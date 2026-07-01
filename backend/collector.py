import os
import asyncio
import logging
from datetime import datetime, timezone
import re

import httpx
from dotenv import load_dotenv

from database import insert_post, bulk_insert_posts, upsert_ai_score
from notifier import should_notify, notify

load_dotenv()

logger = logging.getLogger(__name__)

X_RSS_URL = os.getenv("X_RSS_URL", "")

# Yahoo Finance の一般市場ニュースRSS（無料・無認証、5分ごと更新）
YAHOO_FINANCE_RSS_URL = os.getenv(
    "YAHOO_FINANCE_RSS_URL",
    "https://finance.yahoo.com/news/rssindex",
)

# The New York Times のRSS（無料・無認証）。OpenAIのIPO見送り報道のように
# NYTがスクープし後にReuters等が追随するケースを早期に拾うため、
# Business/Technologyセクションを対象にする（DealBook記事もBusinessに含まれる）
NYT_RSS_URLS = [
    u.strip() for u in os.getenv(
        "NYT_RSS_URLS",
        "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml,"
        "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    ).split(",") if u.strip()
]

# Reuters・Bloomberg・The Informationは公式の無料RSSが無いため、
# Google Newsのsite:検索RSS（無料・無認証、個人の非商用利用が前提）で代替する
GOOGLE_NEWS_SOURCES = {
    "reuters": (
        "Reuters",
        os.getenv(
            "REUTERS_RSS_URL",
            "https://news.google.com/rss/search?q=site:reuters.com+when:1d&hl=en-US&gl=US&ceid=US:en",
        ),
    ),
    "bloomberg": (
        "Bloomberg",
        os.getenv(
            "BLOOMBERG_RSS_URL",
            "https://news.google.com/rss/search?q=site:bloomberg.com+when:1d&hl=en-US&gl=US&ceid=US:en",
        ),
    ),
    "the_information": (
        "The Information",
        os.getenv(
            "THE_INFORMATION_RSS_URL",
            "https://news.google.com/rss/search?q=site:theinformation.com+when:1d&hl=en-US&gl=US&ceid=US:en",
        ),
    ),
}

# CNN が5分ごとに更新している Trump の Truth Social 全投稿アーカイブ
# クラウドIPからアクセス可能（Truth Social 直接アクセスは403）
TRUTH_SOCIAL_JSON_URL = os.getenv(
    "TRUTH_SOCIAL_RSS_URL",
    "https://ix.cnn.io/data/truth-social/truth_archive.json",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}

NEW_POST_CALLBACKS: list = []


def on_new_post(callback):
    NEW_POST_CALLBACKS.append(callback)


def _fire_callbacks(post_id: str, source: str, content: str):
    for cb in NEW_POST_CALLBACKS:
        try:
            cb(post_id, source, content)
        except Exception as e:
            logger.error(f"callback error: {e}")


async def _ai_score_post(post_id: str, content: str, content_type: str = "statement", source: str = ""):
    """新着投稿をGemini無料APIで自動スコアリングしてDBに保存する。

    ニュース(content_type="news")は件数が多く速報性が必要なため、
    人間のスコアリングを待たずAIスコアが閾値以上なら自動でDiscord通知する。
    トランプ発言(statement)側の通知タイミングは変更しない（人間スコア提出時のまま）。
    """
    try:
        from ai_scorer import score_post
        result = await score_post(content, content_type=content_type)
        if result:
            await asyncio.to_thread(
                upsert_ai_score,
                post_id, result["score"], result["sectors"],
                f"AI分析: {result['reason']}" if result.get("reason") else "",
            )
            logger.info(f"[AI Scorer] {post_id[:8]}... → {result['score']}%")
            if content_type == "news" and should_notify(result["score"]):
                notify(content, result["score"], source)
    except Exception as e:
        logger.error(f"[AI Scorer] failed for {post_id[:8]}...: {e}")


# ── Truth Social（CNN アーカイブ JSON）ポーリング ───────────────────────────

async def poll_truth_social():
    """
    CNN が公開している Trump の Truth Social アーカイブ JSON を5分ごとにポーリング。
    初回起動時は全投稿を一括 INSERT（イベントループをブロックしないよう to_thread 使用）。
    """
    seen_ids: set[str] = set()
    newest_date: str | None = None
    first_run = True

    while True:
        try:
            # ファイルが大きい（10MB+）ため timeout を長めに設定
            async with httpx.AsyncClient(timeout=90, follow_redirects=True, headers=HEADERS) as client:
                resp = await client.get(TRUTH_SOCIAL_JSON_URL)
                resp.raise_for_status()

                all_posts = resp.json()
                if not isinstance(all_posts, list):
                    raise ValueError("Unexpected JSON format (expected list)")

            # JSONパース済み。候補を絞り込む
            if first_run:
                candidates = sorted(all_posts, key=lambda x: x.get("created_at", ""))
            else:
                candidates = [
                    p for p in all_posts
                    if newest_date and p.get("created_at", "") > newest_date
                ]

            # 挿入用データを準備（CPU処理のみ、まだDBは触らない）
            to_insert = []
            for post in candidates:
                pid = str(post.get("id", ""))
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)

                content = _strip_html(post.get("content", "")).strip()
                if not content:
                    continue

                created_raw = post.get("created_at", "")
                try:
                    posted_at = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
                except Exception:
                    posted_at = datetime.now(timezone.utc)

                to_insert.append({
                    "source": "truth_social",
                    "post_id": pid,
                    "content": content,
                    "posted_at": posted_at,
                    "url": post.get("url"),
                })

                if created_raw and (newest_date is None or created_raw > newest_date):
                    newest_date = created_raw

            # DB挿入をバックグラウンドスレッドで実行
            if first_run:
                # 起動時の一括ロードは bulk_insert（AIスコアリングはスキップ）
                saved = await asyncio.to_thread(bulk_insert_posts, to_insert) if to_insert else 0
                logger.info(
                    f"[Truth Social] startup: {saved} posts loaded from CNN archive "
                    f"(archive total: {len(all_posts)})"
                )
                first_run = False
            else:
                # 増分更新：個別にINSERTしてIDを取得→AIスコアリング
                new_posts = []
                for post_data in to_insert:
                    post_id = await asyncio.to_thread(
                        insert_post,
                        post_data["source"], post_data["post_id"],
                        post_data["content"], post_data["posted_at"],
                        post_data.get("url"),
                    )
                    if post_id:
                        new_posts.append({"id": post_id, "content": post_data["content"]})
                if new_posts:
                    logger.info(f"[Truth Social] {len(new_posts)} new posts")
                    for p in new_posts:
                        await _ai_score_post(p["id"], p["content"])
                        await asyncio.sleep(4)  # Gemini無料枠: 15RPM制限対策

        except httpx.HTTPStatusError as e:
            logger.error(f"[Truth Social] HTTP {e.response.status_code}: {TRUTH_SOCIAL_JSON_URL}")
        except Exception as e:
            logger.error(f"[Truth Social] error: {e}")

        await asyncio.sleep(300)  # 5分ごとにポーリング


# ── X（旧Twitter）RSS ポーリング ────────────────────────────────────────────

async def poll_x_rss():
    if not X_RSS_URL:
        logger.warning("X_RSS_URL not set — X polling disabled.")
        return

    seen: set[str] = set()
    first_run = True

    while True:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
                resp = await client.get(X_RSS_URL)
                resp.raise_for_status()
                items = _parse_rss(resp.text)

                saved = 0
                for item in items:
                    if item["guid"] in seen:
                        continue
                    seen.add(item["guid"])

                    post_id = insert_post(
                        source="x",
                        post_id=item["guid"],
                        content=item["title"],
                        posted_at=item["pub_date"],
                        url=item.get("link") or None,
                    )
                    if post_id:
                        saved += 1
                        if not first_run:
                            logger.info(f"[X] new post: {item['title'][:80]}")
                            _fire_callbacks(post_id, "x", item["title"])
                            await _ai_score_post(post_id, item["title"])

                if first_run:
                    logger.info(f"[X] startup: {saved} posts saved from RSS")
                    first_run = False

        except Exception as e:
            logger.error(f"[X] RSS poll error: {e}")

        await asyncio.sleep(30)


# ── Yahoo Finance 重要ニュース RSS ポーリング ───────────────────────────────

async def poll_yahoo_finance_news():
    """
    Yahoo Financeの一般市場ニュースRSS（無料・無認証）を5分ごとにポーリングする。
    IPO動向・M&A・金融政策等、市場全体に影響しうるニュースを検知する用途。
    """
    seen: set[str] = set()
    first_run = True

    while True:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
                resp = await client.get(YAHOO_FINANCE_RSS_URL)
                resp.raise_for_status()
                items = _parse_rss(resp.text)

                saved = 0
                for item in items:
                    if item["guid"] in seen:
                        continue
                    seen.add(item["guid"])

                    post_id = insert_post(
                        source="yahoo_finance",
                        post_id=item["guid"],
                        content=item["title"],
                        posted_at=item["pub_date"],
                        url=item.get("link") or None,
                    )
                    if post_id:
                        saved += 1
                        if not first_run:
                            logger.info(f"[Yahoo Finance] new news: {item['title'][:80]}")
                            _fire_callbacks(post_id, "yahoo_finance", item["title"])
                            await _ai_score_post(post_id, item["title"], content_type="news", source="yahoo_finance")
                            await asyncio.sleep(4)  # Gemini無料枠: 15RPM制限対策

                if first_run:
                    logger.info(f"[Yahoo Finance] startup: {saved} news saved from RSS")
                    first_run = False

        except Exception as e:
            logger.error(f"[Yahoo Finance] RSS poll error: {e}")

        await asyncio.sleep(300)  # フィードのttl(5分)に合わせてポーリング


# ── The New York Times RSS ポーリング ───────────────────────────────────────

async def poll_nyt_news():
    """
    NYTのBusiness/Technology RSS（無料・無認証）を5分ごとにポーリングする。
    NYTが最初にスクープし、後からReuter等が追随して世界に広がるニュース
    （例：OpenAIの今年のIPO見送り報道）を早期に検知する用途。
    """
    if not NYT_RSS_URLS:
        logger.warning("NYT_RSS_URLS not set — NYT polling disabled.")
        return

    seen: set[str] = set()
    first_run = True

    while True:
        try:
            saved = 0
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
                for feed_url in NYT_RSS_URLS:
                    resp = await client.get(feed_url)
                    resp.raise_for_status()
                    items = _parse_rss(resp.text)

                    for item in items:
                        if item["guid"] in seen:
                            continue
                        seen.add(item["guid"])

                        content = item["title"]
                        if item.get("description") and item["description"] != item["title"]:
                            content = f"{item['title']}\n\n{item['description']}"

                        post_id = insert_post(
                            source="nyt",
                            post_id=item["guid"],
                            content=content,
                            posted_at=item["pub_date"],
                            url=item.get("link") or None,
                        )
                        if post_id:
                            saved += 1
                            if not first_run:
                                logger.info(f"[NYT] new news: {item['title'][:80]}")
                                _fire_callbacks(post_id, "nyt", content)
                                await _ai_score_post(post_id, content, content_type="news", source="nyt")
                                await asyncio.sleep(4)  # Gemini無料枠: 15RPM制限対策

            if first_run:
                logger.info(f"[NYT] startup: {saved} news saved from RSS")
                first_run = False

        except Exception as e:
            logger.error(f"[NYT] RSS poll error: {e}")

        await asyncio.sleep(300)


# ── Reuters・Bloomberg・The Information（Google News経由）ポーリング ────────

async def poll_google_news_source(source_key: str, label: str, feed_url: str):
    """
    Reuters/Bloomberg/The Informationは公式の無料RSSが無いため、
    Google Newsのsite:検索RSSで代替して見出しを検知する。
    """
    seen: set[str] = set()
    first_run = True

    while True:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers=HEADERS) as client:
                resp = await client.get(feed_url)
                resp.raise_for_status()
                items = _parse_rss(resp.text)

                saved = 0
                for item in items:
                    if item["guid"] in seen:
                        continue
                    seen.add(item["guid"])

                    post_id = insert_post(
                        source=source_key,
                        post_id=item["guid"],
                        content=item["title"],
                        posted_at=item["pub_date"],
                        url=item.get("link") or None,
                    )
                    if post_id:
                        saved += 1
                        if not first_run:
                            logger.info(f"[{label}] new news: {item['title'][:80]}")
                            _fire_callbacks(post_id, source_key, item["title"])
                            await _ai_score_post(post_id, item["title"], content_type="news", source=source_key)
                            await asyncio.sleep(4)  # Gemini無料枠: 15RPM制限対策

                if first_run:
                    logger.info(f"[{label}] startup: {saved} news saved from RSS")
                    first_run = False

        except Exception as e:
            logger.error(f"[{label}] RSS poll error: {e}")

        await asyncio.sleep(300)


# ── RSS parser（X・Yahoo Finance・NYT共通）──────────────────────────────────

def _parse_rss(xml_text: str) -> list[dict]:
    from email.utils import parsedate_to_datetime
    import xml.etree.ElementTree as ET
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            description = _strip_html(item.findtext("description") or "")
            if not title:
                title = description
            link = item.findtext("link") or ""
            guid = item.findtext("guid") or link or ""
            pub_date_str = item.findtext("pubDate") or ""
            pub_date = None
            try:
                pub_date = parsedate_to_datetime(pub_date_str).astimezone(timezone.utc)
            except Exception:
                # Yahoo FinanceのpubDateはISO8601形式（例: 2026-07-01T12:58:34Z）のためフォールバック
                try:
                    pub_date = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00")).astimezone(timezone.utc)
                except Exception:
                    pub_date = datetime.now(timezone.utc)
            if title and guid:
                items.append({
                    "title": title.strip(),
                    "description": description.strip(),
                    "guid": guid,
                    "link": link.strip(),
                    "pub_date": pub_date,
                })
    except Exception as e:
        logger.error(f"RSS parse error: {e}")
    return items


def _strip_html(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html)
    text = (text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
    return text.strip()


async def start_collectors():
    google_news_tasks = [
        poll_google_news_source(key, label, url)
        for key, (label, url) in GOOGLE_NEWS_SOURCES.items()
    ]
    await asyncio.gather(
        poll_truth_social(),
        poll_x_rss(),
        poll_yahoo_finance_news(),
        poll_nyt_news(),
        *google_news_tasks,
    )

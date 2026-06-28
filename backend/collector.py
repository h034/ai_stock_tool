import os
import asyncio
import logging
from datetime import datetime, timezone
import re

import httpx
from dotenv import load_dotenv

from database import insert_post, bulk_insert_posts

load_dotenv()

logger = logging.getLogger(__name__)

X_RSS_URL = os.getenv("X_RSS_URL", "")

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
                })

                if created_raw and (newest_date is None or created_raw > newest_date):
                    newest_date = created_raw

            # DB挿入をバックグラウンドスレッドで実行（イベントループをブロックしない）
            if to_insert:
                saved = await asyncio.to_thread(bulk_insert_posts, to_insert)
            else:
                saved = 0

            if first_run:
                logger.info(
                    f"[Truth Social] startup: {saved} posts loaded from CNN archive "
                    f"(archive total: {len(all_posts)})"
                )
                first_run = False
            elif saved > 0:
                logger.info(f"[Truth Social] {saved} new posts")

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
                    )
                    if post_id:
                        saved += 1
                        if not first_run:
                            logger.info(f"[X] new post: {item['title'][:80]}")
                            _fire_callbacks(post_id, "x", item["title"])

                if first_run:
                    logger.info(f"[X] startup: {saved} posts saved from RSS")
                    first_run = False

        except Exception as e:
            logger.error(f"[X] RSS poll error: {e}")

        await asyncio.sleep(30)


# ── RSS parser（X用）──────────────────────────────────────────────────────────

def _parse_rss(xml_text: str) -> list[dict]:
    from email.utils import parsedate_to_datetime
    import xml.etree.ElementTree as ET
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            if not title:
                desc = item.findtext("description") or ""
                title = _strip_html(desc)
            guid = item.findtext("guid") or item.findtext("link") or ""
            pub_date_str = item.findtext("pubDate") or ""
            try:
                pub_date = parsedate_to_datetime(pub_date_str).astimezone(timezone.utc)
            except Exception:
                pub_date = datetime.now(timezone.utc)
            if title and guid:
                items.append({"title": title.strip(), "guid": guid, "pub_date": pub_date})
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
    await asyncio.gather(
        poll_truth_social(),
        poll_x_rss(),
    )

import os
import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
from dotenv import load_dotenv

from database import insert_post

load_dotenv()

logger = logging.getLogger(__name__)

X_RSS_URL = os.getenv("X_RSS_URL", "")

# Truth Social は直接アクセスするとクラウドIPをブロックする(403)ため、
# RSSHub（オープンソースのRSSプロキシ）経由で取得する。
# 環境変数 TRUTH_SOCIAL_RSS_URL で上書き可能。
TRUTH_SOCIAL_RSS = os.getenv(
    "TRUTH_SOCIAL_RSS_URL",
    "https://rsshub.app/truthsocial/user/realDonaldTrump",
)

# ブラウザとして見せることで IP ブロックを回避
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
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


# ── Truth Social RSS ポーリング ─────────────────────────────────────────

async def poll_truth_social():
    """
    Truth Social の公開RSSフィードをポーリング。
    API（/api/v1/accounts/...）はクラウドIPをブロックするためRSSを使用。
    """
    seen: set[str] = set()
    first_run = True

    while True:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=HEADERS) as client:
                resp = await client.get(TRUTH_SOCIAL_RSS)
                resp.raise_for_status()
                items = _parse_rss(resp.text)

                saved = 0
                for item in items:
                    if item["guid"] in seen:
                        continue
                    seen.add(item["guid"])

                    post_id = insert_post(
                        source="truth_social",
                        post_id=item["guid"],
                        content=item["title"],
                        posted_at=item["pub_date"],
                    )
                    if post_id:
                        saved += 1
                        if not first_run:
                            logger.info(f"[Truth Social] new post: {item['title'][:80]}")
                            _fire_callbacks(post_id, "truth_social", item["title"])

                if first_run:
                    logger.info(f"[Truth Social] startup: {saved} posts saved from RSS")
                    first_run = False

        except httpx.HTTPStatusError as e:
            logger.error(f"[Truth Social] HTTP {e.response.status_code} on RSS: {TRUTH_SOCIAL_RSS}")
        except Exception as e:
            logger.error(f"[Truth Social] RSS poll error: {e}")

        await asyncio.sleep(60)


# ── X（旧Twitter）RSS ポーリング ────────────────────────────────────────

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


# ── RSS parser ──────────────────────────────────────────────────────────

def _parse_rss(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    import re
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            # タイトル優先、なければ description から HTML 除去
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
    import re
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

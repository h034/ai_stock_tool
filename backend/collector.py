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

TRUTH_SOCIAL_INSTANCE = os.getenv("TRUTH_SOCIAL_INSTANCE", "truthsocial.com")
TRUMP_TRUTH_SOCIAL_ID = os.getenv("TRUMP_TRUTH_SOCIAL_ID", "107780257626128497")
X_RSS_URL = os.getenv("X_RSS_URL", "")

NEW_POST_CALLBACKS: list = []


def on_new_post(callback):
    NEW_POST_CALLBACKS.append(callback)


def _fire_callbacks(post_id: str, source: str, content: str):
    for cb in NEW_POST_CALLBACKS:
        try:
            cb(post_id, source, content)
        except Exception as e:
            logger.error(f"callback error: {e}")


# ── Truth Social REST ポーリング ────────────────────────────────────────

async def poll_truth_social():
    """
    WebSocket は 403 になるため REST API でポーリング。
    Mastodon 互換エンドポイント：GET /api/v1/accounts/:id/statuses
    """
    api_url = f"https://{TRUTH_SOCIAL_INSTANCE}/api/v1/accounts/{TRUMP_TRUTH_SOCIAL_ID}/statuses"
    seen: set[str] = set()
    first_run = True

    while True:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                resp = await client.get(api_url, params={"limit": 20})
                resp.raise_for_status()
                statuses = resp.json()

                for status in statuses:
                    sid = str(status.get("id", ""))
                    if not sid or sid in seen:
                        continue
                    seen.add(sid)

                    content = _strip_html(status.get("content", ""))
                    if not content:
                        continue

                    try:
                        posted_at = datetime.fromisoformat(
                            status["created_at"].replace("Z", "+00:00")
                        )
                    except Exception:
                        posted_at = datetime.now(timezone.utc)

                    post_id = insert_post(
                        source="truth_social",
                        post_id=sid,
                        content=content,
                        posted_at=posted_at,
                    )
                    if post_id:
                        if not first_run:
                            logger.info(f"[Truth Social] new post: {content[:80]}")
                            _fire_callbacks(post_id, "truth_social", content)

                if first_run:
                    logger.info(f"[Truth Social] loaded {len(statuses)} posts on startup")
                    first_run = False

        except httpx.HTTPStatusError as e:
            logger.error(f"[Truth Social] HTTP {e.response.status_code}: {e}")
        except Exception as e:
            logger.error(f"[Truth Social] poll error: {e}")

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
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(X_RSS_URL)
                resp.raise_for_status()
                items = _parse_rss(resp.text)

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
                    if post_id and not first_run:
                        logger.info(f"[X] new post: {item['title'][:80]}")
                        _fire_callbacks(post_id, "x", item["title"])

                if first_run:
                    logger.info(f"[X] loaded {len(items)} posts on startup")
                    first_run = False

        except Exception as e:
            logger.error(f"[X] RSS poll error: {e}")

        await asyncio.sleep(30)


def _parse_rss(xml_text: str) -> list[dict]:
    import xml.etree.ElementTree as ET
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            guid = item.findtext("guid") or item.findtext("link") or ""
            pub_date_str = item.findtext("pubDate") or ""
            try:
                pub_date = parsedate_to_datetime(pub_date_str).astimezone(timezone.utc)
            except Exception:
                pub_date = datetime.now(timezone.utc)
            items.append({"title": title, "guid": guid, "pub_date": pub_date})
    except Exception as e:
        logger.error(f"RSS parse error: {e}")
    return items


def _strip_html(html: str) -> str:
    import re
    text = re.sub(r"<[^>]+>", "", html)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return text.strip()


async def fetch_historical_truth_social(target: int = 100):
    """起動時に過去投稿を最大 target 件まとめて取得する。"""
    api_url = f"https://{TRUTH_SOCIAL_INSTANCE}/api/v1/accounts/{TRUMP_TRUTH_SOCIAL_ID}/statuses"
    total = 0
    max_id: str | None = None

    logger.info(f"[Truth Social] fetching up to {target} historical posts...")
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        while total < target:
            params: dict = {"limit": 40}
            if max_id:
                params["max_id"] = max_id
            try:
                resp = await client.get(api_url, params=params)
                resp.raise_for_status()
                statuses = resp.json()
                if not statuses:
                    break
                for status in statuses:
                    sid = str(status.get("id", ""))
                    content = _strip_html(status.get("content", ""))
                    if not content or not sid:
                        continue
                    try:
                        posted_at = datetime.fromisoformat(
                            status["created_at"].replace("Z", "+00:00")
                        )
                    except Exception:
                        posted_at = datetime.now(timezone.utc)
                    if insert_post("truth_social", sid, content, posted_at):
                        total += 1
                max_id = statuses[-1]["id"]
                await asyncio.sleep(1)  # rate limit
            except Exception as e:
                logger.error(f"[Truth Social] historical fetch error: {e}")
                break

    logger.info(f"[Truth Social] historical fetch done: {total} posts saved")


async def start_collectors():
    await fetch_historical_truth_social(target=100)
    await asyncio.gather(
        poll_truth_social(),
        poll_x_rss(),
    )

import os
import json
import asyncio
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx
import websockets
from dotenv import load_dotenv

from database import insert_post

load_dotenv()

logger = logging.getLogger(__name__)

TRUTH_SOCIAL_INSTANCE = os.getenv("TRUTH_SOCIAL_INSTANCE", "truthsocial.com")
TRUMP_TRUTH_SOCIAL_ID = os.getenv("TRUMP_TRUTH_SOCIAL_ID", "107780257626128497")
X_RSS_URL = os.getenv("X_RSS_URL", "")  # RSS.app などのRSSフィードURL

NEW_POST_CALLBACKS: list = []


def on_new_post(callback):
    """新規投稿時に呼ぶコールバックを登録"""
    NEW_POST_CALLBACKS.append(callback)


def _fire_callbacks(post_id: str, source: str, content: str):
    for cb in NEW_POST_CALLBACKS:
        try:
            cb(post_id, source, content)
        except Exception as e:
            logger.error(f"callback error: {e}")


# ── Truth Social WebSocket ──────────────────────────────────────────

async def stream_truth_social():
    ws_url = f"wss://{TRUTH_SOCIAL_INSTANCE}/api/v1/streaming?stream=public:local"
    backoff = 5
    while True:
        try:
            logger.info(f"Connecting to Truth Social: {ws_url}")
            async with websockets.connect(ws_url, ping_interval=30) as ws:
                backoff = 5
                async for raw in ws:
                    try:
                        event = json.loads(raw)
                        if event.get("event") != "update":
                            continue
                        payload = json.loads(event["payload"])
                        account_id = payload.get("account", {}).get("id", "")
                        if account_id != TRUMP_TRUTH_SOCIAL_ID:
                            continue
                        content = _strip_html(payload.get("content", ""))
                        if not content:
                            continue
                        posted_at = datetime.fromisoformat(
                            payload["created_at"].replace("Z", "+00:00")
                        )
                        post_id = insert_post(
                            source="truth_social",
                            post_id=payload["id"],
                            content=content,
                            posted_at=posted_at,
                        )
                        if post_id:
                            logger.info(f"[Truth Social] new post: {content[:80]}")
                            _fire_callbacks(post_id, "truth_social", content)
                    except Exception as e:
                        logger.error(f"parse error: {e}")
        except Exception as e:
            logger.warning(f"WebSocket disconnected: {e}. Retry in {backoff}s")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 300)


# ── X（旧Twitter）RSS ポーリング ────────────────────────────────────

async def poll_x_rss():
    if not X_RSS_URL:
        logger.warning("X_RSS_URL not set. X polling disabled.")
        return
    seen: set[str] = set()
    while True:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
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
                    if post_id:
                        logger.info(f"[X] new post: {item['title'][:80]}")
                        _fire_callbacks(post_id, "x", item["title"])
        except Exception as e:
            logger.error(f"X RSS poll error: {e}")
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
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return text.strip()


async def start_collectors():
    await asyncio.gather(
        stream_truth_social(),
        poll_x_rss(),
    )

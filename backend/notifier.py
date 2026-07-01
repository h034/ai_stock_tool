import os
import logging
import smtplib
from email.mime.text import MIMEText

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "70"))


def should_notify(score: int) -> bool:
    return score >= SCORE_THRESHOLD


SOURCE_LABELS = {
    "truth_social": "Truth Social",
    "x": "X",
    "yahoo_finance": "Yahoo Finance ニュース",
    "nyt": "The New York Times",
    "reuters": "Reuters",
    "bloomberg": "Bloomberg",
    "the_information": "The Information",
}

NEWS_SOURCES = {"yahoo_finance", "nyt", "reuters", "bloomberg", "the_information"}


def notify(content: str, score: int, source: str):
    label = SOURCE_LABELS.get(source, source)
    is_news = source in NEWS_SOURCES
    color = 0xef4444 if score >= 70 else 0xf59e0b  # red / yellow
    if DISCORD_WEBHOOK_URL:
        _notify_discord(content, score, label, color, is_news)
    if SMTP_HOST and NOTIFY_EMAIL:
        subject = "重要ニュースアラート" if is_news else "トランプ発言アラート"
        message = f"[{label}] スコア {score}%\n\n{content}"
        _notify_email(f"{subject}（スコア {score}%）", message)


def _notify_discord(content: str, score: int, label: str, color: int, is_news: bool = False):
    try:
        # Discord Embed で見やすく送信
        short = content[:300] + ("..." if len(content) > 300 else "")
        title = f"📰 重要ニュースアラート — スコア {score}%" if is_news else f"🚨 トランプ発言アラート — スコア {score}%"
        payload = {
            "embeds": [{
                "title": title,
                "description": short,
                "color": color,
                "fields": [
                    {"name": "ソース", "value": label, "inline": True},
                    {"name": "スコア", "value": f"{score}%", "inline": True},
                ],
                "footer": {"text": "トランプ発言影響スコアラー"},
            }]
        }
        resp = httpx.post(DISCORD_WEBHOOK_URL, json=payload, timeout=10)
        if resp.status_code in (200, 204):
            logger.info(f"Discord notification sent (score={score}%)")
        else:
            logger.error(f"Discord webhook failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"Discord notify error: {e}")


def _notify_email(subject: str, body: str):
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = NOTIFY_EMAIL
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASS)
            smtp.send_message(msg)
        logger.info("Email notification sent")
    except Exception as e:
        logger.error(f"Email notify error: {e}")

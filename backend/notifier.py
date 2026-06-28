import os
import logging
import smtplib
from email.mime.text import MIMEText

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

LINE_NOTIFY_TOKEN = os.getenv("LINE_NOTIFY_TOKEN", "")
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
NOTIFY_EMAIL = os.getenv("NOTIFY_EMAIL", "")
SCORE_THRESHOLD = int(os.getenv("SCORE_THRESHOLD", "70"))


def should_notify(score: int) -> bool:
    return score >= SCORE_THRESHOLD


def notify(content: str, score: int, source: str):
    label = "Truth Social" if source == "truth_social" else "X"
    message = f"[{label}] スコア {score}%\n\n{content}"
    if LINE_NOTIFY_TOKEN:
        _notify_line(message)
    if SMTP_HOST and NOTIFY_EMAIL:
        _notify_email(f"トランプ発言アラート（スコア {score}%）", message)


def _notify_line(message: str):
    try:
        resp = httpx.post(
            "https://notify-api.line.me/api/notify",
            headers={"Authorization": f"Bearer {LINE_NOTIFY_TOKEN}"},
            data={"message": message},
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info("LINE notification sent")
        else:
            logger.error(f"LINE notify failed: {resp.status_code} {resp.text}")
    except Exception as e:
        logger.error(f"LINE notify error: {e}")


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

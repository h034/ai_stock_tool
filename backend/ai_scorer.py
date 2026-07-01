import asyncio
import json
import logging
import os

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.0-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"
)

_PROMPT = """あなたは株式市場アナリストです。以下のトランプ大統領の発言を分析し、米国株式市場への影響度を0〜100でスコアリングしてください。

スコア基準:
- 0〜20: 市場影響なし・ほぼなし（一般的な政治・個人発言）
- 21〜40: 軽微な影響（曖昧な政策示唆）
- 41〜60: 中程度の影響（具体的な政策・人事に関する発言）
- 61〜80: 大きな影響（関税・規制・制裁等の具体的発表）
- 81〜100: 非常に大きな影響（市場急変の可能性がある緊急発言）

影響を受けるセクターを以下から選んでください（複数可、該当なければ空配列）:
エネルギー, テクノロジー, 金融, ヘルスケア, 素材, 輸送・物流, 防衛, 農業, 小売, 自動車

発言:
{content}

以下のJSON形式のみで回答してください（コードブロック不要）:
{{"score": <0〜100の整数>, "sectors": [<セクター名>], "reason": "<40文字以内の日本語で理由>"}}"""


async def score_post(content: str) -> dict | None:
    """Gemini無料APIで発言をスコアリングする。失敗時はNoneを返す。"""
    if not GEMINI_API_KEY:
        logger.warning("[AI Scorer] GEMINI_API_KEY not set — skipping")
        return None

    prompt = _PROMPT.format(content=content[:1200])
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 200},
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{GEMINI_URL}?key={GEMINI_API_KEY}", json=payload
            )
            resp.raise_for_status()
            data = resp.json()

        text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)
        score = max(0, min(100, int(result["score"])))
        sectors = [s for s in result.get("sectors", []) if isinstance(s, str)]
        reason = str(result.get("reason", ""))[:100]

        logger.info(f"[AI Scorer] score={score} sectors={sectors}")
        return {"score": score, "sectors": sectors, "reason": reason}

    except Exception as e:
        logger.error(f"[AI Scorer] Error: {e}")
        return None

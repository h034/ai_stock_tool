import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from database import init_db, get_posts, upsert_score
from collector import start_collectors, on_new_post
from notifier import should_notify, notify

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("DB initialized")
    asyncio.create_task(start_collectors())
    logger.info("Collectors started")
    yield


app = FastAPI(title="Trump Statement Scorer API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScoreRequest(BaseModel):
    post_id: str
    human_score: Optional[int] = Field(None, ge=0, le=100)
    sectors: list[str] = []
    memo: str = ""


@app.get("/posts")
def list_posts(limit: int = 50):
    posts = get_posts(limit=limit)
    for p in posts:
        if p.get("posted_at"):
            p["posted_at"] = p["posted_at"].isoformat()
        if p.get("fetched_at"):
            p["fetched_at"] = p["fetched_at"].isoformat()
        if p.get("scored_at"):
            p["scored_at"] = p["scored_at"].isoformat()
    return posts


@app.post("/scores")
def save_score(req: ScoreRequest):
    score_id = upsert_score(
        post_id=req.post_id,
        human_score=req.human_score,
        ai_score=None,
        sectors=req.sectors,
        memo=req.memo,
    )
    # スコアが閾値を超えていたら通知
    if req.human_score is not None and should_notify(req.human_score):
        posts = get_posts(limit=200)
        target = next((p for p in posts if p["id"] == req.post_id), None)
        if target:
            notify(target["content"], req.human_score, target["source"])
    return {"score_id": score_id}


@app.get("/health")
def health():
    return {"status": "ok"}

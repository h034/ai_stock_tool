import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from database import (
    init_db, get_posts, upsert_score, insert_post,
    upsert_user, log_activity, get_activity_logs, get_user_activity, get_user_score_stats,
)
from collector import start_collectors, on_new_post
from notifier import should_notify, notify
from auth import (
    get_current_user, get_optional_user,
    get_discord_login_url, fetch_discord_user, create_jwt,
    FRONTEND_URL,
)

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


# ── Auth ────────────────────────────────────────────────────────────────────

@app.get("/auth/discord")
def discord_login():
    url = get_discord_login_url()
    return RedirectResponse(url)


@app.get("/auth/discord/callback")
async def discord_callback(code: str):
    try:
        discord_user = await fetch_discord_user(code)
    except Exception as e:
        logger.error(f"Discord OAuth error: {e}")
        return RedirectResponse(f"{FRONTEND_URL}/?error=auth_failed")

    user = upsert_user(
        discord_id=discord_user["id"],
        username=discord_user["username"],
        discriminator=discord_user.get("discriminator", "0"),
        avatar=discord_user.get("avatar"),
    )
    log_activity(
        user_id=str(user["id"]),
        username=user["username"],
        avatar=user["avatar"],
        action="LOGIN",
        detail={"discord_id": discord_user["id"]},
    )

    token = create_jwt(
        user_id=str(user["id"]),
        discord_id=discord_user["id"],
        username=user["username"],
        avatar=user["avatar"],
        is_admin=user["is_admin"],
    )
    return RedirectResponse(f"{FRONTEND_URL}/?token={token}")


@app.get("/me")
def get_me(user: dict = Depends(get_current_user)):
    stats = get_user_score_stats(user["sub"])
    activity = get_user_activity(user["sub"])
    return {
        "id": user["sub"],
        "discord_id": user["discord_id"],
        "username": user["username"],
        "avatar": user.get("avatar"),
        "is_admin": user.get("is_admin", False),
        "stats": {k: (float(v) if v is not None else 0) for k, v in stats.items()},
        "recent_activity": activity,
    }


# ── Activity Logs ────────────────────────────────────────────────────────────

@app.get("/activity-logs")
def list_activity_logs(limit: int = 100, user: dict = Depends(get_current_user)):
    return get_activity_logs(limit=limit)


# ── Posts & Scores ────────────────────────────────────────────────────────────

class ScoreRequest(BaseModel):
    post_id: str
    human_score: Optional[int] = Field(None, ge=0, le=100)
    sectors: list[str] = []
    memo: str = ""


@app.get("/posts")
def list_posts(limit: int = 50, user: dict = Depends(get_current_user)):
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
def save_score(req: ScoreRequest, user: dict = Depends(get_current_user)):
    score_id = upsert_score(
        post_id=req.post_id,
        human_score=req.human_score,
        ai_score=None,
        sectors=req.sectors,
        memo=req.memo,
        user_id=user["sub"],
        scored_by_username=user["username"],
    )
    log_activity(
        user_id=user["sub"],
        username=user["username"],
        avatar=user.get("avatar"),
        action="SCORE_SAVED",
        detail={
            "post_id": req.post_id,
            "score": req.human_score,
            "sectors": req.sectors,
            "memo": req.memo,
        },
    )
    if req.human_score is not None and should_notify(req.human_score):
        posts = get_posts(limit=200)
        target = next((p for p in posts if p["id"] == req.post_id), None)
        if target:
            notify(target["content"], req.human_score, target["source"])
    return {"score_id": score_id}


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Admin: Manual Post Injection ─────────────────────────────────────────────

class ManualPost(BaseModel):
    source: str = "truth_social"
    content: str
    posted_at: Optional[str] = None  # ISO8601, defaults to now


class ManualPostRequest(BaseModel):
    posts: list[ManualPost]


@app.post("/admin/posts")
def admin_inject_posts(req: ManualPostRequest, user: dict = Depends(get_current_user)):
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Admin only")

    from datetime import datetime, timezone
    import hashlib

    inserted = 0
    for p in req.posts:
        posted_at = (
            datetime.fromisoformat(p.posted_at.replace("Z", "+00:00"))
            if p.posted_at
            else datetime.now(timezone.utc)
        )
        post_id_hash = hashlib.md5(f"{p.source}:{p.content[:100]}".encode()).hexdigest()
        result = insert_post(
            source=p.source,
            post_id=post_id_hash,
            content=p.content,
            posted_at=posted_at,
        )
        if result:
            inserted += 1

    return {"inserted": inserted, "total": len(req.posts)}

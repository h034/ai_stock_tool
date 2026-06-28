import json
import os
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor, Json
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY,
                    discord_id VARCHAR UNIQUE NOT NULL,
                    username VARCHAR NOT NULL,
                    discriminator VARCHAR,
                    avatar VARCHAR,
                    is_admin BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS posts (
                    id UUID PRIMARY KEY,
                    source VARCHAR NOT NULL,
                    post_id VARCHAR NOT NULL,
                    content TEXT NOT NULL,
                    posted_at TIMESTAMP NOT NULL,
                    fetched_at TIMESTAMP NOT NULL,
                    UNIQUE(source, post_id)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS scores (
                    id UUID PRIMARY KEY,
                    post_id UUID REFERENCES posts(id) ON DELETE CASCADE,
                    user_id UUID REFERENCES users(id),
                    scored_by_username VARCHAR,
                    human_score INTEGER CHECK (human_score BETWEEN 0 AND 100),
                    ai_score INTEGER CHECK (ai_score BETWEEN 0 AND 100),
                    sectors TEXT[],
                    memo TEXT,
                    scored_at TIMESTAMP NOT NULL
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id UUID PRIMARY KEY,
                    user_id UUID REFERENCES users(id),
                    username VARCHAR NOT NULL,
                    avatar VARCHAR,
                    action VARCHAR NOT NULL,
                    detail JSONB,
                    created_at TIMESTAMP NOT NULL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts(posted_at DESC)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_activity_created_at ON activity_logs(created_at DESC)
            """)
            # Migration: add columns to scores if they don't exist
            for stmt in [
                "ALTER TABLE scores ADD COLUMN user_id UUID REFERENCES users(id)",
                "ALTER TABLE scores ADD COLUMN scored_by_username VARCHAR",
            ]:
                cur.execute(f"""
                    DO $$ BEGIN {stmt};
                    EXCEPTION WHEN duplicate_column THEN NULL;
                    END $$;
                """)


# ── Users ──────────────────────────────────────────────────────────────────

def upsert_user(discord_id: str, username: str, discriminator: str, avatar: str | None) -> dict:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE discord_id = %s", (discord_id,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                    UPDATE users SET username = %s, discriminator = %s, avatar = %s
                    WHERE discord_id = %s
                    RETURNING id, discord_id, username, avatar, is_admin
                """, (username, discriminator, avatar, discord_id))
            else:
                uid = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO users (id, discord_id, username, discriminator, avatar, is_admin, created_at)
                    VALUES (%s, %s, %s, %s, %s, FALSE, %s)
                    RETURNING id, discord_id, username, avatar, is_admin
                """, (uid, discord_id, username, discriminator, avatar, datetime.now(timezone.utc)))
            return dict(cur.fetchone())


# ── Activity Logs ───────────────────────────────────────────────────────────

def log_activity(user_id: str, username: str, avatar: str | None, action: str, detail: dict | None = None):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO activity_logs (id, user_id, username, avatar, action, detail, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (str(uuid.uuid4()), user_id, username, avatar, action,
                  Json(detail) if detail else None, datetime.now(timezone.utc)))


def get_activity_logs(limit: int = 100) -> list[dict]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id::text, username, avatar, action, detail, created_at
                FROM activity_logs
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
            return rows


def get_user_activity(user_id: str, limit: int = 30) -> list[dict]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, action, detail, created_at
                FROM activity_logs
                WHERE user_id = %s
                ORDER BY created_at DESC
                LIMIT %s
            """, (user_id, limit))
            rows = [dict(r) for r in cur.fetchall()]
            for r in rows:
                if r.get("created_at"):
                    r["created_at"] = r["created_at"].isoformat()
            return rows


def get_user_score_stats(user_id: str) -> dict:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as total_scored,
                       ROUND(AVG(human_score), 1) as avg_score,
                       COUNT(*) FILTER (WHERE human_score >= 70) as high_impact_count
                FROM scores
                WHERE user_id = %s AND human_score IS NOT NULL
            """, (user_id,))
            return dict(cur.fetchone())


# ── Posts & Scores ──────────────────────────────────────────────────────────

def insert_post(source: str, post_id: str, content: str, posted_at: datetime) -> str | None:
    new_id = str(uuid.uuid4())
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO posts (id, source, post_id, content, posted_at, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (source, post_id) DO NOTHING
                RETURNING id
            """, (new_id, source, post_id, content, posted_at, datetime.now(timezone.utc)))
            row = cur.fetchone()
            return row["id"] if row else None


def bulk_insert_posts(posts: list[dict]) -> int:
    """
    posts: list of {source, post_id, content, posted_at}
    1トランザクションで一括挿入。重複はスキップ。
    挿入件数を返す。
    """
    if not posts:
        return 0
    now = datetime.now(timezone.utc)
    values = [
        (str(uuid.uuid4()), p["source"], p["post_id"], p["content"], p["posted_at"], now)
        for p in posts
    ]
    with get_db() as conn:
        with conn.cursor() as cur:
            from psycopg2.extras import execute_values
            execute_values(
                cur,
                """
                INSERT INTO posts (id, source, post_id, content, posted_at, fetched_at)
                VALUES %s
                ON CONFLICT (source, post_id) DO NOTHING
                """,
                values,
                page_size=500,
            )
            return cur.rowcount


def upsert_score(
    post_id: str,
    human_score: int | None,
    ai_score: int | None,
    sectors: list[str],
    memo: str,
    user_id: str | None = None,
    scored_by_username: str | None = None,
) -> str:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM scores WHERE post_id = %s", (post_id,))
            existing = cur.fetchone()
            now = datetime.now(timezone.utc)
            if existing:
                cur.execute("""
                    UPDATE scores
                    SET human_score = %s, ai_score = %s, sectors = %s, memo = %s,
                        scored_at = %s, user_id = %s, scored_by_username = %s
                    WHERE post_id = %s
                """, (human_score, ai_score, sectors, memo, now, user_id, scored_by_username, post_id))
                return existing["id"]
            else:
                score_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO scores
                        (id, post_id, human_score, ai_score, sectors, memo, scored_at, user_id, scored_by_username)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (score_id, post_id, human_score, ai_score, sectors, memo, now, user_id, scored_by_username))
                return score_id


def get_posts(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.source, p.content, p.posted_at, p.fetched_at,
                       s.human_score, s.ai_score, s.sectors, s.memo, s.scored_by_username
                FROM posts p
                LEFT JOIN scores s ON s.post_id = p.id
                ORDER BY p.posted_at DESC
                LIMIT %s
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

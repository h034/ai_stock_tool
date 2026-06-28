import os
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
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
                    human_score INTEGER CHECK (human_score BETWEEN 0 AND 100),
                    ai_score INTEGER CHECK (ai_score BETWEEN 0 AND 100),
                    sectors TEXT[],
                    memo TEXT,
                    scored_at TIMESTAMP NOT NULL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_posts_posted_at ON posts(posted_at DESC)
            """)


def insert_post(source: str, post_id: str, content: str, posted_at: datetime) -> str | None:
    """重複チェックしながら投稿を保存。新規保存ならUUID返す、重複ならNone。"""
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


def upsert_score(post_id: str, human_score: int | None, ai_score: int | None,
                 sectors: list[str], memo: str) -> str:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM scores WHERE post_id = %s", (post_id,))
            existing = cur.fetchone()
            if existing:
                cur.execute("""
                    UPDATE scores
                    SET human_score = %s, ai_score = %s, sectors = %s, memo = %s, scored_at = %s
                    WHERE post_id = %s
                """, (human_score, ai_score, sectors, memo, datetime.now(timezone.utc), post_id))
                return existing["id"]
            else:
                score_id = str(uuid.uuid4())
                cur.execute("""
                    INSERT INTO scores (id, post_id, human_score, ai_score, sectors, memo, scored_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (score_id, post_id, human_score, ai_score, sectors, memo,
                      datetime.now(timezone.utc)))
                return score_id


def get_posts(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT p.id, p.source, p.content, p.posted_at, p.fetched_at,
                       s.human_score, s.ai_score, s.sectors, s.memo
                FROM posts p
                LEFT JOIN scores s ON s.post_id = p.id
                ORDER BY p.posted_at DESC
                LIMIT %s
            """, (limit,))
            return [dict(row) for row in cur.fetchall()]

import os
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

DISCORD_CLIENT_ID = os.getenv("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.getenv("DISCORD_CLIENT_SECRET", "")
DISCORD_REDIRECT_URI = os.getenv(
    "DISCORD_REDIRECT_URI",
    "https://ai-stock-tool-api.onrender.com/auth/discord/callback",
)
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://ai-stock-tool.vercel.app")
JWT_SECRET = os.getenv("JWT_SECRET", "change-me-use-a-long-random-string-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_DAYS = 30

_AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
_TOKEN_URL = "https://discord.com/api/oauth2/token"
_USER_URL = "https://discord.com/api/users/@me"

security = HTTPBearer(auto_error=False)


def create_jwt(user_id: str, discord_id: str, username: str, avatar: str | None, is_admin: bool) -> str:
    payload = {
        "sub": user_id,
        "discord_id": discord_id,
        "username": username,
        "avatar": avatar,
        "is_admin": is_admin,
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def _decode(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return _decode(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_optional_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict | None:
    if credentials is None:
        return None
    try:
        return _decode(credentials.credentials)
    except JWTError:
        return None


def get_discord_login_url() -> str:
    params = urllib.parse.urlencode({
        "client_id": DISCORD_CLIENT_ID,
        "redirect_uri": DISCORD_REDIRECT_URI,
        "response_type": "code",
        "scope": "identify",
    })
    return f"{_AUTHORIZE_URL}?{params}"


async def fetch_discord_user(code: str) -> dict:
    async with httpx.AsyncClient() as client:
        token_res = await client.post(
            _TOKEN_URL,
            data={
                "client_id": DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        token_res.raise_for_status()
        access_token = token_res.json()["access_token"]

        user_res = await client.get(
            _USER_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        user_res.raise_for_status()
        return user_res.json()

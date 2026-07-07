"""Authentication routes — Feishu bot-based login."""

import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db import get_db

router = APIRouter(prefix="/api/auth", tags=["auth"])

# In-memory token store: token -> {user_name, open_id, display_name, expires_at}
_login_tokens: dict[str, dict] = {}
TOKEN_TTL = 300  # 5 minutes


class TokenRequest(BaseModel):
    open_id: str


def _cleanup_expired():
    """Remove expired tokens."""
    now = time.time()
    expired = [t for t, v in _login_tokens.items() if v["expires_at"] < now]
    for t in expired:
        del _login_tokens[t]


@router.post("/token")
def create_login_token(req: TokenRequest, request: Request):
    """Generate a one-time login token for a Feishu user.

    Called internally by the Feishu bot when a user sends 'login'.
    Maps open_id to kanban user, generates a short-lived token.
    """
    _cleanup_expired()

    with get_db() as conn:
        user = conn.execute(
            "SELECT id, name, display_name, role FROM users WHERE feishu_open_id=?",
            (req.open_id,)
        ).fetchone()
        if not user:
            raise HTTPException(404, "No kanban user linked to this Feishu account")

    token = secrets.token_urlsafe(32)
    _login_tokens[token] = {
        "user_name": user["name"],
        "display_name": user["display_name"] or user["name"],
        "role": user["role"],
        "open_id": req.open_id,
        "expires_at": time.time() + TOKEN_TTL,
    }
    return {"token": token, "user_name": user["name"]}


@router.get("/login")
def login_with_token(token: str):
    """Validate a one-time login token and return user info.

    Called by the frontend when user clicks the login link from Feishu.
    Token is consumed (one-time use).
    """
    _cleanup_expired()

    if token not in _login_tokens:
        raise HTTPException(401, "Invalid or expired login token")

    data = _login_tokens.pop(token)
    return {
        "user_name": data["user_name"],
        "display_name": data["display_name"],
        "role": data["role"],
    }

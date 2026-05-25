"""User CRUD routes."""

import uuid

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, _require_human
from helpers import now_iso
from models import UserCreate, UserUpdate, NotificationPrefUpdate

router = APIRouter(prefix="/api", tags=["users"])


@router.get("/users")
def list_users():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
        return [dict(r) for r in rows]


@router.post("/users")
def create_user(u: UserCreate):
    uid = uuid.uuid4().hex[:12]
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE name=?", (u.name,)).fetchone()
        if existing:
            return {"id": existing["id"], "existing": True}
        conn.execute("INSERT INTO users (id, name, display_name, role) VALUES (?, ?, ?, ?)",
                     (uid, u.name, u.display_name or u.name, u.role))
        return {"id": uid, "role": u.role}


@router.put("/users/{uid}")
def update_user(uid: str, u: UserUpdate, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
        if not existing:
            raise HTTPException(404, "User not found")
        # Role changes require a human actor to prevent privilege escalation
        if u.role is not None:
            _require_human(conn, actor, "change user roles")
        updates, params = [], []
        if u.display_name is not None:
            updates.append("display_name=?")
            params.append(u.display_name)
        if u.role is not None:
            updates.append("role=?")
            params.append(u.role)
        if updates:
            params.append(uid)
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id=?", params)
        return {"id": uid, "updated": True}


@router.get("/users/{uid}/notifications")
def get_notification_prefs(uid: str):
    """Get notification preferences for a user."""
    with get_db() as conn:
        user = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            raise HTTPException(404, "User not found")
        row = conn.execute(
            "SELECT * FROM notification_preferences WHERE user_id=?", (uid,)
        ).fetchone()
        if not row:
            # Return defaults
            return {"user_id": uid, "channel": "feishu", "overdue": 1,
                    "stale": 1, "blocker": 1, "digest": 1, "stale_days": 3}
        return dict(row)


@router.put("/users/{uid}/notifications")
def update_notification_prefs(uid: str, prefs: NotificationPrefUpdate, request: Request):
    """Update notification preferences for a user."""
    actor = get_actor(request)
    with get_db() as conn:
        user = conn.execute("SELECT id FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            raise HTTPException(404, "User not found")
        existing = conn.execute(
            "SELECT user_id FROM notification_preferences WHERE user_id=?", (uid,)
        ).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO notification_preferences (user_id, channel) VALUES (?, 'feishu')",
                (uid,)
            )
        updates, params = [], []
        for k, v in prefs.model_dump(exclude_none=True).items():
            updates.append(f"{k}=?")
            params.append(v)
        if updates:
            updates.append("updated_at=?")
            params.append(now_iso())
            params.append(uid)
            conn.execute(
                f"UPDATE notification_preferences SET {', '.join(updates)} WHERE user_id=?",
                params
            )
        return {"ok": True}


@router.get("/users/{uid}/activity")
def user_activity(uid: str, limit: int = 100):
    with get_db() as conn:
        user = conn.execute("SELECT name FROM users WHERE id=?", (uid,)).fetchone()
        if not user:
            raise HTTPException(404, "User not found")
        rows = conn.execute(
            "SELECT * FROM activity_log WHERE actor=? ORDER BY created_at DESC LIMIT ?",
            (user["name"], limit)
        ).fetchall()
        return [dict(r) for r in rows]

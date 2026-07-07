"""Comment routes."""

import uuid

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso
from models import CommentCreate

router = APIRouter(prefix="/api", tags=["comments"])


@router.get("/comments/{entity_type}/{entity_id}")
def list_comments(entity_type: str, entity_id: str):
    valid = {"task", "workstream", "blocker", "bug"}
    if entity_type not in valid:
        raise HTTPException(400, f"Invalid entity_type: {entity_type}")
    with get_db() as conn:
        comments = conn.execute(
            "SELECT * FROM comments WHERE entity_type=? AND entity_id=? ORDER BY created_at ASC",
            (entity_type, entity_id)
        ).fetchall()
        activities = conn.execute(
            "SELECT * FROM activity_log WHERE entity_type=? AND entity_id=? ORDER BY created_at ASC",
            (entity_type, entity_id)
        ).fetchall()
        return {"comments": [dict(r) for r in comments], "activity": [dict(r) for r in activities]}


@router.post("/comments/{entity_type}/{entity_id}")
def add_comment(entity_type: str, entity_id: str, c: CommentCreate, request: Request):
    valid = {"task", "workstream", "blocker", "bug"}
    if entity_type not in valid:
        raise HTTPException(400, f"Invalid entity_type: {entity_type}")
    cid = uuid.uuid4().hex[:12]
    actor = get_actor(request)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO comments (id, entity_type, entity_id, author, body, created_at) VALUES (?,?,?,?,?,?)",
            (cid, entity_type, entity_id, actor, c.body, now_iso())
        )
        log_activity(conn, entity_type, entity_id, "commented", actor=actor, detail=c.body[:80])
    return {"id": cid}


@router.delete("/comments/{cid}")
def delete_comment(cid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        row = conn.execute("SELECT id, entity_type, entity_id FROM comments WHERE id=?", (cid,)).fetchone()
        if not row:
            raise HTTPException(404, "Comment not found")
        conn.execute("DELETE FROM comments WHERE id=?", (cid,))
        log_activity(conn, row["entity_type"], row["entity_id"], "comment_deleted", actor=actor)
    return {"ok": True}

"""Blocker routes."""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso, _notify_context
from models import BlockerCreate, BlockerUpdate

try:
    import feishu_notify
except ImportError:
    feishu_notify = None  # type: ignore

router = APIRouter(prefix="/api", tags=["blockers"])


@router.get("/blockers")
def list_blockers(workstream_id: Optional[str] = None, active_only: bool = True):
    with get_db() as conn:
        q = "SELECT * FROM blockers"
        params: list = []
        clauses = ["deleted_at IS NULL"]
        if workstream_id:
            clauses.append("workstream_id=?")
            params.append(workstream_id)
        if active_only:
            clauses.append("resolved=0")
        q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY created_at DESC"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


@router.post("/blockers")
def create_blocker(b: BlockerCreate, request: Request):
    bid = uuid.uuid4().hex[:12]
    actor = get_actor(request)
    with get_db() as conn:
        if not conn.execute("SELECT id FROM workstreams WHERE id=? AND deleted_at IS NULL",
                            (b.workstream_id,)).fetchone():
            raise HTTPException(404, "Workstream not found")
        ts = now_iso()
        conn.execute(
            "INSERT INTO blockers (id, workstream_id, description_en, description_zh, "
            "assignee, notes, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (bid, b.workstream_id, b.description_en, b.description_zh,
             b.assignee, b.notes, ts, ts)
        )
        log_activity(conn, "blocker", bid, "created", actor=actor, detail=b.description_en[:80])
        if feishu_notify:
            proj, ws_title = _notify_context(conn, b.workstream_id)
            feishu_notify.notify_blocker_created(b.description_en, proj, ws_title, actor)
        return {"id": bid}


@router.put("/blockers/{bid}")
def update_blocker(bid: str, b: BlockerUpdate, request: Request):
    actor = get_actor(request)
    fields: list = []
    vals: list = []
    for k, v in b.model_dump(exclude_none=True).items():
        fields.append(f"{k}=?")
        vals.append(v)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at=?")
    vals.append(now_iso())
    vals.append(bid)
    with get_db() as conn:
        row = conn.execute("SELECT id FROM blockers WHERE id=? AND deleted_at IS NULL", (bid,)).fetchone()
        if not row:
            raise HTTPException(404, "Blocker not found")
        conn.execute(f"UPDATE blockers SET {', '.join(fields)} WHERE id=? AND deleted_at IS NULL", vals)
        log_activity(conn, "blocker", bid, "updated", actor=actor)
        return {"ok": True}


@router.put("/blockers/{bid}/resolve")
def resolve_blocker(bid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        blocker = conn.execute("SELECT * FROM blockers WHERE id=? AND deleted_at IS NULL", (bid,)).fetchone()
        if not blocker:
            raise HTTPException(404, "Blocker not found")
        ts = now_iso()
        conn.execute("UPDATE blockers SET resolved=1, resolved_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (ts, ts, bid))
        log_activity(conn, "blocker", bid, "resolved", actor=actor)
        if feishu_notify:
            proj, ws_title = _notify_context(conn, blocker["workstream_id"])
            feishu_notify.notify_blocker_resolved(blocker["description_en"], proj, ws_title, actor)
        return {"ok": True}

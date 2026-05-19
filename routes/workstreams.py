"""Workstream CRUD routes."""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso, _require_human
from models import WorkstreamCreate, WorkstreamUpdate, ReorderRequest

router = APIRouter(prefix="/api", tags=["workstreams"])


@router.get("/workstreams")
def list_workstreams(project_id: Optional[str] = None):
    with get_db() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM workstreams WHERE project_id=? AND deleted_at IS NULL ORDER BY sort_order, title_en",
                (project_id,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM workstreams WHERE deleted_at IS NULL ORDER BY sort_order, title_en").fetchall()
        return [dict(r) for r in rows]


@router.post("/workstreams")
def create_workstream(w: WorkstreamCreate, request: Request):
    wid = uuid.uuid4().hex[:12]
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "create workstreams")
        if not conn.execute("SELECT id FROM projects WHERE id=? AND deleted_at IS NULL",
                            (w.project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        conn.execute(
            "INSERT INTO workstreams (id, project_id, title_en, title_zh, owner, priority, status, summary_en, summary_zh) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (wid, w.project_id, w.title_en, w.title_zh, w.owner, w.priority, w.status, w.summary_en, w.summary_zh)
        )
        log_activity(conn, "workstream", wid, "created", actor=actor, detail=w.title_en)
        return {"id": wid}


@router.put("/workstreams/reorder")
def reorder_workstreams(req: ReorderRequest, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        for item in req.items:
            conn.execute("UPDATE workstreams SET sort_order=?, updated_at=? WHERE id=?",
                         (item.sort_order, now_iso(), item.id))
        log_activity(conn, "workstream", "bulk", "reordered", actor=actor,
                     detail=f"{len(req.items)} workstreams")
    return {"ok": True}


@router.put("/workstreams/{wid}")
def update_workstream(wid: str, w: WorkstreamUpdate, request: Request):
    fields, vals = [], []
    for k, v in w.model_dump(exclude_none=True).items():
        fields.append(f"{k}=?")
        vals.append(v)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at=?")
    vals.append(now_iso())
    vals.append(wid)
    actor = get_actor(request)
    with get_db() as conn:
        if w.priority is not None:
            _require_human(conn, actor, "change workstream priorities")
        cur = conn.execute(f"UPDATE workstreams SET {', '.join(fields)} WHERE id=? AND deleted_at IS NULL", vals)
        if cur.rowcount == 0:
            raise HTTPException(404, "Workstream not found")
        log_activity(conn, "workstream", wid, "updated", actor=get_actor(request))
        return {"ok": True}


@router.delete("/workstreams/{wid}")
def delete_workstream(wid: str, request: Request):
    actor = get_actor(request)
    ts = now_iso()
    with get_db() as conn:
        _require_human(conn, actor, "delete workstreams")
        cur = conn.execute("UPDATE workstreams SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, wid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Workstream not found")
        # Cascade soft-delete to child tasks, blockers, recurring tasks
        conn.execute("UPDATE tasks SET deleted_at=? WHERE workstream_id=? AND deleted_at IS NULL", (ts, wid))
        conn.execute("UPDATE blockers SET deleted_at=? WHERE workstream_id=? AND deleted_at IS NULL", (ts, wid))
        conn.execute("UPDATE recurring_tasks SET deleted_at=? WHERE workstream_id=? AND deleted_at IS NULL", (ts, wid))
        log_activity(conn, "workstream", wid, "deleted", actor=actor)
        return {"ok": True}

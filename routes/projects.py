"""Project CRUD routes."""

import json
import uuid

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from db import get_db
from helpers import get_actor, log_activity, now_iso, _require_human
from models import ProjectCreate, ProjectUpdate, ReorderRequest


class WipLimitsUpdate(BaseModel):
    doing: Optional[int] = None
    in_review: Optional[int] = None

router = APIRouter(prefix="/api", tags=["projects"])


@router.get("/projects")
def list_projects():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY sort_order, name_en").fetchall()
        return [dict(r) for r in rows]


@router.get("/projects/{pid}")
def get_project(pid: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=? AND deleted_at IS NULL", (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        return dict(row)


@router.post("/projects")
def create_project(p: ProjectCreate, request: Request):
    pid = uuid.uuid4().hex[:12]
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "create projects")
        conn.execute(
            "INSERT INTO projects (id, name_en, name_zh, description, color) VALUES (?, ?, ?, ?, ?)",
            (pid, p.name_en, p.name_zh, p.description, p.color)
        )
        log_activity(conn, "project", pid, "created", actor=actor, detail=p.name_en)
        return {"id": pid}


@router.put("/projects/reorder")
def reorder_projects(req: ReorderRequest, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        for item in req.items:
            conn.execute("UPDATE projects SET sort_order=?, updated_at=? WHERE id=?",
                         (item.sort_order, now_iso(), item.id))
        log_activity(conn, "project", "bulk", "reordered", actor=actor,
                     detail=f"{len(req.items)} projects")
    return {"ok": True}


@router.put("/projects/{pid}")
def update_project(pid: str, p: ProjectUpdate, request: Request):
    fields, vals = [], []
    for k, v in p.model_dump(exclude_none=True).items():
        fields.append(f"{k}=?")
        vals.append(v)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at=?")
    vals.append(now_iso())
    vals.append(pid)
    with get_db() as conn:
        cur = conn.execute(f"UPDATE projects SET {', '.join(fields)} WHERE id=? AND deleted_at IS NULL", vals)
        if cur.rowcount == 0:
            raise HTTPException(404, "Project not found")
        log_activity(conn, "project", pid, "updated", actor=get_actor(request))
        return {"ok": True}


@router.delete("/projects/{pid}")
def delete_project(pid: str, request: Request):
    actor = get_actor(request)
    ts = now_iso()
    with get_db() as conn:
        _require_human(conn, actor, "delete projects")
        cur = conn.execute("UPDATE projects SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (ts, pid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Project not found")
        # Cascade soft-delete to child workstreams and their children
        ws_ids = [r["id"] for r in conn.execute(
            "SELECT id FROM workstreams WHERE project_id=? AND deleted_at IS NULL", (pid,)).fetchall()]
        if ws_ids:
            placeholders = ",".join("?" * len(ws_ids))
            conn.execute(f"UPDATE workstreams SET deleted_at=? WHERE id IN ({placeholders})", [ts] + ws_ids)
            conn.execute(f"UPDATE tasks SET deleted_at=? WHERE workstream_id IN ({placeholders}) AND deleted_at IS NULL",
                         [ts] + ws_ids)
            conn.execute(f"UPDATE blockers SET deleted_at=? WHERE workstream_id IN ({placeholders}) AND deleted_at IS NULL",
                         [ts] + ws_ids)
            conn.execute(f"UPDATE recurring_tasks SET deleted_at=? WHERE workstream_id IN ({placeholders}) AND deleted_at IS NULL",
                         [ts] + ws_ids)
        log_activity(conn, "project", pid, "deleted", actor=actor)
        return {"ok": True}


@router.get("/projects/{pid}/wip-limits")
def get_wip_limits(pid: str):
    """Get WIP limits for a project."""
    with get_db() as conn:
        row = conn.execute("SELECT wip_limits FROM projects WHERE id=? AND deleted_at IS NULL",
                           (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        return json.loads(row["wip_limits"] or "{}")


@router.put("/projects/{pid}/wip-limits")
def update_wip_limits(pid: str, limits: WipLimitsUpdate, request: Request):
    """Set WIP limits for a project. Soft limits only (visual warning)."""
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "set WIP limits")
        row = conn.execute("SELECT wip_limits FROM projects WHERE id=? AND deleted_at IS NULL",
                           (pid,)).fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        current = json.loads(row["wip_limits"] or "{}")
        for k, v in limits.model_dump(exclude_none=True).items():
            current[k] = v
        conn.execute("UPDATE projects SET wip_limits=?, updated_at=? WHERE id=?",
                     (json.dumps(current), now_iso(), pid))
        log_activity(conn, "project", pid, "wip_limits_updated", actor=actor,
                     detail=json.dumps(current))
        return current

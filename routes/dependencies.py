"""Task dependency routes."""

import sqlite3
import uuid

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity
from models import DependencyCreate

router = APIRouter(prefix="/api", tags=["dependencies"])


@router.get("/tasks/{tid}/dependencies")
def get_dependencies(tid: str):
    with get_db() as conn:
        task = conn.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
        if not task:
            raise HTTPException(404, "Task not found")
        blocked_by = conn.execute(
            "SELECT td.id as dep_id, td.dep_type, t.id, t.title_en, t.title_zh, t.status, t.assignee "
            "FROM task_dependencies td JOIN tasks t ON t.id=td.depends_on_id "
            "WHERE td.task_id=? AND t.deleted_at IS NULL", (tid,)).fetchall()
        blocks = conn.execute(
            "SELECT td.id as dep_id, td.dep_type, t.id, t.title_en, t.title_zh, t.status, t.assignee "
            "FROM task_dependencies td JOIN tasks t ON t.id=td.task_id "
            "WHERE td.depends_on_id=? AND t.deleted_at IS NULL", (tid,)).fetchall()
        return {
            "blocked_by": [dict(r) for r in blocked_by if r["dep_type"] == "blocked_by"],
            "blocks": [dict(r) for r in blocks if r["dep_type"] == "blocked_by"],
            "related": [dict(r) for r in blocked_by if r["dep_type"] == "related"]
                      + [dict(r) for r in blocks if r["dep_type"] == "related"],
        }


@router.post("/tasks/{tid}/dependencies")
def add_dependency(tid: str, dep: DependencyCreate, request: Request):
    if tid == dep.depends_on_id:
        raise HTTPException(400, "A task cannot depend on itself")
    actor = get_actor(request)
    did = uuid.uuid4().hex[:12]
    with get_db() as conn:
        for check_id in (tid, dep.depends_on_id):
            if not conn.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (check_id,)).fetchone():
                raise HTTPException(404, f"Task {check_id} not found")
        try:
            conn.execute("INSERT INTO task_dependencies (id, task_id, depends_on_id, dep_type) VALUES (?,?,?,?)",
                         (did, tid, dep.depends_on_id, dep.dep_type))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Dependency already exists")
        log_activity(conn, "task", tid, "dependency_added", actor=actor,
                     detail=f"{dep.dep_type}: {dep.depends_on_id}")
    return {"id": did}


@router.delete("/tasks/{tid}/dependencies/{dep_id}")
def remove_dependency(tid: str, dep_id: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute("DELETE FROM task_dependencies WHERE id=? AND task_id=?", (dep_id, tid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Dependency not found")
        log_activity(conn, "task", tid, "dependency_removed", actor=actor, detail=dep_id)
    return {"ok": True}


@router.get("/tasks/{tid}/dependency-check")
def check_dependencies(tid: str):
    with get_db() as conn:
        deps = conn.execute(
            "SELECT t.id, t.title_en, t.status FROM task_dependencies td "
            "JOIN tasks t ON t.id=td.depends_on_id "
            "WHERE td.task_id=? AND td.dep_type='blocked_by' AND t.deleted_at IS NULL", (tid,)).fetchall()
        unmet = [dict(d) for d in deps if d["status"] != "done"]
        return {"can_start": len(unmet) == 0, "unmet": unmet}

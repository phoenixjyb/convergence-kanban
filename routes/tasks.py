"""Task CRUD, reorder, and bulk action routes."""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso, _require_human, _notify_context
from models import TaskCreate, TaskUpdate, ReorderRequest, BulkTaskAction

import notify

router = APIRouter(prefix="/api", tags=["tasks"])


@router.get("/tasks")
def list_tasks(workstream_id: Optional[str] = None, parent_task_id: Optional[str] = None,
               assignee: Optional[str] = None, status: Optional[str] = None):
    with get_db() as conn:
        clauses = ["deleted_at IS NULL"]
        params: list = []
        if workstream_id:
            clauses.append("workstream_id=?")
            params.append(workstream_id)
        if parent_task_id:
            clauses.append("parent_task_id=?")
            params.append(parent_task_id)
        if assignee:
            clauses.append("assignee=?")
            params.append(assignee)
        if status:
            clauses.append("status=?")
            params.append(status)
        q = f"SELECT * FROM tasks WHERE {' AND '.join(clauses)} ORDER BY sort_order, created_at"
        rows = conn.execute(q, params).fetchall()
        tasks = []
        for r in rows:
            d = dict(r)
            sub = conn.execute(
                "SELECT count(*) c, sum(CASE WHEN status='done' THEN 1 ELSE 0 END) done FROM tasks WHERE parent_task_id=? AND deleted_at IS NULL",
                (d["id"],)
            ).fetchone()
            d["subtask_count"] = sub["c"]
            d["subtask_done"] = sub["done"] or 0
            tasks.append(d)
        return tasks


@router.get("/tasks/{tid}/subtasks")
def list_subtasks(tid: str):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE parent_task_id=? AND deleted_at IS NULL ORDER BY sort_order, created_at",
            (tid,)
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/tasks")
def create_task(t: TaskCreate, request: Request):
    tid = uuid.uuid4().hex[:12]
    actor = get_actor(request)
    with get_db() as conn:
        if not conn.execute("SELECT id FROM workstreams WHERE id=? AND deleted_at IS NULL",
                            (t.workstream_id,)).fetchone():
            raise HTTPException(404, "Workstream not found")
        if t.parent_task_id:
            if not conn.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL",
                                (t.parent_task_id,)).fetchone():
                raise HTTPException(404, "Parent task not found")
        conn.execute(
            "INSERT INTO tasks (id, workstream_id, parent_task_id, title_en, title_zh, assignee, status, priority, start_date, due_date, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (tid, t.workstream_id, t.parent_task_id, t.title_en, t.title_zh, t.assignee, t.status, t.priority, t.start_date, t.due_date, t.notes)
        )
        log_activity(conn, "task", tid, "created", actor=actor, detail=t.title_en)
        proj, ws_title = _notify_context(conn, t.workstream_id)
        notify.notify_task_created(t.title_en, proj, ws_title, t.assignee, actor)
        return {"id": tid}


@router.put("/tasks/reorder")
def reorder_tasks(req: ReorderRequest, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        for item in req.items:
            conn.execute("UPDATE tasks SET sort_order=?, updated_at=? WHERE id=?",
                         (item.sort_order, now_iso(), item.id))
        log_activity(conn, "task", "bulk", "reordered", actor=actor,
                     detail=f"{len(req.items)} tasks")
    return {"ok": True}


@router.post("/tasks/bulk")
def bulk_task_action(req: BulkTaskAction, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        if req.action == "delete":
            _require_human(conn, actor, "bulk delete tasks")
            for tid in req.task_ids:
                conn.execute("UPDATE tasks SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                             (now_iso(), tid))
            log_activity(conn, "task", "bulk", "bulk_deleted", actor=actor,
                         detail=f"{len(req.task_ids)} tasks")
        elif req.action == "update" and req.fields:
            allowed = {"status", "assignee", "workstream_id"}
            updates = {k: v for k, v in req.fields.items() if k in allowed}
            if not updates:
                raise HTTPException(400, "No valid fields to update.")
            valid_statuses = {"todo", "doing", "in_review", "done", "blocked", "abandoned"}
            if "status" in updates and updates["status"] not in valid_statuses:
                raise HTTPException(400, f"Invalid status: {updates['status']}")
            if updates.get("status") == "done":
                _require_human(conn, actor, "bulk mark tasks as done — use 'in_review' instead")
            if updates.get("status") == "abandoned":
                _require_human(conn, actor, "bulk mark tasks as abandoned — humans only")
            set_clause = ", ".join(f"{k}=?" for k in updates)
            vals = list(updates.values()) + [now_iso()]
            for tid in req.task_ids:
                conn.execute(f"UPDATE tasks SET {set_clause}, updated_at=? WHERE id=? AND deleted_at IS NULL",
                             vals + [tid])
            log_activity(conn, "task", "bulk", "bulk_updated", actor=actor,
                         detail=f"{len(req.task_ids)} tasks: {updates}")
    return {"ok": True, "affected": len(req.task_ids)}


@router.put("/tasks/{tid}")
def update_task(tid: str, t: TaskUpdate, request: Request):
    fields, vals = [], []
    for k, v in t.model_dump(exclude_none=True).items():
        fields.append(f"{k}=?")
        vals.append(v)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at=?")
    vals.append(now_iso())
    vals.append(tid)
    actor = get_actor(request)
    with get_db() as conn:
        if t.status == "done":
            _require_human(conn, actor, "mark tasks as done — use 'in_review' instead")
        if t.status == "abandoned":
            _require_human(conn, actor, "mark tasks as abandoned — humans only")
        old_row = conn.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
        if not old_row:
            raise HTTPException(404, "Task not found")
        conn.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=? AND deleted_at IS NULL", vals)
        log_activity(conn, "task", tid, "updated", actor=actor)
        if t.status and t.status != old_row["status"]:
            proj, ws_title = _notify_context(conn, old_row["workstream_id"])
            notify.notify_task_status_changed(
                old_row["title_en"], proj, ws_title, old_row["status"], t.status, actor)
        warnings = []
        if t.assignee:
            user_row = conn.execute(
                "SELECT feishu_open_id FROM users WHERE name=? COLLATE NOCASE OR display_name=? COLLATE NOCASE",
                (t.assignee, t.assignee)).fetchone()
            if not user_row:
                warnings.append(f"User '{t.assignee}' not found in system")
            elif not user_row["feishu_open_id"]:
                warnings.append(f"User '{t.assignee}' has no Feishu account linked — will not appear as executor on Bitable")
        if t.status == "doing":
            unmet = conn.execute(
                "SELECT t2.title_en FROM task_dependencies td JOIN tasks t2 ON t2.id=td.depends_on_id "
                "WHERE td.task_id=? AND td.dep_type='blocked_by' AND t2.status!='done' AND t2.deleted_at IS NULL",
                (tid,)).fetchall()
            warnings.extend(f"Blocked by: {r['title_en']} (not done)" for r in unmet)
        return {"ok": True, "warnings": warnings}


@router.delete("/tasks/{tid}")
def delete_task(tid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "delete tasks")
        cur = conn.execute("UPDATE tasks SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (now_iso(), tid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Task not found")
        log_activity(conn, "task", tid, "deleted", actor=actor)
        return {"ok": True}

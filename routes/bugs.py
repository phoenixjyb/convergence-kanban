"""Bug CRUD and suggestion routes."""

import json
import uuid
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from db import get_db
from helpers import get_actor, log_activity, now_iso, _require_human, _is_bot, generate_bug_display_id

import notify

from models import BugCreate, BugUpdate


class BugLinkTasks(BaseModel):
    task_ids: List[str]

router = APIRouter(prefix="/api", tags=["bugs"])


def _decode_issue_images(raw):
    """Parse issue_images TEXT (JSON) column to a list. Returns [] on anything else."""
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (ValueError, TypeError):
        return []


def _bug_row_to_dict(row):
    d = dict(row)
    d["issue_images"] = _decode_issue_images(d.get("issue_images"))
    return d


@router.get("/bugs")
def list_bugs(project_id: Optional[str] = None, status: Optional[str] = None,
              workstream_id: Optional[str] = None, source: Optional[str] = None):
    with get_db() as conn:
        q = "SELECT * FROM bugs"
        params: list = []
        clauses = ["deleted_at IS NULL"]
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        if status:
            clauses.append("status=?")
            params.append(status)
        if workstream_id:
            clauses.append("workstream_id=?")
            params.append(workstream_id)
        if source:
            clauses.append("COALESCE(source,'manual')=?")
            params.append(source)
        q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC"
        rows = conn.execute(q, params).fetchall()
        return [_bug_row_to_dict(r) for r in rows]


@router.get("/bugs/{bug_id}")
def get_bug(bug_id: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM bugs WHERE id=? AND deleted_at IS NULL", (bug_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Bug not found")
        bug = _bug_row_to_dict(row)
        if bug.get("project_id"):
            p = conn.execute("SELECT name_en FROM projects WHERE id=?", (bug["project_id"],)).fetchone()
            bug["project_name"] = p["name_en"] if p else ""
        if bug.get("workstream_id"):
            w = conn.execute("SELECT title_en FROM workstreams WHERE id=?", (bug["workstream_id"],)).fetchone()
            bug["workstream_name"] = w["title_en"] if w else ""
        # Linked tasks (many-to-many)
        linked = conn.execute(
            "SELECT t.id, t.title_en, t.title_zh, t.status, t.assignee, w.title_en as workstream_name "
            "FROM bug_task_links btl JOIN tasks t ON btl.task_id=t.id "
            "LEFT JOIN workstreams w ON t.workstream_id=w.id "
            "WHERE btl.bug_id=? AND t.deleted_at IS NULL", (bug_id,)
        ).fetchall()
        bug["linked_tasks"] = [dict(r) for r in linked]
        # Backward compat: task_name from legacy task_id
        if bug.get("task_id"):
            t = conn.execute("SELECT title_en FROM tasks WHERE id=?", (bug["task_id"],)).fetchone()
            bug["task_name"] = t["title_en"] if t else ""
        return bug


@router.post("/bugs")
def create_bug(b: BugCreate, request: Request):
    bid = uuid.uuid4().hex[:12]
    actor = get_actor(request)
    with get_db() as conn:
        # Bots can only create agent-sourced bugs (rd-bugs-list).
        # Manual bugs are reserved for the QA team via the Feishu Bitable.
        # Coerce silently — bots accidentally omitting source='agent' would
        # otherwise default to 'manual' and pollute the QA team's table.
        if _is_bot(conn, actor) and b.source != "agent":
            b.source = "agent"
        images_json = json.dumps(b.issue_images, ensure_ascii=False) if b.issue_images else ""
        display_id = generate_bug_display_id(conn, b.source)
        conn.execute(
            "INSERT INTO bugs (id, title, description, severity, status, reporter, assignee, "
            "project_id, workstream_id, task_id, environment, steps_to_reproduce, "
            "issue_time, feature, repro_rate, issue_version, device_id, issue_images, source, display_id, "
            "fix_method, fix_version, fix_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (bid, b.title, b.description, b.severity, b.status, b.reporter or actor,
             b.assignee, b.project_id, b.workstream_id, b.task_id,
             b.environment, b.steps_to_reproduce,
             b.issue_time, b.feature, b.repro_rate,
             b.issue_version, b.device_id, images_json, b.source, display_id,
             b.fix_method, b.fix_version, b.fix_date)
        )
        # Also insert into junction table if task_id provided
        if b.task_id:
            conn.execute("INSERT OR IGNORE INTO bug_task_links (bug_id, task_id) VALUES (?, ?)",
                         (bid, b.task_id))
        log_activity(conn, "bug", bid, "created", actor=actor, detail=f"{display_id} {b.title[:70]}")
        notify.notify_bug_created(b.title, b.severity or "unknown", b.reporter or actor)
        return {"id": bid, "display_id": display_id}


@router.put("/bugs/{bug_id}")
def update_bug(bug_id: str, b: BugUpdate, request: Request):
    fields, vals = [], []
    for k, v in b.model_dump(exclude_none=True).items():
        fields.append(f"{k}=?")
        # issue_images arrives as a list; the column stores JSON text.
        vals.append(json.dumps(v, ensure_ascii=False) if k == "issue_images" else v)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at=?")
    vals.append(now_iso())
    if b.status in ("resolved", "closed"):
        fields.append("resolved_at=?")
        vals.append(now_iso())
    vals.append(bug_id)
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute(f"UPDATE bugs SET {', '.join(fields)} WHERE id=? AND deleted_at IS NULL", vals)
        if cur.rowcount == 0:
            raise HTTPException(404, "Bug not found")
        log_activity(conn, "bug", bug_id, "updated", actor=actor)
        return {"ok": True}


@router.delete("/bugs/{bug_id}")
def delete_bug(bug_id: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "delete bugs")
        cur = conn.execute("UPDATE bugs SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (now_iso(), bug_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Bug not found")
        log_activity(conn, "bug", bug_id, "deleted", actor=actor)
        return {"ok": True}


@router.get("/bugs/{bug_id}/tasks")
def bug_linked_tasks(bug_id: str):
    """List all tasks linked to a bug."""
    with get_db() as conn:
        bug = conn.execute("SELECT id FROM bugs WHERE id=? AND deleted_at IS NULL", (bug_id,)).fetchone()
        if not bug:
            raise HTTPException(404, "Bug not found")
        rows = conn.execute(
            "SELECT t.id, t.title_en, t.title_zh, t.status, t.assignee, "
            "w.title_en as workstream_name, p.name_en as project_name "
            "FROM bug_task_links btl JOIN tasks t ON btl.task_id=t.id "
            "LEFT JOIN workstreams w ON t.workstream_id=w.id "
            "LEFT JOIN projects p ON w.project_id=p.id "
            "WHERE btl.bug_id=? AND t.deleted_at IS NULL", (bug_id,)
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/bugs/{bug_id}/tasks")
def link_bug_tasks(bug_id: str, body: BugLinkTasks, request: Request):
    """Link one or more tasks to a bug."""
    actor = get_actor(request)
    with get_db() as conn:
        bug = conn.execute("SELECT id FROM bugs WHERE id=? AND deleted_at IS NULL", (bug_id,)).fetchone()
        if not bug:
            raise HTTPException(404, "Bug not found")
        linked = 0
        for tid in body.task_ids:
            task = conn.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
            if not task:
                continue
            conn.execute("INSERT OR IGNORE INTO bug_task_links (bug_id, task_id) VALUES (?, ?)",
                         (bug_id, tid))
            linked += 1
        # Update legacy task_id to first linked task if not set
        if linked and not conn.execute("SELECT task_id FROM bugs WHERE id=? AND task_id IS NOT NULL AND task_id != ''",
                                       (bug_id,)).fetchone():
            conn.execute("UPDATE bugs SET task_id=? WHERE id=?", (body.task_ids[0], bug_id))
        log_activity(conn, "bug", bug_id, "linked_tasks", actor=actor,
                     detail=f"linked {linked} task(s)")
        return {"linked": linked}


@router.delete("/bugs/{bug_id}/tasks/{task_id}")
def unlink_bug_task(bug_id: str, task_id: str, request: Request):
    """Unlink a task from a bug."""
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute("DELETE FROM bug_task_links WHERE bug_id=? AND task_id=?",
                           (bug_id, task_id))
        if cur.rowcount == 0:
            raise HTTPException(404, "Link not found")
        # Clear legacy task_id if it matches
        conn.execute("UPDATE bugs SET task_id=NULL WHERE id=? AND task_id=?", (bug_id, task_id))
        log_activity(conn, "bug", bug_id, "unlinked_task", actor=actor, detail=task_id)
        return {"ok": True}


@router.get("/tasks/{task_id}/bugs")
def task_linked_bugs(task_id: str):
    """List all bugs linked to a task (reverse lookup)."""
    with get_db() as conn:
        task = conn.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,)).fetchone()
        if not task:
            raise HTTPException(404, "Task not found")
        rows = conn.execute(
            "SELECT b.id, b.title, b.severity, b.status, b.assignee "
            "FROM bug_task_links btl JOIN bugs b ON btl.bug_id=b.id "
            "WHERE btl.task_id=? AND b.deleted_at IS NULL "
            "ORDER BY CASE b.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END", (task_id,)
        ).fetchall()
        return [dict(r) for r in rows]


@router.get("/bugs/{bug_id}/suggest-links")
def suggest_bug_links(bug_id: str):
    """Suggest workstreams/tasks that may be related to this bug by keyword overlap."""
    with get_db() as conn:
        bug = conn.execute("SELECT * FROM bugs WHERE id=? AND deleted_at IS NULL", (bug_id,)).fetchone()
        if not bug:
            raise HTTPException(404, "Bug not found")

        bug_text = f"{bug['title']} {bug['description']} {bug['steps_to_reproduce']}".lower()
        words = set(bug_text.split())

        ws_rows = conn.execute(
            "SELECT w.*, p.name_en as project_name FROM workstreams w "
            "JOIN projects p ON w.project_id=p.id "
            "WHERE w.deleted_at IS NULL"
        ).fetchall()
        ws_scores = []
        for ws in ws_rows:
            ws_text = f"{ws['title_en']} {ws['title_zh']} {ws['summary_en']} {ws['summary_zh']}".lower()
            ws_words = set(ws_text.split())
            overlap = len(words & ws_words)
            if overlap > 0:
                ws_scores.append({
                    "type": "workstream",
                    "id": ws["id"],
                    "title": ws["title_en"],
                    "project_name": ws["project_name"],
                    "score": overlap,
                    "status": ws["status"],
                })

        task_rows = conn.execute(
            "SELECT t.*, w.title_en as ws_title, p.name_en as project_name "
            "FROM tasks t JOIN workstreams w ON t.workstream_id=w.id "
            "JOIN projects p ON w.project_id=p.id "
            "WHERE t.deleted_at IS NULL"
        ).fetchall()
        task_scores = []
        for task in task_rows:
            task_text = f"{task['title_en']} {task['title_zh']} {task['notes']}".lower()
            task_words = set(task_text.split())
            overlap = len(words & task_words)
            if overlap > 0:
                task_scores.append({
                    "type": "task",
                    "id": task["id"],
                    "title": task["title_en"],
                    "workstream": task["ws_title"],
                    "project_name": task["project_name"],
                    "score": overlap,
                    "status": task["status"],
                })

        ws_scores.sort(key=lambda x: x["score"], reverse=True)
        task_scores.sort(key=lambda x: x["score"], reverse=True)

        return {
            "workstreams": ws_scores[:5],
            "tasks": task_scores[:10],
        }

"""Template CRUD and apply routes."""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso
from models import TemplateCreate, TemplateApply

router = APIRouter(prefix="/api", tags=["templates"])


@router.post("/templates")
def create_template(tmpl: TemplateCreate, request: Request):
    tid = uuid.uuid4().hex[:12]
    actor = get_actor(request)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO templates (id, name, project_id, structure, created_at) VALUES (?, ?, ?, ?, ?)",
            (tid, tmpl.name, tmpl.project_id, json.dumps(tmpl.structure), now_iso()))
        log_activity(conn, "template", tid, "created", actor=actor, detail=tmpl.name)
        return {"id": tid}


@router.get("/templates")
def list_templates(project_id: Optional[str] = None):
    with get_db() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM templates WHERE deleted_at IS NULL AND (project_id=? OR project_id IS NULL) ORDER BY name",
                (project_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM templates WHERE deleted_at IS NULL ORDER BY name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["structure"] = json.loads(d["structure"])
            result.append(d)
        return result


@router.delete("/templates/{tid}")
def delete_template(tid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute("UPDATE templates SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                           (now_iso(), tid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Template not found")
        log_activity(conn, "template", tid, "deleted", actor=actor)
        return {"ok": True}


@router.post("/templates/{tid}/apply")
def apply_template(tid: str, body: TemplateApply, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        tmpl = conn.execute("SELECT * FROM templates WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone()
        if not tmpl:
            raise HTTPException(404, "Template not found")
        structure = json.loads(tmpl["structure"])
        created_ids = []
        now = now_iso()
        for i, item in enumerate(structure):
            task_id = uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO tasks (id, workstream_id, title_en, title_zh, assignee, status, notes, sort_order, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (task_id, body.workstream_id, item.get("title_en", ""), item.get("title_zh", ""),
                 item.get("assignee", ""), item.get("status", "todo"), item.get("notes", ""),
                 i * 10, now, now))
            created_ids.append(task_id)
            for j, sub in enumerate(item.get("subtasks", [])):
                sub_id = uuid.uuid4().hex[:12]
                conn.execute(
                    "INSERT INTO tasks (id, workstream_id, parent_task_id, title_en, title_zh, assignee, status, sort_order, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sub_id, body.workstream_id, task_id, sub.get("title_en", ""), sub.get("title_zh", ""),
                     sub.get("assignee", ""), sub.get("status", "todo"), j * 10, now, now))
        log_activity(conn, "template", tid, "applied", actor=actor,
                     detail=f"Created {len(created_ids)} tasks in {body.workstream_id}")
        return {"ok": True, "created": len(created_ids), "task_ids": created_ids}

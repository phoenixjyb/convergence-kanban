"""Activity log and import routes."""

import uuid
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso
from models import ImportPayload

router = APIRouter(prefix="/api", tags=["activity"])

STATUS_MAP = {
    "✅ merged": "done", "stable": "stable", "deployed": "stable",
    "doc-ready": "stable", "dry-run-verified": "in-progress",
    "in-progress": "in-progress", "planned": "planned",
}


@router.get("/activity")
def get_activity(limit: int = 50):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/import/session-status")
def import_session_status(payload: ImportPayload):
    """Import workstreams from session-status.json format into a project."""
    project_id = payload.project_id
    data = payload.data
    workstreams = data.get("workstreams", {})
    imported = 0

    with get_db() as conn:
        row = conn.execute("SELECT id FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(404, f"Project {project_id} not found")

        for key, ws in workstreams.items():
            wid = key[:8]
            title = ws.get("title", key)
            status_raw = ws.get("status", "planned")
            status = STATUS_MAP.get(status_raw, "in-progress")
            priority = ws.get("priority", "medium")
            if priority not in ("critical", "high", "medium", "low"):
                priority = "medium"
            summary = ws.get("summary", "")

            existing = conn.execute("SELECT id FROM workstreams WHERE id=?", (wid,)).fetchone()
            if existing:
                conn.execute(
                    "UPDATE workstreams SET title_en=?, status=?, priority=?, summary_en=?, updated_at=? WHERE id=?",
                    (title, status, priority, summary, now_iso(), wid)
                )
            else:
                conn.execute(
                    "INSERT INTO workstreams (id, project_id, title_en, owner, priority, status, summary_en) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (wid, project_id, title, "", priority, status, summary)
                )

            for i, pending in enumerate(ws.get("pending", [])):
                tid = f"{wid}-t{i}"
                task_status = "done" if pending.startswith("✅") else "todo"
                existing_task = conn.execute("SELECT id FROM tasks WHERE id=?", (tid,)).fetchone()
                if not existing_task:
                    conn.execute(
                        "INSERT INTO tasks (id, workstream_id, title_en, status, sort_order) VALUES (?, ?, ?, ?, ?)",
                        (tid, wid, pending, task_status, i)
                    )

            for i, blocker in enumerate(ws.get("blockers", [])):
                bid = f"{wid}-b{i}"
                existing_b = conn.execute("SELECT id FROM blockers WHERE id=?", (bid,)).fetchone()
                if not existing_b:
                    conn.execute(
                        "INSERT INTO blockers (id, workstream_id, description_en) VALUES (?, ?, ?)",
                        (bid, wid, blocker)
                    )

            imported += 1

        log_activity(conn, "project", project_id, "imported",
                     detail=f"Imported {imported} workstreams from session-status.json")

    return {"ok": True, "imported": imported}

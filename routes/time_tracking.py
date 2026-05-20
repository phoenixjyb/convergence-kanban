"""Time tracking routes."""

import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import TZ, get_actor, log_activity, now_iso
from models import TimeEntryCreate

router = APIRouter(prefix="/api", tags=["time_tracking"])


@router.get("/tasks/{tid}/time")
def get_time_entries(tid: str):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM time_entries WHERE task_id=? ORDER BY date DESC, created_at DESC",
                            (tid,)).fetchall()
        return [dict(r) for r in rows]


@router.post("/tasks/{tid}/time")
def log_time(tid: str, entry: TimeEntryCreate, request: Request):
    actor = get_actor(request)
    eid = uuid.uuid4().hex[:12]
    date = entry.date or datetime.now(TZ).strftime("%Y-%m-%d")
    with get_db() as conn:
        if not conn.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (tid,)).fetchone():
            raise HTTPException(404, "Task not found")
        conn.execute("INSERT INTO time_entries (id, task_id, user_name, minutes, description, date) VALUES (?,?,?,?,?,?)",
                     (eid, tid, actor, entry.minutes, entry.description, date))
        log_activity(conn, "task", tid, "time_logged", actor=actor,
                     detail=f"{entry.minutes}min: {entry.description}")
    return {"id": eid}


@router.delete("/time-entries/{eid}")
def delete_time_entry(eid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute("DELETE FROM time_entries WHERE id=?", (eid,))
        if cur.rowcount == 0:
            raise HTTPException(404, "Time entry not found")
        log_activity(conn, "time_entry", eid, "deleted", actor=actor)
    return {"ok": True}


@router.get("/time-report")
def time_report(project_id: Optional[str] = None, workstream_id: Optional[str] = None,
                user_name: Optional[str] = None, date_from: Optional[str] = None,
                date_to: Optional[str] = None):
    with get_db() as conn:
        query = ("SELECT te.*, t.title_en as task_title, t.workstream_id, w.title_en as ws_title, w.project_id "
                 "FROM time_entries te JOIN tasks t ON t.id=te.task_id "
                 "JOIN workstreams w ON w.id=t.workstream_id WHERE 1=1")
        params = []
        if project_id:
            query += " AND w.project_id=?"
            params.append(project_id)
        if workstream_id:
            query += " AND t.workstream_id=?"
            params.append(workstream_id)
        if user_name:
            query += " AND te.user_name=?"
            params.append(user_name)
        if date_from:
            query += " AND te.date>=?"
            params.append(date_from)
        if date_to:
            query += " AND te.date<=?"
            params.append(date_to)
        query += " ORDER BY te.date DESC, te.created_at DESC"
        rows = conn.execute(query, params).fetchall()
        entries = [dict(r) for r in rows]
        total_minutes = sum(r["minutes"] for r in entries)
        by_user = {}
        for r in entries:
            by_user[r["user_name"]] = by_user.get(r["user_name"], 0) + r["minutes"]
        return {"entries": entries, "total_minutes": total_minutes, "by_user": by_user}

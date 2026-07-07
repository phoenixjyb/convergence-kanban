"""Recurring task routes."""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import TZ, get_actor, log_activity, now_iso
from models import RecurringTaskCreate, RecurringTaskUpdate

router = APIRouter(prefix="/api", tags=["recurring"])


def _compute_next_due(schedule, day_of_week=None, day_of_month=None):
    """Compute the next due date based on schedule."""
    today = datetime.now(TZ).date()
    if schedule == "daily":
        return (today + timedelta(days=1)).isoformat()
    elif schedule == "weekly":
        dow = day_of_week if day_of_week is not None else today.weekday()
        days_ahead = dow - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        return (today + timedelta(days=days_ahead)).isoformat()
    elif schedule == "biweekly":
        dow = day_of_week if day_of_week is not None else today.weekday()
        days_ahead = dow - today.weekday()
        if days_ahead <= 0:
            days_ahead += 14
        return (today + timedelta(days=days_ahead)).isoformat()
    elif schedule == "monthly":
        dom = day_of_month if day_of_month is not None else today.day
        year, month = today.year, today.month
        if today.day >= dom:
            month += 1
            if month > 12:
                month = 1
                year += 1
        dom = min(dom, 28)
        return f"{year:04d}-{month:02d}-{dom:02d}"
    return today.isoformat()


def check_recurring_tasks():
    """Check all active recurring tasks and create instances as needed. Returns list of created task IDs."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    today_date = datetime.now(TZ).date()
    created = []
    with get_db() as conn:
        recs = conn.execute(
            "SELECT * FROM recurring_tasks WHERE active=1 AND deleted_at IS NULL"
        ).fetchall()
        for r in recs:
            if r["last_created"] == today:
                continue
            should = False
            if r["schedule"] == "daily":
                should = True
            elif r["schedule"] == "weekly":
                should = (r["day_of_week"] is None or today_date.weekday() == r["day_of_week"])
            elif r["schedule"] == "biweekly":
                should = (r["day_of_week"] is None or today_date.weekday() == r["day_of_week"]) and (today_date.isocalendar()[1] % 2 == 0)
            elif r["schedule"] == "monthly":
                should = (r["day_of_month"] is None or today_date.day == r["day_of_month"])
            if not should:
                continue
            tid = uuid.uuid4().hex[:12]
            next_due = _compute_next_due(r["schedule"], r["day_of_week"], r["day_of_month"])
            conn.execute(
                "INSERT INTO tasks (id, workstream_id, title_en, title_zh, assignee, status, "
                "start_date, notes, sort_order, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (tid, r["workstream_id"], r["title_en"], r["title_zh"], r["assignee"], "todo",
                 today, r["notes"], 0, now_iso(), now_iso()))
            conn.execute("UPDATE recurring_tasks SET last_created=?, next_due=?, updated_at=? WHERE id=?",
                         (today, next_due, now_iso(), r["id"]))
            log_activity(conn, "task", tid, "auto_created", actor="system",
                         detail=f"Recurring: {r['title_en']}")
            created.append(tid)
    return created


@router.get("/recurring-tasks")
def list_recurring(workstream_id: Optional[str] = None):
    with get_db() as conn:
        if workstream_id:
            rows = conn.execute("SELECT * FROM recurring_tasks WHERE workstream_id=? AND deleted_at IS NULL ORDER BY created_at",
                                (workstream_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM recurring_tasks WHERE deleted_at IS NULL ORDER BY created_at").fetchall()
        return [dict(r) for r in rows]


@router.post("/recurring-tasks")
def create_recurring(rt: RecurringTaskCreate, request: Request):
    actor = get_actor(request)
    rid = uuid.uuid4().hex[:12]
    with get_db() as conn:
        if not conn.execute("SELECT id FROM workstreams WHERE id=? AND deleted_at IS NULL",
                            (rt.workstream_id,)).fetchone():
            raise HTTPException(404, "Workstream not found")
        next_due = _compute_next_due(rt.schedule, rt.day_of_week, rt.day_of_month)
        conn.execute(
            "INSERT INTO recurring_tasks (id, workstream_id, title_en, title_zh, assignee, notes, "
            "schedule, day_of_week, day_of_month, next_due) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (rid, rt.workstream_id, rt.title_en, rt.title_zh, rt.assignee, rt.notes,
             rt.schedule, rt.day_of_week, rt.day_of_month, next_due))
        log_activity(conn, "recurring_task", rid, "created", actor=actor, detail=rt.title_en)
    return {"id": rid}


@router.put("/recurring-tasks/{rid}")
def update_recurring(rid: str, rt: RecurringTaskUpdate, request: Request):
    fields, vals = [], []
    for k, v in rt.model_dump(exclude_none=True).items():
        fields.append(f"{k}=?")
        vals.append(v)
    if not fields:
        raise HTTPException(400, "No fields to update")
    fields.append("updated_at=?")
    vals.append(now_iso())
    vals.append(rid)
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute(f"UPDATE recurring_tasks SET {', '.join(fields)} WHERE id=? AND deleted_at IS NULL", vals)
        if cur.rowcount == 0:
            raise HTTPException(404, "Recurring task not found")
        log_activity(conn, "recurring_task", rid, "updated", actor=actor)
    return {"ok": True}


@router.delete("/recurring-tasks/{rid}")
def delete_recurring(rid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute("UPDATE recurring_tasks SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (now_iso(), rid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Recurring task not found")
        log_activity(conn, "recurring_task", rid, "deleted", actor=actor)
    return {"ok": True}


@router.post("/recurring-tasks/check")
def trigger_recurring_check(request: Request):
    created = check_recurring_tasks()
    return {"ok": True, "created": created}

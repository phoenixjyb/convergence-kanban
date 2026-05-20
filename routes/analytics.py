"""Analytics snapshot and query routes."""

import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Request

from db import get_db
from helpers import TZ, build_person_map, get_actor, log_activity, normalize_assignee, now_iso

router = APIRouter(prefix="/api", tags=["analytics"])


@router.post("/analytics/snapshot")
def capture_snapshot(request: Request):
    """Capture a daily snapshot of task counts per project. Idempotent per day."""
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    actor = get_actor(request)
    with get_db() as conn:
        existing = conn.execute("SELECT id FROM snapshots WHERE date=?", (today,)).fetchone()
        projects = conn.execute("SELECT id, name_en FROM projects WHERE deleted_at IS NULL").fetchall()
        person_map = build_person_map(conn)
        snapshot_data = {"projects": {}, "totals": {}}
        total_todo = total_doing = total_in_review = total_done = total_blocked = total_abandoned = total_blockers = 0
        for p in projects:
            pid = p["id"]
            tasks = conn.execute(
                "SELECT t.status, count(*) c FROM tasks t "
                "JOIN workstreams w ON t.workstream_id=w.id "
                "WHERE w.project_id=? AND t.deleted_at IS NULL AND t.parent_task_id IS NULL "
                "GROUP BY t.status", (pid,)).fetchall()
            counts = {r["status"]: r["c"] for r in tasks}
            blockers = conn.execute(
                "SELECT count(*) c FROM blockers b "
                "JOIN workstreams w ON b.workstream_id=w.id "
                "WHERE w.project_id=? AND b.resolved=0 AND b.deleted_at IS NULL", (pid,)).fetchone()
            # Bug counts by status for this project
            bug_rows = conn.execute(
                "SELECT status, count(*) c FROM bugs "
                "WHERE project_id=? AND deleted_at IS NULL GROUP BY status", (pid,)
            ).fetchall()
            bug_counts = {r["status"]: r["c"] for r in bug_rows}
            # Per-assignee task counts
            assignee_rows = conn.execute(
                "SELECT t.assignee, count(*) c FROM tasks t "
                "JOIN workstreams w ON t.workstream_id=w.id "
                "WHERE w.project_id=? AND t.deleted_at IS NULL AND t.parent_task_id IS NULL "
                "GROUP BY t.assignee", (pid,)
            ).fetchall()
            assignee_counts: dict = {}
            for r in assignee_rows:
                canon = normalize_assignee(r["assignee"], person_map)
                assignee_counts[canon] = assignee_counts.get(canon, 0) + r["c"]
            proj_data = {
                "name": p["name_en"],
                "todo": counts.get("todo", 0), "doing": counts.get("doing", 0),
                "in_review": counts.get("in_review", 0),
                "done": counts.get("done", 0), "blocked": counts.get("blocked", 0),
                "abandoned": counts.get("abandoned", 0),
                "active_blockers": blockers["c"],
                "bugs": bug_counts,
                "assignees": assignee_counts,
            }
            snapshot_data["projects"][pid] = proj_data
            total_todo += proj_data["todo"]
            total_doing += proj_data["doing"]
            total_in_review += proj_data["in_review"]
            total_done += proj_data["done"]
            total_blocked += proj_data["blocked"]
            total_abandoned += proj_data["abandoned"]
            total_blockers += proj_data["active_blockers"]
        snapshot_data["totals"] = {
            "todo": total_todo, "doing": total_doing, "in_review": total_in_review, "done": total_done,
            "blocked": total_blocked, "abandoned": total_abandoned,
            "total": total_todo + total_doing + total_in_review + total_done + total_blocked + total_abandoned,
            "active_blockers": total_blockers,
        }
        if existing:
            conn.execute("UPDATE snapshots SET data=?, created_at=? WHERE date=?",
                         (json.dumps(snapshot_data), now_iso(), today))
        else:
            sid = uuid.uuid4().hex[:12]
            conn.execute("INSERT INTO snapshots (id, date, data, created_at) VALUES (?, ?, ?, ?)",
                         (sid, today, json.dumps(snapshot_data), now_iso()))
        log_activity(conn, "analytics", "snapshot", "captured", actor=actor, detail=today)
        return {"ok": True, "date": today}


@router.get("/analytics")
def get_analytics(days: int = Query(default=30, ge=1, le=365)):
    """Return time-series snapshot data for the last N days."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT date, data FROM snapshots ORDER BY date DESC LIMIT ?", (days,)).fetchall()
        result = [{"date": r["date"], **json.loads(r["data"])} for r in rows]
        result.reverse()
        return result


@router.get("/analytics/bugs")
def get_bug_analytics(days: int = Query(default=30, ge=1, le=365)):
    """Bug open/close counts per day for the last N days."""
    cutoff = (datetime.now(TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    with get_db() as conn:
        opened = conn.execute(
            "SELECT DATE(created_at) AS day, COUNT(*) AS count "
            "FROM bugs WHERE DATE(created_at) >= ? AND deleted_at IS NULL "
            "GROUP BY DATE(created_at) ORDER BY day", (cutoff,)
        ).fetchall()
        closed = conn.execute(
            "SELECT DATE(updated_at) AS day, COUNT(*) AS count "
            "FROM bugs WHERE DATE(updated_at) >= ? AND deleted_at IS NULL "
            "AND status IN ('resolved', 'closed', 'wontfix') "
            "GROUP BY DATE(updated_at) ORDER BY day", (cutoff,)
        ).fetchall()
        return {
            "opened": [{"date": r["day"], "count": r["count"]} for r in opened],
            "closed": [{"date": r["day"], "count": r["count"]} for r in closed],
        }


@router.get("/analytics/workload")
def get_workload():
    """Per-assignee task distribution by status, with person grouping."""
    with get_db() as conn:
        person_map = build_person_map(conn)
        rows = conn.execute(
            "SELECT assignee, status, COUNT(*) AS count FROM tasks "
            "WHERE deleted_at IS NULL AND parent_task_id IS NULL "
            "GROUP BY assignee, status"
        ).fetchall()
        assignees: dict = {}
        for r in rows:
            name = normalize_assignee(r["assignee"], person_map)
            if name not in assignees:
                assignees[name] = {"assignee": name, "todo": 0, "doing": 0,
                                   "in_review": 0, "done": 0, "blocked": 0, "abandoned": 0, "total": 0}
            entry = assignees[name]
            status = r["status"]
            if status in entry:
                entry[status] += r["count"]
            entry["total"] += r["count"]
        return list(assignees.values())


@router.get("/analytics/blockers")
def get_blocker_aging():
    """Unresolved blocker aging information."""
    now = datetime.now(TZ)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT b.id, b.description_en, b.created_at, "
            "p.name_en AS project, w.title_en AS workstream "
            "FROM blockers b "
            "JOIN workstreams w ON b.workstream_id = w.id "
            "JOIN projects p ON w.project_id = p.id "
            "WHERE b.resolved = 0 AND b.deleted_at IS NULL "
            "ORDER BY b.created_at ASC"
        ).fetchall()
        result = []
        for r in rows:
            created = datetime.fromisoformat(r["created_at"])
            if created.tzinfo is None:
                created = created.replace(tzinfo=TZ)
            age_hours = round((now - created).total_seconds() / 3600, 1)
            result.append({
                "id": r["id"],
                "description_en": r["description_en"],
                "project": r["project"],
                "workstream": r["workstream"],
                "age_hours": age_hours,
                "created_at": r["created_at"],
            })
        return result


@router.get("/analytics/activity")
def get_activity_log(
    limit: int = Query(default=200, ge=1, le=1000),
    entity_type: str = Query(default=""),
    actor: str = Query(default=""),
):
    """Paginated activity log with optional filters."""
    with get_db() as conn:
        query = "SELECT id, entity_type, entity_id, action, actor, detail, created_at FROM activity_log"
        conditions = []
        params: list = []
        if entity_type:
            conditions.append("entity_type = ?")
            params.append(entity_type)
        if actor:
            conditions.append("actor = ?")
            params.append(actor)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

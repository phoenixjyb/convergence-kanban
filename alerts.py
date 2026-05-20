"""Alert detection engine — pure functions, no web framework dependency.

Detects overdue tasks, stale tasks, and aging blockers.
Used by routes/alerts.py (API) and alert_runner.py (cron).
"""

import sqlite3
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def _today() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _now() -> datetime:
    return datetime.now(TZ)


def find_overdue_tasks(conn: sqlite3.Connection) -> list[dict]:
    """Tasks with due_date in the past that are not done/blocked/deleted."""
    today = _today()
    rows = conn.execute(
        "SELECT t.id, t.title_en, t.title_zh, t.assignee, t.status, t.due_date, "
        "t.start_date, w.title_en as workstream, p.name_en as project "
        "FROM tasks t "
        "JOIN workstreams w ON t.workstream_id = w.id "
        "JOIN projects p ON w.project_id = p.id "
        "WHERE t.due_date < ? AND t.status NOT IN ('done', 'blocked', 'abandoned') "
        "AND t.deleted_at IS NULL AND w.deleted_at IS NULL AND p.deleted_at IS NULL "
        "ORDER BY t.due_date ASC",
        (today,)
    ).fetchall()
    result = []
    for r in rows:
        days = (_now().date() - datetime.strptime(r["due_date"], "%Y-%m-%d").date()).days
        result.append({**dict(r), "days_overdue": days, "alert_type": "overdue"})
    return result


def find_stale_tasks(conn: sqlite3.Connection, days: int = 3) -> list[dict]:
    """Tasks in 'doing' with no activity_log entry for N days."""
    cutoff = (_now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT t.id, t.title_en, t.title_zh, t.assignee, t.status, "
        "t.start_date, t.due_date, "
        "w.title_en as workstream, p.name_en as project, "
        "MAX(a.created_at) as last_activity "
        "FROM tasks t "
        "JOIN workstreams w ON t.workstream_id = w.id "
        "JOIN projects p ON w.project_id = p.id "
        "LEFT JOIN activity_log a ON a.entity_type = 'task' AND a.entity_id = t.id "
        "WHERE t.status = 'doing' "
        "AND t.deleted_at IS NULL AND w.deleted_at IS NULL AND p.deleted_at IS NULL "
        "GROUP BY t.id "
        "HAVING last_activity IS NULL OR last_activity < ? "
        "ORDER BY last_activity ASC",
        (cutoff,)
    ).fetchall()
    result = []
    for r in rows:
        last = r["last_activity"]
        if last:
            stale_days = (_now() - datetime.strptime(last, "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=TZ)).days
        else:
            stale_days = days + 1
        result.append({**dict(r), "stale_days": stale_days, "alert_type": "stale"})
    return result


def find_aging_blockers(conn: sqlite3.Connection, hours: int = 48) -> list[dict]:
    """Unresolved blockers older than N hours."""
    cutoff = (_now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute(
        "SELECT b.id, b.description_en, b.description_zh, b.created_at, "
        "w.title_en as workstream, p.name_en as project "
        "FROM blockers b "
        "JOIN workstreams w ON b.workstream_id = w.id "
        "JOIN projects p ON w.project_id = p.id "
        "WHERE b.resolved = 0 AND b.created_at < ? "
        "AND b.deleted_at IS NULL AND w.deleted_at IS NULL AND p.deleted_at IS NULL "
        "ORDER BY b.created_at ASC",
        (cutoff,)
    ).fetchall()
    result = []
    for r in rows:
        created = datetime.strptime(r["created_at"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        age_hours = int((_now() - created).total_seconds() / 3600)
        result.append({**dict(r), "age_hours": age_hours, "alert_type": "aging_blocker"})
    return result


def get_alert_summary(conn: sqlite3.Connection, stale_days: int = 3,
                      blocker_hours: int = 48) -> dict:
    """Compact counts for badge display."""
    overdue = find_overdue_tasks(conn)
    stale = find_stale_tasks(conn, stale_days)
    aging = find_aging_blockers(conn, blocker_hours)
    return {
        "overdue": len(overdue),
        "stale": len(stale),
        "aging_blockers": len(aging),
        "total": len(overdue) + len(stale) + len(aging),
    }

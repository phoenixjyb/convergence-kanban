"""Alert detection API routes."""

from typing import Optional

from fastapi import APIRouter

from db import get_db
from alerts import find_overdue_tasks, find_stale_tasks, find_aging_blockers, get_alert_summary

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts")
def list_alerts(stale_days: int = 3, blocker_hours: int = 48,
                assignee: Optional[str] = None):
    """Return all active alerts: overdue tasks, stale tasks, aging blockers."""
    with get_db() as conn:
        overdue = find_overdue_tasks(conn)
        stale = find_stale_tasks(conn, stale_days)
        aging = find_aging_blockers(conn, blocker_hours)

        if assignee:
            overdue = [a for a in overdue if a.get("assignee") == assignee]
            stale = [a for a in stale if a.get("assignee") == assignee]

        return {
            "overdue": overdue,
            "stale": stale,
            "aging_blockers": aging,
            "total": len(overdue) + len(stale) + len(aging),
        }


@router.get("/alerts/summary")
def alert_summary(stale_days: int = 3, blocker_hours: int = 48):
    """Compact alert counts for badge display."""
    with get_db() as conn:
        return get_alert_summary(conn, stale_days, blocker_hours)

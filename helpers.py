"""Shared helper functions used across route modules."""

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from db import get_db

# Project-wide timezone: Asia/Shanghai (UTC+8)
TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def generate_bug_display_id(conn: sqlite3.Connection, source: str = "manual") -> str:
    """Generate a human-readable bug ID: BUG-YYMMDD-NNN or RD-YYMMDD-NNN.

    NNN resets daily per prefix. Uses the bugs table to find the max counter
    for today's date and increments.

    Note: prior to 2026-05-09 the format was MMDD (4 digits). Existing IDs
    in that older format are left in place; new IDs use YYMMDD (6 digits).
    """
    prefix = "RD" if source == "agent" else "BUG"
    today = datetime.now(TZ)
    yymmdd = today.strftime("%y%m%d")
    pattern = f"{prefix}-{yymmdd}-%"
    row = conn.execute(
        "SELECT display_id FROM bugs WHERE display_id LIKE ? ORDER BY display_id DESC LIMIT 1",
        (pattern,)
    ).fetchone()
    if row and row["display_id"]:
        # Extract NNN from the last display_id
        try:
            last_num = int(row["display_id"].rsplit("-", 1)[1])
        except (ValueError, IndexError):
            last_num = 0
        next_num = last_num + 1
    else:
        next_num = 1
    return f"{prefix}-{yymmdd}-{next_num:03d}"


def get_actor(request: Request) -> str:
    """Extract actor name from X-Kanban-User header, default to 'system'."""
    return request.headers.get("X-Kanban-User", "system")


def _is_bot(conn: sqlite3.Connection, actor: str) -> bool:
    """Check if actor is a bot user.
    Unknown actors (not in users table) are treated as bots unless they are
    the default 'system' actor (web UI). This prevents unregistered actors
    from bypassing bot governance."""
    if actor == "system":
        return False  # web UI default — trusted
    row = conn.execute("SELECT role FROM users WHERE name=? COLLATE NOCASE", (actor,)).fetchone()
    if not row:
        return True  # unknown actor — restricted like a bot
    return row["role"] == "bot"


def _require_human(conn: sqlite3.Connection, actor: str, action: str,
                    entity_type: str = "", entity_id: str = ""):
    """Raise 403 if actor is a bot. Logs rejected action before raising.

    Optional entity_type/entity_id give context about what the bot tried to
    touch (e.g. entity_type="project", entity_id=pid).  When omitted, the
    log still records the action description under 'governance'.
    """
    if _is_bot(conn, actor):
        log_entity = entity_type or "governance"
        log_id = entity_id or "rejected"
        detail = f"Bot attempted to {action}"
        log_activity(conn, log_entity, log_id, "rejected", actor=actor, detail=detail)
        conn.commit()
        raise HTTPException(403, f"Bot users cannot {action}. Request human approval.")


def _notify_context(conn: sqlite3.Connection, workstream_id: str) -> tuple:
    """Return (project_name, workstream_title) for notification context."""
    ws = conn.execute("SELECT project_id, title_en FROM workstreams WHERE id=?", (workstream_id,)).fetchone()
    if not ws:
        return ("", "")
    p = conn.execute("SELECT name_en FROM projects WHERE id=?", (ws["project_id"],)).fetchone()
    return (p["name_en"] if p else "", ws["title_en"])


def build_person_map(conn: sqlite3.Connection) -> dict:
    """Build a mapping from all known name variants to a canonical person name.

    Groups human users with their bot agents by shared firstname prefix.
    e.g. alice.smith (human) + alice-claude (bot) → both map to 'alice.smith'
    Also stores the firstname→human lookup for resolving ad-hoc names.
    """
    rows = conn.execute("SELECT name, role FROM users").fetchall()
    # Build firstname → human name lookup
    first_to_human = {}
    for r in rows:
        if r["role"] == "human":
            firstname = r["name"].split(".")[0].split("-")[0].lower()
            first_to_human[firstname] = r["name"]
    # Map all user table names to their human counterpart
    person_map = {}
    for r in rows:
        name = r["name"]
        firstname = name.split(".")[0].split("-")[0].lower()
        person_map[name] = first_to_human.get(firstname, name)
    # Stash the firstname lookup for ad-hoc name resolution
    person_map["__first_to_human__"] = first_to_human
    return person_map


def normalize_assignee(name: str, person_map: dict) -> str:
    """Resolve a name to its canonical person using the person map."""
    if not name:
        return "unassigned"
    if name in person_map:
        return person_map[name]
    # Ad-hoc name not in users table — try firstname match
    first_to_human = person_map.get("__first_to_human__", {})
    firstname = name.split(".")[0].split("-")[0].lower()
    canonical = first_to_human.get(firstname)
    if canonical:
        person_map[name] = canonical  # cache for next lookup
        return canonical
    return name


def log_activity(conn: sqlite3.Connection, entity_type: str, entity_id: str,
                 action: str, actor: str = "system", detail: str = ""):
    conn.execute(
        "INSERT INTO activity_log (entity_type, entity_id, actor, action, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (entity_type, entity_id, actor, action, detail, now_iso())
    )


# ── Login-required middleware ────────────────────────────────────────────

# Paths that skip the login check (read-only, auth, or automated endpoints)
_LOGIN_EXEMPT = {
    "/api/auth/login", "/api/auth/token", "/api/health",
    "/api/users",  # user creation (for first-time setup)
    "/api/analytics/snapshot",  # automated cron job
    "/api/import/session-status",  # automated session import
    "/api/recurring-tasks/check",  # called by feishu_sync each cycle
}


class RequireLoginMiddleware(BaseHTTPMiddleware):
    """Block mutation requests (POST/PUT/DELETE) unless X-Kanban-User
    identifies a known user in the database.  GET requests pass through."""

    async def dispatch(self, request, call_next):
        if request.method in ("POST", "PUT", "DELETE"):
            path = request.url.path
            # Allow exempt paths
            if path not in _LOGIN_EXEMPT:
                actor = request.headers.get("X-Kanban-User", "")
                if not actor or actor == "system":
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Login required. Please log in via Feishu bot or user picker."},
                    )
                # Verify user exists in DB
                with get_db() as conn:
                    row = conn.execute(
                        "SELECT id FROM users WHERE name=? COLLATE NOCASE", (actor,)
                    ).fetchone()
                if not row:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": f"Unknown user '{actor}'. Please log in with a valid account."},
                    )
        return await call_next(request)

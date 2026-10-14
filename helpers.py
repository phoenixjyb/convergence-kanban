"""Shared helper functions used across route modules."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from db import get_db

# Project-wide timezone: Asia/Shanghai (UTC+8)
TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def issue_to_dict(row) -> dict:
    result = dict(row)
    for field in ("task_ids", "bug_ids"):
        result[field] = json.loads(result[field])
    return result


def generate_issue_display_id(conn) -> str:
    # Reserve the SQLite write lock before reading the counter, including
    # concurrent API submissions and Feishu imports.
    conn.execute("UPDATE issues SET rank=rank WHERE 0")
    prefix = f"ISS-{datetime.now(TZ):%y%m%d}-"
    ids = conn.execute("SELECT display_id FROM issues WHERE display_id LIKE ?", (prefix + "%",)).fetchall()
    counter = max((int(r["display_id"].rsplit("-", 1)[1]) for r in ids), default=0) + 1
    return f"{prefix}{counter:03d}"


def validate_issue_values(conn, values, previous=None):
    """Validate issue content, closure evidence, and references for API/sync."""
    if not values["title"].strip() or not values["content"].strip():
        raise HTTPException(400, "Issue title and content must not be blank")
    if values["status"] == "closed" and (
        not values["resolution_criteria"].strip() or not values["resolution"].strip()
    ):
        raise HTTPException(400, "Closing an issue requires resolution criteria and an outcome")
    for field, table in (("project_id", "projects"), ("workstream_id", "workstreams")):
        if previous and previous.get(field) == values.get(field):
            continue
        if values.get(field) and not conn.execute(
            f"SELECT id FROM {table} WHERE id=? AND deleted_at IS NULL", (values[field],)
        ).fetchone():
            raise HTTPException(400, f"Unknown or deleted {field}")
    if values.get("project_id") and values.get("workstream_id"):
        ws = conn.execute("SELECT project_id FROM workstreams WHERE id=?", (values["workstream_id"],)).fetchone()
        if ws["project_id"] != values["project_id"]:
            raise HTTPException(400, "Workstream does not belong to the selected project")
    for field, table in (("task_ids", "tasks"), ("bug_ids", "bugs")):
        for target in values[field]:
            if previous and target in previous.get(field, []):
                continue
            if not conn.execute(f"SELECT id FROM {table} WHERE id=? AND deleted_at IS NULL", (target,)).fetchone():
                raise HTTPException(400, f"Unknown or deleted reference in {field}: {target}")


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


def apply_issue_conflict(conn, conflict, value, actor):
    apply_issue_conflicts(conn, [(conflict, value)], actor)


def apply_issue_conflicts(conn, choices, actor):
    from models import IssueUpdate
    from pydantic import ValidationError

    iid = choices[0][0]["entity_id"]
    row = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
    if not row:
        raise HTTPException(404, "Issue not found")
    changes = {}
    archive = None
    for conflict, value in choices:
        field = conflict["field_name"]
        if field == "deleted_at":
            _require_human(conn, actor, "archive or restore issues", "issue", iid)
            archive = {"deleted_at": now_iso() if value else None}
            continue
        if field not in IssueUpdate.model_fields:
            raise HTTPException(400, "Unsupported issue conflict field")
        parsed = value
        if field in ("task_ids", "bug_ids"):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                raise HTTPException(400, "Invalid issue link JSON")
        if field in ("project_id", "workstream_id", "due_date"):
            parsed = value or None
        changes[field] = parsed
    try:
        updates = IssueUpdate.model_validate(changes).model_dump(mode="json", exclude_unset=True)
    except ValidationError:
        raise HTTPException(400, "Invalid issue conflict value")
    if updates.get("status") == "closed":
        _require_human(conn, actor, "close issues", "issue", iid)
    validate_issue_values(conn, issue_to_dict(row) | updates, previous=issue_to_dict(row))
    for field in ("task_ids", "bug_ids"):
        if field in updates:
            updates[field] = json.dumps(sorted(set(updates[field])))
    updates.update(archive or {})
    updates["updated_at"] = now_iso()
    conn.execute(f"UPDATE issues SET {','.join(k+'=?' for k in updates)} WHERE id=?", [*updates.values(), iid])
    for conflict, value in choices:
        if conflict["field_name"] in ("task_ids", "bug_ids"):
            value = json.dumps(sorted(set(json.loads(value))))
        conn.execute("UPDATE sync_conflicts SET local_value=? WHERE id=?", (str(value or ""), conflict["id"]))


def apply_bug_conflicts(conn, choices, actor):
    """Validate and apply Feishu bug conflict choices as one entity update."""
    from models import BugCreate
    from pydantic import ValidationError

    if not choices:
        return
    bug_id = choices[0][0]["entity_id"]
    _require_human(conn, actor, "resolve bug sync conflicts", "bug", bug_id)
    row = conn.execute(
        "SELECT * FROM bugs WHERE id=? AND deleted_at IS NULL", (bug_id,)
    ).fetchone()
    if not row:
        raise HTTPException(404, "Bug not found or deleted")

    allowed_fields = {
        "title", "status", "assignee", "severity", "reporter", "environment",
        "steps", "feature", "repro_rate", "issue_time", "issue_version",
        "device_id", "issue_images", "fix_method", "fix_version", "fix_date",
        "task_ids",
    }
    columns = {"steps": "steps_to_reproduce"}
    current = dict(row)
    try:
        stored_images = current.get("issue_images")
        current["issue_images"] = json.loads(stored_images) if stored_images else []
        if not isinstance(current["issue_images"], list):
            raise ValueError("issue_images must be a JSON list")

        changes = {}
        resolved_values = []
        task_ids_choice = None
        for conflict, value in choices:
            field = conflict["field_name"]
            if field not in allowed_fields:
                raise HTTPException(400, "Unsupported bug conflict field")
            parsed = value
            if field == "issue_images":
                parsed = json.loads(value) if value else []
                if not isinstance(parsed, list):
                    raise ValueError("issue_images must be a JSON list")
                remote_value = conflict["remote_value"]
                remote_images = json.loads(remote_value) if remote_value else []
                if not isinstance(remote_images, list):
                    raise ValueError("remote issue_images must be a JSON list")
                if parsed != remote_images:
                    raise HTTPException(
                        400,
                        "Issue image choices must match the remote Feishu value",
                    )
            if field == "task_ids":
                parsed = json.loads(value) if value else []
                if (not isinstance(parsed, list) or
                        any(not isinstance(task_id, str) or not task_id for task_id in parsed) or
                        len(parsed) != len(set(parsed))):
                    raise ValueError("task_ids must be a unique JSON array of task IDs")
                for task_id in parsed:
                    if not conn.execute(
                        "SELECT id FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,)
                    ).fetchone():
                        raise HTTPException(400, f"Unknown or deleted task in task_ids: {task_id}")
                parsed = sorted(parsed)
                task_ids_choice = parsed
            model_field = columns.get(field, field)
            if field != "task_ids":
                changes[model_field] = parsed
            resolved_values.append((conflict, parsed))

        BugCreate.model_validate(current | changes)
    except HTTPException:
        raise
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(400, "Invalid bug conflict value")

    updates = {columns.get(field, field): value for field, value in changes.items()}
    if "issue_images" in updates:
        updates["issue_images"] = json.dumps(updates["issue_images"]) if updates["issue_images"] else ""
    task_ids = task_ids_choice
    if task_ids is not None:
        conn.execute("DELETE FROM bug_task_links WHERE bug_id=?", (bug_id,))
        conn.executemany(
            "INSERT INTO bug_task_links (bug_id, task_id) VALUES (?, ?)",
            [(bug_id, task_id) for task_id in task_ids],
        )
        updates["task_id"] = task_ids[0] if task_ids else None
    if updates.get("status") in ("resolved", "closed"):
        updates["resolved_at"] = now_iso()
    updates["updated_at"] = now_iso()
    conn.execute(
        f"UPDATE bugs SET {','.join(k+'=?' for k in updates)} WHERE id=? AND deleted_at IS NULL",
        [*updates.values(), bug_id],
    )
    for conflict, value in resolved_values:
        if conflict["field_name"] == "issue_images":
            value = json.dumps(value) if value else ""
        elif conflict["field_name"] == "task_ids":
            value = json.dumps(value)
        conn.execute(
            "UPDATE sync_conflicts SET local_value=? WHERE id=?",
            (str(value or ""), conflict["id"]),
        )


def _sync_text_field(value, english_field, chinese_field):
    """Map Feishu's single text value into the appropriate bilingual column."""
    value = value or ""
    cjk_ranges = (
        (0x2E80, 0x2FFF), (0x3000, 0x30FF), (0x3100, 0x31FF),
        (0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xAC00, 0xD7AF),
        (0xF900, 0xFAFF), (0xFF00, 0xFFEF),
    )
    field = chinese_field if any(
        any(start <= ord(char) <= end for start, end in cjk_ranges) for char in value
    ) else english_field
    return field, value


def _validate_sync_dates(changes):
    for field in ("start_date", "due_date"):
        if field not in changes:
            continue
        value = changes[field]
        if value in (None, ""):
            changes[field] = None
            continue
        try:
            parsed = date.fromisoformat(value)
        except (TypeError, ValueError):
            raise HTTPException(400, f"Invalid {field}; expected an ISO date")
        if parsed.isoformat() != value:
            raise HTTPException(400, f"Invalid {field}; expected an ISO date")


def _task_conflict_updates(conn, choices, actor):
    from models import TaskUpdate
    from pydantic import ValidationError

    task_id = choices[0][0]["entity_id"]
    row = conn.execute("SELECT * FROM tasks WHERE id=? AND deleted_at IS NULL", (task_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Task not found or deleted")
    current = dict(row)
    changes = {}
    for conflict, value in choices:
        field = conflict["field_name"]
        if field not in {"title_en", "status", "assignee", "start_date", "due_date", "notes", "parent_task_id"}:
            raise HTTPException(400, "Unsupported task conflict field")
        if field == "title_en":
            target, value = _sync_text_field(value, "title_en", "title_zh")
            changes[target] = value
            if target == "title_en":
                changes["title_zh"] = ""
        elif field in ("start_date", "due_date"):
            changes[field] = value or None
        elif field == "parent_task_id":
            changes[field] = value or None
        else:
            changes[field] = value
    try:
        _validate_sync_dates(changes)
        updates = TaskUpdate.model_validate(changes).model_dump(exclude_unset=True)
    except HTTPException:
        raise
    except (TypeError, ValueError, ValidationError):
        raise HTTPException(400, "Invalid task conflict value")

    if updates.get("status") in ("done", "abandoned"):
        action = "mark tasks as done — use 'in_review' instead" if updates["status"] == "done" else "mark tasks as abandoned — humans only"
        _require_human(conn, actor, action, "task", task_id)
    if "parent_task_id" in updates and updates["parent_task_id"]:
        parent_id = updates["parent_task_id"]
        parent = conn.execute(
            "SELECT id, workstream_id FROM tasks WHERE id=? AND deleted_at IS NULL", (parent_id,)
        ).fetchone()
        if not parent or parent["workstream_id"] != current["workstream_id"]:
            raise HTTPException(400, "Parent task must be active in the same workstream")
        descendants = conn.execute(
            "WITH RECURSIVE descendants(id) AS ("
            "SELECT id FROM tasks WHERE parent_task_id=? AND deleted_at IS NULL UNION "
            "SELECT t.id FROM tasks t JOIN descendants d ON t.parent_task_id=d.id WHERE t.deleted_at IS NULL) "
            "SELECT id FROM descendants", (task_id,),
        ).fetchall()
        if parent_id == task_id or parent_id in {item["id"] for item in descendants}:
            raise HTTPException(400, "Parent task would create a cycle")
    return task_id, updates, choices


def apply_task_conflict(conn, conflict, value, actor):
    apply_task_conflicts(conn, [(conflict, value)], actor)


def apply_task_conflicts(conn, choices, actor):
    """Validate and apply all selected conflicts for one active task."""
    if not choices:
        return
    task_id, updates, resolved_values = _task_conflict_updates(conn, choices, actor)
    if updates:
        updates["updated_at"] = now_iso()
        conn.execute(
            f"UPDATE tasks SET {','.join(field+'=?' for field in updates)} WHERE id=? AND deleted_at IS NULL",
            [*updates.values(), task_id],
        )
    for conflict, value in resolved_values:
        conn.execute("UPDATE sync_conflicts SET local_value=? WHERE id=?", (str(value or ""), conflict["id"]))


def apply_blocker_conflict(conn, conflict, value):
    apply_blocker_conflicts(conn, [(conflict, value)])


def apply_blocker_conflicts(conn, choices):
    """Validate and apply all selected conflicts for one active blocker."""
    from models import BlockerUpdate
    from pydantic import ValidationError

    if not choices:
        return
    blocker_id = choices[0][0]["entity_id"]
    row = conn.execute("SELECT * FROM blockers WHERE id=? AND deleted_at IS NULL", (blocker_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Blocker not found or deleted")
    changes = {}
    for conflict, value in choices:
        field = conflict["field_name"]
        if field == "status":
            if value not in ("done", "blocked"):
                raise HTTPException(400, "Invalid blocker status")
            changes["resolved"] = value == "done"
        elif field in ("title_en", "description_en"):
            target, value = _sync_text_field(value, "description_en", "description_zh")
            changes[target] = value
            if target == "description_en":
                changes["description_zh"] = ""
        elif field in BlockerUpdate.model_fields:
            changes[field] = value
        else:
            raise HTTPException(400, "Unsupported blocker conflict field")
    try:
        update_fields = {k: v for k, v in changes.items() if k != "resolved"}
        updates = BlockerUpdate.model_validate(update_fields).model_dump(exclude_unset=True)
    except (TypeError, ValueError, ValidationError):
        raise HTTPException(400, "Invalid blocker conflict value")
    updates.update({k: v for k, v in changes.items() if k == "resolved"})
    if "resolved" in updates:
        updates["resolved_at"] = now_iso() if updates["resolved"] else None
    if updates:
        updates["updated_at"] = now_iso()
        conn.execute(
            f"UPDATE blockers SET {','.join(field+'=?' for field in updates)} WHERE id=? AND deleted_at IS NULL",
            [*updates.values(), blocker_id],
        )
    for conflict, value in choices:
        conn.execute("UPDATE sync_conflicts SET local_value=? WHERE id=?", (str(value or ""), conflict["id"]))


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

"""CSV export and import endpoints for tasks and bugs."""

import csv
import io
import uuid
from typing import Optional

from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import StreamingResponse

from db import get_db
from helpers import get_actor, log_activity, now_iso

router = APIRouter(prefix="/api", tags=["export"])


@router.get("/export/tasks")
def export_tasks(project_id: Optional[str] = None, status: Optional[str] = None):
    columns = [
        "id", "title_en", "title_zh", "status", "priority",
        "assignee", "due_date", "workstream_id", "created_at", "updated_at",
    ]
    with get_db() as conn:
        clauses = ["t.deleted_at IS NULL"]
        params: list = []
        if project_id:
            clauses.append("w.project_id=?")
            params.append(project_id)
        if status:
            clauses.append("t.status=?")
            params.append(status)
        q = (
            "SELECT t.* FROM tasks t "
            "LEFT JOIN workstreams w ON t.workstream_id=w.id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY t.created_at"
        )
        rows = conn.execute(q, params).fetchall()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=tasks.csv"},
    )


@router.get("/export/bugs")
def export_bugs(project_id: Optional[str] = None, severity: Optional[str] = None):
    columns = [
        "id", "title", "severity", "status",
        "reporter", "assignee", "created_at", "resolved_at",
    ]
    with get_db() as conn:
        clauses = ["deleted_at IS NULL"]
        params: list = []
        if project_id:
            clauses.append("project_id=?")
            params.append(project_id)
        if severity:
            clauses.append("severity=?")
            params.append(severity)
        q = f"SELECT * FROM bugs WHERE {' AND '.join(clauses)} ORDER BY created_at"
        rows = conn.execute(q, params).fetchall()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(dict(r))

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=bugs.csv"},
    )


# ---------------------------------------------------------------------------
# Import endpoints
# ---------------------------------------------------------------------------

VALID_TASK_STATUSES = {"backlog", "todo", "doing", "in_review", "done"}
VALID_PRIORITIES = {"critical", "high", "medium", "low"}
VALID_BUG_SEVERITIES = {"critical", "high", "medium", "low"}
VALID_BUG_STATUSES = {"open", "investigating", "fixing", "fix_complete", "to_verify", "resolved", "closed", "wontfix"}


@router.post("/import/tasks")
async def import_tasks(request: Request, file: UploadFile = File(...)):
    """Bulk import tasks from a CSV file.

    Required columns: title_en, workstream_id
    Optional columns: title_zh, status, priority, assignee, due_date, notes
    """
    actor = get_actor(request)
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    imported = 0
    skipped = 0
    errors: list[str] = []

    with get_db() as conn:
        # Pre-fetch valid workstream IDs
        ws_rows = conn.execute(
            "SELECT id FROM workstreams WHERE deleted_at IS NULL"
        ).fetchall()
        valid_ws = {r["id"] for r in ws_rows}

        for i, row in enumerate(reader, start=2):  # row 1 is header
            title_en = (row.get("title_en") or "").strip()
            workstream_id = (row.get("workstream_id") or "").strip()

            if not title_en or not workstream_id:
                skipped += 1
                errors.append(f"Row {i}: missing required field (title_en or workstream_id)")
                continue

            if workstream_id not in valid_ws:
                skipped += 1
                errors.append(f"Row {i}: workstream_id '{workstream_id}' not found")
                continue

            status = (row.get("status") or "todo").strip()
            if status not in VALID_TASK_STATUSES:
                status = "todo"

            priority = (row.get("priority") or "medium").strip()
            if priority not in VALID_PRIORITIES:
                priority = "medium"

            tid = uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO tasks (id, workstream_id, title_en, title_zh, assignee, "
                "status, priority, due_date, notes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    tid,
                    workstream_id,
                    title_en,
                    (row.get("title_zh") or "").strip(),
                    (row.get("assignee") or "").strip(),
                    status,
                    priority,
                    (row.get("due_date") or "").strip() or None,
                    (row.get("notes") or "").strip(),
                ),
            )
            log_activity(conn, "task", tid, "imported", actor=actor, detail=title_en)
            imported += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}


@router.post("/import/bugs")
async def import_bugs(request: Request, file: UploadFile = File(...)):
    """Bulk import bugs from a CSV file.

    Required columns: title, severity, project_id
    Optional columns: description, reporter, assignee, status
    """
    actor = get_actor(request)
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))

    imported = 0
    skipped = 0
    errors: list[str] = []

    with get_db() as conn:
        # Pre-fetch valid project IDs
        proj_rows = conn.execute(
            "SELECT id FROM projects WHERE deleted_at IS NULL"
        ).fetchall()
        valid_projects = {r["id"] for r in proj_rows}

        for i, row in enumerate(reader, start=2):
            title = (row.get("title") or "").strip()
            severity = (row.get("severity") or "").strip()
            project_id = (row.get("project_id") or "").strip()

            if not title or not project_id:
                skipped += 1
                errors.append(f"Row {i}: missing required field (title or project_id)")
                continue

            if project_id not in valid_projects:
                skipped += 1
                errors.append(f"Row {i}: project_id '{project_id}' not found")
                continue

            if severity not in VALID_BUG_SEVERITIES:
                severity = "medium"

            status = (row.get("status") or "open").strip()
            if status not in VALID_BUG_STATUSES:
                status = "open"

            bid = uuid.uuid4().hex[:12]
            conn.execute(
                "INSERT INTO bugs (id, title, description, severity, status, "
                "reporter, assignee, project_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    bid,
                    title,
                    (row.get("description") or "").strip(),
                    severity,
                    status,
                    (row.get("reporter") or actor).strip(),
                    (row.get("assignee") or "").strip(),
                    project_id,
                    now_iso(),
                ),
            )
            log_activity(conn, "bug", bid, "imported", actor=actor, detail=title)
            imported += 1

    return {"imported": imported, "skipped": skipped, "errors": errors}

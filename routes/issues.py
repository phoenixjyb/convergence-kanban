"""Cross-team issues register, independent of software bug workflows."""

import json
import uuid

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import (
    _require_human, generate_issue_display_id, get_actor, issue_to_dict,
    log_activity, now_iso, validate_issue_values,
)
from models import IssueCreate, IssueUpdate

router = APIRouter(prefix="/api", tags=["issues"])


def _encode(values):
    result = dict(values)
    for field in ("task_ids", "bug_ids"):
        if field in result:
            result[field] = json.dumps(list(dict.fromkeys(result[field])))
    return result


@router.get("/issues")
def list_issues(category: str | None = None, status: str | None = None,
                owner: str | None = None, priority: str | None = None,
                include_deleted: bool = False):
    clauses, params = [], []
    if not include_deleted:
        clauses.append("deleted_at IS NULL")
    for field, value in (("category", category), ("status", status), ("owner", owner), ("priority", priority)):
        if value is not None:
            clauses.append(f"{field}=?")
            params.append(value)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM issues" + where +
            " ORDER BY (status='closed'), (rank=0), rank, "
            "CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, created_at DESC, id",
            params,
        ).fetchall()
        return [issue_to_dict(row) for row in rows]


@router.get("/issues/{iid}")
def get_issue(iid: str):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM issues WHERE id=? AND deleted_at IS NULL", (iid,)).fetchone()
        if not row:
            raise HTTPException(404, "Issue not found")
        return issue_to_dict(row)


@router.post("/issues")
def create_issue(body: IssueCreate, request: Request):
    actor, ts = get_actor(request), now_iso()
    values = body.model_dump(mode="json")
    values["raised_by"] = values["raised_by"].strip() or actor
    values["raised_date"] = values["raised_date"] or ts[:10]
    with get_db() as conn:
        if values["status"] == "closed":
            _require_human(conn, actor, "close issues", "issue")
        validate_issue_values(conn, values)
        values.update(id=uuid.uuid4().hex[:12], display_id=generate_issue_display_id(conn), created_at=ts, updated_at=ts)
        encoded = _encode(values)
        conn.execute(
            f"INSERT INTO issues ({', '.join(encoded)}) VALUES ({','.join('?' for _ in encoded)})",
            list(encoded.values()),
        )
        log_activity(conn, "issue", values["id"], "created", actor, f"{values['display_id']} {values['title']}")
        return {"id": values["id"], "display_id": values["display_id"]}


@router.put("/issues/{iid}")
def update_issue(iid: str, body: IssueUpdate, request: Request):
    changes = body.model_dump(mode="json", exclude_unset=True)
    if not changes:
        raise HTTPException(400, "No fields to update")
    nullable = {"project_id", "workstream_id", "due_date"}
    if any(value is None and field not in nullable for field, value in changes.items()):
        raise HTTPException(400, "Only project, workstream, and due date can be cleared with null")
    actor = get_actor(request)
    with get_db() as conn:
        row = conn.execute("SELECT * FROM issues WHERE id=? AND deleted_at IS NULL", (iid,)).fetchone()
        if not row:
            raise HTTPException(404, "Issue not found")
        if changes.get("status") == "closed":
            _require_human(conn, actor, "close issues", "issue", iid)
        validate_issue_values(conn, issue_to_dict(row) | changes, previous=issue_to_dict(row))
        encoded = _encode(changes | {"updated_at": now_iso()})
        conn.execute(f"UPDATE issues SET {', '.join(k+'=?' for k in encoded)} WHERE id=?", [*encoded.values(), iid])
        log_activity(conn, "issue", iid, "updated", actor, ", ".join(changes))
        return {"ok": True}


@router.delete("/issues/{iid}")
def delete_issue(iid: str, request: Request):
    actor, ts = get_actor(request), now_iso()
    with get_db() as conn:
        _require_human(conn, actor, "delete issues", "issue", iid)
        cur = conn.execute("UPDATE issues SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at IS NULL", (ts, ts, iid))
        if not cur.rowcount:
            raise HTTPException(404, "Issue not found")
        log_activity(conn, "issue", iid, "deleted", actor)
    return {"ok": True}


@router.post("/issues/{iid}/restore")
def restore_issue(iid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "restore issues", "issue", iid)
        cur = conn.execute("UPDATE issues SET deleted_at=NULL, updated_at=? WHERE id=? AND deleted_at IS NOT NULL", (now_iso(), iid))
        if not cur.rowcount:
            raise HTTPException(404, "Issue not found in bin")
        log_activity(conn, "issue", iid, "restored", actor)
    return {"ok": True}

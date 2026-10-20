"""Sync conflict resolution routes."""

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import (
    _require_human,
    apply_blocker_conflict,
    apply_blocker_conflicts,
    apply_bug_conflicts,
    apply_issue_conflict,
    apply_issue_conflicts,
    apply_task_conflict,
    apply_task_conflicts,
    get_actor,
    log_activity,
    now_iso,
)
from models import ConflictResolve

router = APIRouter(prefix="/api", tags=["sync_conflicts"])


def _choice_value(conflict, body):
    if body.resolution == "manual":
        return body.manual_value
    return conflict["local_value"] if body.resolution == "local" else conflict["remote_value"]


@router.get("/sync-conflicts")
def list_conflicts(resolved: bool = False):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sc.*, COALESCE(t.title_en, b.description_en, bg.title, i.title, '') as entity_title "
            "FROM sync_conflicts sc "
            "LEFT JOIN tasks t ON sc.entity_type='task' AND t.id=sc.entity_id "
            "LEFT JOIN blockers b ON sc.entity_type='blocker' AND b.id=sc.entity_id "
            "LEFT JOIN bugs bg ON sc.entity_type='bug' AND bg.id=sc.entity_id "
            "LEFT JOIN issues i ON sc.entity_type='issue' AND i.id=sc.entity_id "
            "WHERE sc.resolved=? ORDER BY sc.created_at DESC",
            (1 if resolved else 0,),
        ).fetchall()
        return [dict(row) for row in rows]


@router.get("/sync-conflicts/count")
def conflict_count():
    with get_db() as conn:
        row = conn.execute("SELECT count(*) c FROM sync_conflicts WHERE resolved=0").fetchone()
        return {"unresolved": row["c"]}


@router.put("/sync-conflicts/{cid}/resolve")
def resolve_conflict(cid: str, body: ConflictResolve, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        conflict = conn.execute(
            "SELECT * FROM sync_conflicts WHERE id=? AND resolved=0", (cid,)
        ).fetchone()
        if not conflict:
            raise HTTPException(404, "Conflict not found or already resolved")
        value = _choice_value(conflict, body)
        entity_type = conflict["entity_type"]
        if entity_type == "issue":
            apply_issue_conflict(conn, conflict, value, actor)
        elif entity_type == "bug":
            apply_bug_conflicts(conn, [(conflict, value)], actor)
        elif entity_type == "task":
            apply_task_conflict(conn, conflict, value, actor)
        elif entity_type == "blocker":
            apply_blocker_conflict(conn, conflict, value)
        else:
            raise HTTPException(400, "Unsupported sync conflict entity")
        conn.execute(
            "UPDATE sync_conflicts SET resolved=1, resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
            (body.resolution, actor, now_iso(), cid),
        )
        log_activity(
            conn, entity_type, conflict["entity_id"], "conflict_resolved",
            actor=actor, detail=f"{conflict['field_name']}: {body.resolution}",
        )
    return {"ok": True}


@router.post("/sync-conflicts/resolve-all")
def resolve_all_conflicts(body: ConflictResolve, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        conflicts = conn.execute("SELECT * FROM sync_conflicts WHERE resolved=0").fetchall()
        grouped = {kind: {} for kind in ("issue", "bug", "task", "blocker")}
        for conflict in conflicts:
            kind = conflict["entity_type"]
            if kind not in grouped:
                raise HTTPException(400, "Unsupported sync conflict entity")
            value = _choice_value(conflict, body)
            choice = (conflict, value)
            grouped[kind].setdefault(conflict["entity_id"], []).append(choice)

        for choices in grouped["issue"].values():
            if any(
                conflict["field_name"] == "deleted_at"
                or (conflict["field_name"] == "status" and value == "closed")
                for conflict, value in choices
            ):
                _require_human(conn, actor, "close/archive/restore issues")
        for bug_id in grouped["bug"]:
            _require_human(conn, actor, "resolve bug sync conflicts", "bug", bug_id)
        # Preflight before applying any choices because _require_human commits
        # its rejection audit entry before raising for bot actors.
        for task_id, choices in grouped["task"].items():
            statuses = [value for conflict, value in choices if conflict["field_name"] == "status"]
            if "done" in statuses:
                _require_human(conn, actor, "mark tasks as done — use 'in_review' instead", "task", task_id)
            if "abandoned" in statuses:
                _require_human(conn, actor, "mark tasks as abandoned — humans only", "task", task_id)

        for choices in grouped["issue"].values():
            apply_issue_conflicts(conn, choices, actor)
        for choices in grouped["bug"].values():
            apply_bug_conflicts(conn, choices, actor)
        for choices in grouped["task"].values():
            apply_task_conflicts(conn, choices, actor)
        for choices in grouped["blocker"].values():
            apply_blocker_conflicts(conn, choices)

        for conflict in conflicts:
            conn.execute(
                "UPDATE sync_conflicts SET resolved=1, resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
                (body.resolution, actor, now_iso(), conflict["id"]),
            )
        return {"ok": True, "resolved": len(conflicts)}

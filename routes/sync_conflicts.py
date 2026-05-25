"""Sync conflict resolution routes."""

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso
from models import ConflictResolve

router = APIRouter(prefix="/api", tags=["sync_conflicts"])


@router.get("/sync-conflicts")
def list_conflicts(resolved: bool = False):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT sc.*, COALESCE(t.title_en, b.description_en, bg.title, '') as entity_title "
            "FROM sync_conflicts sc "
            "LEFT JOIN tasks t ON sc.entity_type='task' AND t.id=sc.entity_id "
            "LEFT JOIN blockers b ON sc.entity_type='blocker' AND b.id=sc.entity_id "
            "LEFT JOIN bugs bg ON sc.entity_type='bug' AND bg.id=sc.entity_id "
            "WHERE sc.resolved=? ORDER BY sc.created_at DESC",
            (1 if resolved else 0,)).fetchall()
        return [dict(r) for r in rows]


@router.get("/sync-conflicts/count")
def conflict_count():
    with get_db() as conn:
        row = conn.execute("SELECT count(*) c FROM sync_conflicts WHERE resolved=0").fetchone()
        return {"unresolved": row["c"]}


@router.put("/sync-conflicts/{cid}/resolve")
def resolve_conflict(cid: str, body: ConflictResolve, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        conflict = conn.execute("SELECT * FROM sync_conflicts WHERE id=? AND resolved=0", (cid,)).fetchone()
        if not conflict:
            raise HTTPException(404, "Conflict not found or already resolved")
        value = (body.manual_value if body.resolution == "manual"
                 else conflict["local_value"] if body.resolution == "local"
                 else conflict["remote_value"])
        table_map = {"task": "tasks", "blocker": "blockers", "bug": "bugs"}
        allowed_fields = {"title", "title_en", "description_en", "status", "assignee",
                          "start_date", "due_date", "notes", "priority", "severity"}
        table = table_map.get(conflict["entity_type"])
        field = conflict["field_name"]
        if table and field and field in allowed_fields:
            if table == "blockers":
                # blockers table has no updated_at column
                conn.execute(f"UPDATE {table} SET {field}=? WHERE id=?",
                             (value, conflict["entity_id"]))
            else:
                conn.execute(f"UPDATE {table} SET {field}=?, updated_at=? WHERE id=?",
                             (value, now_iso(), conflict["entity_id"]))
        conn.execute("UPDATE sync_conflicts SET resolved=1, resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
                     (body.resolution, actor, now_iso(), cid))
        log_activity(conn, conflict["entity_type"], conflict["entity_id"], "conflict_resolved",
                     actor=actor, detail=f"{field}: {body.resolution}")
    return {"ok": True}


@router.post("/sync-conflicts/resolve-all")
def resolve_all_conflicts(body: ConflictResolve, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        conflicts = conn.execute("SELECT * FROM sync_conflicts WHERE resolved=0").fetchall()
        table_map = {"task": "tasks", "blocker": "blockers", "bug": "bugs"}
        allowed_fields = {"title", "title_en", "description_en", "status", "assignee",
                          "start_date", "due_date", "notes", "priority", "severity"}
        for c in conflicts:
            value = (body.manual_value if body.resolution == "manual"
                     else c["local_value"] if body.resolution == "local"
                     else c["remote_value"])
            table = table_map.get(c["entity_type"])
            if table and c["field_name"] and c["field_name"] in allowed_fields:
                if table == "blockers":
                    conn.execute(f"UPDATE {table} SET {c['field_name']}=? WHERE id=?",
                                 (value, c["entity_id"]))
                else:
                    conn.execute(f"UPDATE {table} SET {c['field_name']}=?, updated_at=? WHERE id=?",
                                 (value, now_iso(), c["entity_id"]))
            conn.execute("UPDATE sync_conflicts SET resolved=1, resolution=?, resolved_by=?, resolved_at=? WHERE id=?",
                         (body.resolution, actor, now_iso(), c["id"]))
        return {"ok": True, "resolved": len(conflicts)}

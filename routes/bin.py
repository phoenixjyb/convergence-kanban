"""Bin (soft-deleted items) restore and purge routes."""

from fastapi import APIRouter, HTTPException, Request

from db import get_db
from helpers import get_actor, log_activity, now_iso, _require_human

router = APIRouter(prefix="/api", tags=["bin"])


@router.get("/bin")
def list_bin():
    """List all soft-deleted items grouped by type."""
    result = {}
    with get_db() as conn:
        for table, label in [("projects", "projects"), ("workstreams", "workstreams"),
                              ("tasks", "tasks"), ("blockers", "blockers"),
                              ("bugs", "bugs")]:
            rows = conn.execute(f"SELECT * FROM {table} WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC").fetchall()
            result[label] = [dict(r) for r in rows]
    return result


@router.post("/{entity_type}/{eid}/restore")
def restore_item(entity_type: str, eid: str, request: Request):
    table_map = {"projects": "projects", "workstreams": "workstreams", "tasks": "tasks", "blockers": "blockers", "bugs": "bugs"}
    table = table_map.get(entity_type)
    if not table:
        raise HTTPException(400, f"Invalid entity type: {entity_type}")
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "restore deleted items")
        row = conn.execute(f"SELECT * FROM {table} WHERE id=? AND deleted_at IS NOT NULL", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "Item not found in bin")
        deleted_at = row["deleted_at"]
        conn.execute(f"UPDATE {table} SET deleted_at=NULL WHERE id=?", (eid,))
        # Cascade-restore children that were deleted at the same time (cascade-deleted)
        if entity_type == "projects":
            ws_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM workstreams WHERE project_id=? AND deleted_at=?", (eid, deleted_at)).fetchall()]
            if ws_ids:
                placeholders = ",".join("?" * len(ws_ids))
                conn.execute(f"UPDATE workstreams SET deleted_at=NULL WHERE id IN ({placeholders})", ws_ids)
                conn.execute(f"UPDATE tasks SET deleted_at=NULL WHERE workstream_id IN ({placeholders}) AND deleted_at=?",
                             ws_ids + [deleted_at])
                conn.execute(f"UPDATE blockers SET deleted_at=NULL WHERE workstream_id IN ({placeholders}) AND deleted_at=?",
                             ws_ids + [deleted_at])
                conn.execute(f"UPDATE recurring_tasks SET deleted_at=NULL WHERE workstream_id IN ({placeholders}) AND deleted_at=?",
                             ws_ids + [deleted_at])
        elif entity_type == "workstreams":
            conn.execute("UPDATE tasks SET deleted_at=NULL WHERE workstream_id=? AND deleted_at=?", (eid, deleted_at))
            conn.execute("UPDATE blockers SET deleted_at=NULL WHERE workstream_id=? AND deleted_at=?", (eid, deleted_at))
            conn.execute("UPDATE recurring_tasks SET deleted_at=NULL WHERE workstream_id=? AND deleted_at=?", (eid, deleted_at))
        log_activity(conn, entity_type.rstrip("s"), eid, "restored", actor=actor)
        return {"ok": True}


@router.delete("/{entity_type}/{eid}/purge")
def purge_item(entity_type: str, eid: str, request: Request):
    """Permanently delete a binned item."""
    table_map = {"projects": "projects", "workstreams": "workstreams", "tasks": "tasks", "blockers": "blockers", "bugs": "bugs"}
    table = table_map.get(entity_type)
    if not table:
        raise HTTPException(400, f"Invalid entity type: {entity_type}")
    actor = get_actor(request)
    with get_db() as conn:
        _require_human(conn, actor, "purge deleted items")
        row = conn.execute(f"SELECT id FROM {table} WHERE id=? AND deleted_at IS NOT NULL", (eid,)).fetchone()
        if not row:
            raise HTTPException(404, "Item not found in bin (only binned items can be purged)")
        conn.execute(f"DELETE FROM {table} WHERE id=?", (eid,))
        log_activity(conn, entity_type.rstrip("s"), eid, "purged", actor=actor)
        return {"ok": True}

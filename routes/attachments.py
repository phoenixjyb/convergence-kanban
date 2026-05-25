"""File attachment routes."""

import re as _re
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from fastapi.responses import FileResponse

from db import get_db, UPLOAD_DIR, MAX_UPLOAD_BYTES
from helpers import get_actor, log_activity, now_iso

router = APIRouter(prefix="/api", tags=["attachments"])


@router.post("/attachments/{entity_type}/{entity_id}")
async def upload_attachment(entity_type: str, entity_id: str, request: Request,
                            file: UploadFile = File(...)):
    if entity_type not in ("task", "bug", "workstream"):
        raise HTTPException(400, "Invalid entity type")
    table_map = {"task": "tasks", "bug": "bugs", "workstream": "workstreams"}
    with get_db() as conn:
        if not conn.execute(f"SELECT id FROM {table_map[entity_type]} WHERE id=? AND deleted_at IS NULL",
                            (entity_id,)).fetchone():
            raise HTTPException(404, f"{entity_type} not found")
    actor = get_actor(request)
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "File too large (max 20MB)")
    aid = uuid.uuid4().hex[:12]
    raw_name = Path(file.filename).name if file.filename else "upload"
    safe_name = _re.sub(r'[^a-zA-Z0-9._\-\u4e00-\u9fff]', '_', raw_name)[:200]
    disk_name = f"{aid}_{safe_name}"
    (UPLOAD_DIR / disk_name).write_bytes(content)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO attachments (id, entity_type, entity_id, filename, original_name, mime_type, size_bytes, uploader) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (aid, entity_type, entity_id, disk_name, safe_name,
             file.content_type or "application/octet-stream", len(content), actor))
        log_activity(conn, entity_type, entity_id, "attachment_added", actor=actor, detail=safe_name)
    return {"id": aid, "filename": safe_name, "size_bytes": len(content)}


@router.get("/attachments/download/{aid}")
def download_attachment(aid: str):
    with get_db() as conn:
        row = conn.execute("SELECT filename, original_name, mime_type FROM attachments WHERE id=? AND deleted_at IS NULL",
                           (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "Attachment not found")
        path = (UPLOAD_DIR / row["filename"]).resolve()
        if not str(path).startswith(str(UPLOAD_DIR.resolve())):
            raise HTTPException(403, "Invalid file path")
        if not path.exists():
            raise HTTPException(404, "File missing from disk")
        return FileResponse(path, filename=row["original_name"], media_type=row["mime_type"])


@router.get("/attachments/{entity_type}/{entity_id}")
def list_attachments(entity_type: str, entity_id: str):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, original_name, mime_type, size_bytes, uploader, created_at "
            "FROM attachments WHERE entity_type=? AND entity_id=? AND deleted_at IS NULL "
            "ORDER BY created_at DESC", (entity_type, entity_id)).fetchall()
        return [dict(r) for r in rows]


@router.delete("/attachments/{aid}")
def delete_attachment(aid: str, request: Request):
    actor = get_actor(request)
    with get_db() as conn:
        cur = conn.execute("UPDATE attachments SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (now_iso(), aid))
        if cur.rowcount == 0:
            raise HTTPException(404, "Attachment not found")
        log_activity(conn, "attachment", aid, "deleted", actor=actor)
    return {"ok": True}

"""Read-only Feishu sync status summary."""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from db import DATA_DIR, get_db
from helpers import TZ

router = APIRouter(prefix="/api", tags=["sync_status"])


def _parse_time(value: str) -> datetime | None:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=TZ)
        except ValueError:
            continue
    return None


def _age_seconds(value: str) -> int | None:
    parsed = _parse_time(value)
    if not parsed:
        return None
    return max(0, int((datetime.now(TZ) - parsed).total_seconds()))


def _max_timestamp(values: Any) -> str:
    if not isinstance(values, dict) or not values:
        return ""
    timestamps = [v for v in values.values() if isinstance(v, str) and v]
    return max(timestamps) if timestamps else ""


def _count_mapping(values: Any) -> int:
    if isinstance(values, dict):
        return len(values)
    if isinstance(values, list):
        return len(values)
    return 0


def _state_file_candidates() -> list[Path]:
    profile = os.environ.get("FEISHU_PROFILE", "").strip()
    candidates: list[Path] = []
    if profile:
        candidates.append(DATA_DIR / f"feishu_sync_state_{profile}.json")
    candidates.extend(sorted(DATA_DIR.glob("feishu_sync_state*.json")))
    seen = set()
    result = []
    for path in candidates:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        result.append(path)
    return result


def _choose_state_file() -> Path | None:
    candidates = _state_file_candidates()
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _safe_load_state(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _db_counts() -> dict[str, int]:
    with get_db() as conn:
        counts = {}
        for table in ("projects", "workstreams", "tasks", "bugs", "sync_conflicts"):
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if not exists:
                counts[table] = 0
                continue
            row = conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()
            counts[table] = row["c"]
        if counts.get("sync_conflicts"):
            row = conn.execute("SELECT COUNT(*) c FROM sync_conflicts WHERE resolved=0").fetchone()
            counts["unresolved_conflicts"] = row["c"]
        else:
            counts["unresolved_conflicts"] = 0
        return counts


def _table_summary(state: dict[str, Any], state_mtime: str) -> dict[str, dict[str, Any]]:
    task_latest = _max_timestamp(state.get("last_sync_ts_tasks"))
    qa_latest = _max_timestamp(state.get("last_sync_ts_bugs"))
    rd_latest = _max_timestamp(state.get("last_sync_ts_bugs_rd"))
    project_count = _count_mapping(state.get("synced_kids_projects"))

    return {
        "projects": {
            "configured": bool(state.get("projects_table")),
            "table_id_present": bool(state.get("projects_table")),
            "record_count": project_count,
            "latest_sync_at": state_mtime if project_count else "",
            "staleness_seconds": _age_seconds(state_mtime) if project_count else None,
        },
        "tasks": {
            "configured": bool(state.get("tasks_table")),
            "table_id_present": bool(state.get("tasks_table")),
            "record_count": _count_mapping(state.get("last_sync_ts_tasks")),
            "latest_sync_at": task_latest,
            "staleness_seconds": _age_seconds(task_latest),
        },
        "qa_bugs": {
            "configured": bool(state.get("bugs_table")),
            "table_id_present": bool(state.get("bugs_table")),
            "record_count": _count_mapping(state.get("last_sync_ts_bugs")),
            "latest_sync_at": qa_latest,
            "staleness_seconds": _age_seconds(qa_latest),
        },
        "rd_bugs": {
            "configured": bool(state.get("rd_bugs_table")),
            "table_id_present": bool(state.get("rd_bugs_table")),
            "record_count": _count_mapping(state.get("last_sync_ts_bugs_rd")),
            "latest_sync_at": rd_latest,
            "staleness_seconds": _age_seconds(rd_latest),
        },
    }


@router.get("/sync/status")
def sync_status():
    """Return sanitized sync health; never exposes credentials or raw state."""
    state_path = _choose_state_file()
    counts = _db_counts()
    if not state_path:
        configured = bool(os.environ.get("FEISHU_APP_ID") and os.environ.get("FEISHU_APP_SECRET"))
        return {
            "enabled": False,
            "reason": "No Feishu sync state file found." if configured else "Feishu is not configured.",
            "state_file": None,
            "state_mtime": "",
            "state_staleness_seconds": None,
            "tables": {},
            "db_counts": counts,
            "unresolved_conflicts": counts["unresolved_conflicts"],
        }

    state = _safe_load_state(state_path)
    mtime = datetime.fromtimestamp(state_path.stat().st_mtime, tz=TZ).strftime("%Y-%m-%d %H:%M:%S")
    has_tables = any(state.get(k) for k in ("projects_table", "tasks_table", "bugs_table", "rd_bugs_table"))
    return {
        "enabled": bool(has_tables),
        "reason": "" if has_tables else "Sync state file exists but no Feishu tables are configured.",
        "state_file": state_path.name,
        "state_mtime": mtime,
        "state_staleness_seconds": _age_seconds(mtime),
        "tables": _table_summary(state, mtime),
        "db_counts": counts,
        "unresolved_conflicts": counts["unresolved_conflicts"],
    }

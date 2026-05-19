#!/usr/bin/env python3
"""
Feishu Bitable <-> Kanban two-way sync service.

Centralized layout (after feishu_migrate.py):
  - Projects table (DuplexLinked to Tasks)
  - Tasks table (centralized, all projects)
  - Members table (DuplexLinked to Tasks via Executor/Assigned Tasks)
  - Bugs table (DuplexLinked to Projects and Tasks)

Env vars (or .env file):
  FEISHU_APP_ID / FEISHU_APP_SECRET
  KANBAN_DATA_DIR   — path to kanban data/ dir (default: ./data)
  SYNC_INTERVAL     — seconds between sync cycles (default: 30)
"""

import json
import os
import sqlite3
import sys
import time
import uuid
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# Project-wide timezone: Asia/Shanghai (UTC+8)
TZ = timezone(timedelta(hours=8))
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────
def load_dotenv(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

# Profile support: --profile <name> loads .env.<name> and uses separate state file
_profile = "default"
for i, arg in enumerate(sys.argv):
    if arg == "--profile" and i + 1 < len(sys.argv):
        _profile = sys.argv[i + 1]

_base = Path(__file__).parent
if _profile != "default":
    load_dotenv(_base / f".env.{_profile}")
load_dotenv(_base / ".env")  # fallback / shared vars

APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
DATA_DIR = Path(os.environ.get("KANBAN_DATA_DIR", _base / "data"))
DB_PATH = DATA_DIR / "kanban.db"
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL", "30"))
STATE_FILE = DATA_DIR / f"feishu_sync_state_{_profile}.json" if _profile != "default" else DATA_DIR / "feishu_sync_state.json"

_state = {}

# ── HTTP helpers (bypass proxy) ───────────────────────────────────────────
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def _request(url, method="GET", data=None, headers=None, _retries=3):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    body = json.dumps(data).encode() if data else None
    for attempt in range(_retries):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with _opener.open(req, timeout=15) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            if e.code < 500 and e.code != 429:
                # Client errors (except rate limit) — don't retry
                print(f"  HTTP {e.code}: {err_body[:300]}", flush=True)
                return {"code": e.code, "msg": err_body[:200]}
            wait = 2 ** attempt  # 1s, 2s, 4s
            print(f"[sync] Retry {attempt+1}/{_retries} for {url}: HTTP {e.code}", flush=True)
            if attempt < _retries - 1:
                time.sleep(wait)
            else:
                return {"code": e.code, "msg": err_body[:200]}
        except (urllib.error.URLError, OSError) as e:
            wait = 2 ** attempt
            print(f"[sync] Retry {attempt+1}/{_retries} for {url}: {e}", flush=True)
            if attempt < _retries - 1:
                time.sleep(wait)
            else:
                return {"code": -1, "msg": str(e)[:200]}

# ── Feishu Auth ───────────────────────────────────────────────────────────
_token_cache = {"token": "", "expires_at": 0}

def get_token():
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = _request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        method="POST",
        data={"app_id": APP_ID, "app_secret": APP_SECRET},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"Feishu auth failed: {resp}")
    _token_cache["token"] = resp["tenant_access_token"]
    _token_cache["expires_at"] = now + resp.get("expire", 7200)
    return _token_cache["token"]

def feishu_api(path, method="GET", data=None):
    url = f"https://open.feishu.cn/open-apis{path}"
    return _request(url, method=method, data=data,
                    headers={"Authorization": f"Bearer {get_token()}"})

# ── Optional feature→project mapping (loaded once at import time) ────────
def _load_feature_to_project_map():
    """Load the optional 'feature' → project_id mapping for bug auto-routing.
    Format: {"feature_label": "project_id", ...}. Place at config/feature_to_project.json
    relative to the project root. Returns {} if the file is missing.
    """
    path = _base / "config" / "feature_to_project.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"[sync] warning: could not parse {path}: {e}", flush=True)
        return {}


# ── State ─────────────────────────────────────────────────────────────────
def load_state():
    global _state
    if STATE_FILE.exists():
        _state = json.loads(STATE_FILE.read_text())

def save_state():
    STATE_FILE.write_text(json.dumps(_state, indent=2))

def bt():
    return _state.get("bitable_app_token", "")


# ── DB helpers ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def now_iso():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

# ── Feishu record helpers ─────────────────────────────────────────────────
def _text(val):
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(int(val)) if isinstance(val, float) and val == int(val) else str(val)
    if isinstance(val, list):
        return "".join(seg.get("text", str(seg)) if isinstance(seg, dict) else str(seg) for seg in val)
    return str(val)

def _is_chinese(text):
    """Return True if text contains CJK characters (likely Chinese input)."""
    if not text:
        return False
    return any('\u4e00' <= c <= '\u9fff' for c in text)


def _split_bilingual(text):
    """Return (title_en, title_zh) based on detected language."""
    if _is_chinese(text):
        return "", text
    return text, ""


def _date_to_ms(date_str):
    """Convert a date string (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS) to epoch ms for Feishu DateTime fields.
    Uses Asia/Shanghai timezone to match Feishu's date interpretation."""
    if not date_str:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            dt = datetime.strptime(date_str, fmt).replace(tzinfo=TZ)
            return int(dt.timestamp() * 1000)
        except ValueError:
            continue
    return None

def _ms_to_date(val):
    """Convert Feishu DateTime (epoch ms or string) to YYYY-MM-DD string."""
    if not val:
        return ""
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val / 1000, tz=TZ).strftime("%Y-%m-%d")
    s = _text(val)
    # Already a date string
    if s and len(s) >= 10 and s[4] in "-/":
        return s[:10]
    return s

def _link_ids(val):
    """Extract record_ids from a DuplexLink field value."""
    if not val:
        return []
    if isinstance(val, dict):
        return val.get("link_record_ids", [])
    if isinstance(val, list):
        # Could be [{"record_id": "..."}, ...] or ["recXXX", ...]
        result = []
        for item in val:
            if isinstance(item, dict):
                result.append(item.get("record_id", ""))
            elif isinstance(item, str):
                result.append(item)
        return result
    return []

def list_records(table_id):
    """Fetch all records from a Bitable table, paginating automatically.
    Returns (records, complete) tuple.  complete=False when any page
    request failed — callers MUST NOT interpret missing records as
    Feishu-side deletions when complete is False."""
    records = []
    page_token = ""
    while True:
        url = f"/bitable/v1/apps/{bt()}/tables/{table_id}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        resp = feishu_api(url)
        if resp.get("code") != 0:
            print(f"  [WARN] list_records page failed for table {table_id}: "
                  f"code={resp.get('code')} msg={resp.get('msg','')[:200]}", flush=True)
            return records, False
        items = resp.get("data", {}).get("items", [])
        records.extend(items)
        if not resp.get("data", {}).get("has_more"):
            break
        page_token = resp["data"].get("page_token", "")
    return records, True

def create_record(table_id, fields):
    resp = feishu_api(f"/bitable/v1/apps/{bt()}/tables/{table_id}/records",
                      method="POST", data={"fields": fields})
    if resp.get("code") != 0:
        print(f"  create_record err: code={resp.get('code')} msg={resp.get('msg','')[:200]}", flush=True)
        return None
    return resp.get("data", {}).get("record", {}).get("record_id")

def update_record(table_id, record_id, fields):
    feishu_api(f"/bitable/v1/apps/{bt()}/tables/{table_id}/records/{record_id}",
               method="PUT", data={"fields": fields})

def delete_record(table_id, record_id):
    feishu_api(f"/bitable/v1/apps/{bt()}/tables/{table_id}/records/{record_id}",
               method="DELETE")


def _dedupe_remote_records(records, table_id, label=""):
    """Detect records sharing the same kanban_id and delete the extras.

    Returns the deduplicated record list. Keeps the lowest record_id (oldest
    Feishu rid) for each kid. Hard-deletes the others from Feishu.

    This is a defensive cleanup against past sync glitches that created
    duplicate Bitable rows for the same kanban entity.
    """
    by_kid = {}  # kid -> list of records
    no_kid = []
    for rec in records:
        kid_field = rec.get("fields", {}).get("kanban_id", "")
        # Extract text value
        if isinstance(kid_field, list):
            kid = "".join(x.get("text", "") for x in kid_field if isinstance(x, dict))
        else:
            kid = str(kid_field or "")
        if kid:
            by_kid.setdefault(kid, []).append(rec)
        else:
            no_kid.append(rec)

    deduped = list(no_kid)
    deleted_count = 0
    for kid, recs in by_kid.items():
        if len(recs) == 1:
            deduped.append(recs[0])
            continue
        # Keep the record with the smallest record_id (oldest, most stable)
        sorted_recs = sorted(recs, key=lambda r: r["record_id"])
        keep = sorted_recs[0]
        deduped.append(keep)
        for extra in sorted_recs[1:]:
            try:
                delete_record(table_id, extra["record_id"])
                deleted_count += 1
            except Exception as e:
                print(f"  [dedupe{':' + label if label else ''}] failed to delete {extra['record_id']}: {e}", flush=True)
    if deleted_count:
        print(f"  [dedupe{':' + label if label else ''}] removed {deleted_count} duplicate records (kept {len(by_kid)} unique kids)", flush=True)
    return deduped


# ── Per-project table auto-creation ───────────────────────────────────────

_PROJECT_FIELDS = [
    ("Workstream", 1, None),
    ("Type", 3, {"options": [{"name": "Task"}, {"name": "Blocker"}]}),
    ("Status", 3, {"options": [
        {"name": "todo"}, {"name": "doing"}, {"name": "in_review"},
        {"name": "done"}, {"name": "blocked"}, {"name": "abandoned"},
    ]}),
    ("Priority", 3, {"options": [
        {"name": "critical"}, {"name": "high"}, {"name": "medium"}, {"name": "low"},
    ]}),
    ("Executor (Feishu)", 11, None),
    ("Start Date", 5, {"date_formatter": "yyyy/MM/dd"}),
    ("Due Date", 5, {"date_formatter": "yyyy/MM/dd"}),
    ("Notes", 1, None),
    ("kanban_id", 1, None),
    ("updated_at", 1, None),
]

def _ensure_project_table(project_id, project_name):
    """Create a per-project Feishu table if it doesn't exist yet. Returns table_id."""
    pt = _state.setdefault("project_tables", {})
    if project_id in pt:
        return pt[project_id]

    app_token = bt()
    # Create table
    resp = feishu_api(f"/bitable/v1/apps/{app_token}/tables",
                      method="POST", data={"table": {"name": project_name}})
    if resp.get("code") != 0:
        print(f"  ERROR creating per-project table '{project_name}': {resp}", flush=True)
        return None
    tid = resp.get("data", {}).get("table_id")
    print(f"  Created per-project table '{project_name}' -> {tid}", flush=True)

    # Rename default primary field to "Title"
    fields_resp = feishu_api(f"/bitable/v1/apps/{app_token}/tables/{tid}/fields")
    existing = fields_resp.get("data", {}).get("items", [])
    if existing and existing[0]["field_name"] != "Title":
        feishu_api(f"/bitable/v1/apps/{app_token}/tables/{tid}/fields/{existing[0]['field_id']}",
                   method="PUT", data={"field_name": "Title", "type": 1})

    # Add remaining fields
    for fname, ftype, fprop in _PROJECT_FIELDS:
        body = {"field_name": fname, "type": ftype}
        if fprop:
            body["property"] = fprop
        feishu_api(f"/bitable/v1/apps/{app_token}/tables/{tid}/fields",
                   method="POST", data=body)

    # Add kanban and gantt views
    for vname, vtype in [("🔄 Status Board", "kanban"), ("📅 Gantt Chart", "gantt")]:
        feishu_api(f"/bitable/v1/apps/{app_token}/tables/{tid}/views",
                   method="POST", data={"view_name": vname, "view_type": vtype})

    # Save to state
    pt[project_id] = tid
    save_state()
    return tid


# ══════════════════════════════════════════════════════════════════════════
# V2 (Centralized) Sync
# ══════════════════════════════════════════════════════════════════════════

def sync_projects_v2(db):
    """Two-way sync projects to the centralized Projects table."""
    projects_tid = _state["projects_table"]

    # Build local projects from DB
    projects = db.execute(
        "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY sort_order, name_en"
    ).fetchall()
    local = {}
    for p in projects:
        pid = p["id"]
        status, progress = _project_status(db, pid)
        local[pid] = {
            "Project": p["name_zh"] or p["name_en"],
            "Description": p["description"] or "",
            "Status": status,
            "Progress": progress,
            "Color": p["color"] if "color" in p.keys() else "",
            "kanban_id": pid,
            "updated_at": p["updated_at"] or p["created_at"] or "",
        }

    # Get remote
    remote_records, remote_complete = list_records(projects_tid)
    remote_by_kid = {}
    remote_new = []
    for rec in remote_records:
        kid = _text(rec.get("fields", {}).get("kanban_id", ""))
        if kid:
            remote_by_kid[kid] = rec
        else:
            remote_new.append(rec)

    stats = {"pushed": 0, "pulled": 0, "created": 0}
    # Map kanban_id -> feishu record_id for task linking
    proj_record_map = {kid: rec["record_id"] for kid, rec in remote_by_kid.items()}

    # Push local -> Feishu
    for pid, lp in local.items():
        if pid in remote_by_kid:
            remote = remote_by_kid[pid]
            rf = remote.get("fields", {})
            remote_ts = _text(rf.get("updated_at", ""))
            # Always push computed/derived fields even if project row unchanged
            remote_status = _text(rf.get("Status", ""))
            remote_progress = _text(rf.get("Progress", ""))
            remote_name = _text(rf.get("Project", ""))
            if (lp["updated_at"] > remote_ts or
                    lp["Project"] != remote_name or
                    lp["Status"] != remote_status or lp["Progress"] != remote_progress):
                update_record(projects_tid, remote["record_id"], lp)
                stats["pushed"] += 1
        else:
            # Not found in remote — could be Feishu deletion or incomplete read
            prev_synced = set(_state.get("synced_kids_projects", []))
            if pid in prev_synced:
                if remote_complete:
                    # Complete read confirms deletion on Feishu side
                    db.execute("UPDATE projects SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                               (now_iso(), pid))
                    print(f"  [feishu-del] project '{lp['Project']}' deleted from Feishu -> soft-deleted locally", flush=True)
                else:
                    # Incomplete read — do NOT treat as deletion, skip
                    print(f"  [WARN] incomplete read, skipping deletion check for project '{lp['Project']}'", flush=True)
                continue
            else:
                rid = create_record(projects_tid, lp)
                if rid:
                    proj_record_map[pid] = rid
                    stats["created"] += 1
        # Ensure per-project table exists
        _ensure_project_table(pid, lp["Project"])

    # Pull new Feishu projects -> local
    for rec in remote_new:
        f = rec.get("fields", {})
        name = _text(f.get("Project", ""))
        if not name:
            continue
        pid = uuid.uuid4().hex[:8]
        name_en, name_zh = _split_bilingual(name)
        db.execute(
            "INSERT OR IGNORE INTO projects (id, name_en, name_zh, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (pid, name_en or name, name_zh, _text(f.get("Description", "")), now_iso(), now_iso())
        )
        update_record(projects_tid, rec["record_id"],
                      {"kanban_id": pid, "updated_at": now_iso()})
        proj_record_map[pid] = rec["record_id"]
        _ensure_project_table(pid, name)
        stats["pulled"] += 1

    # Remove deleted projects from Feishu (only safe with complete read)
    if remote_complete:
        for kid, rec in remote_by_kid.items():
            if kid not in local:
                was_deleted = db.execute(
                    "SELECT id FROM projects WHERE id=? AND deleted_at IS NOT NULL", (kid,)
                ).fetchone()
                if was_deleted:
                    delete_record(projects_tid, rec["record_id"])

    # Save synced kanban_ids only from complete reads to avoid poisoning state
    if remote_complete:
        _state["synced_kids_projects"] = list(remote_by_kid.keys())
    save_state()

    db.commit()
    return stats, proj_record_map


def _project_status(db, pid):
    """Derive project status and progress from workstreams and tasks.

    Returns (status_str, progress_str).
    """
    ws_rows = db.execute(
        "SELECT id, status FROM workstreams WHERE project_id=? AND deleted_at IS NULL",
        (pid,)
    ).fetchall()
    if not ws_rows:
        return "planned", ""

    ws_ids = [r["id"] for r in ws_rows]
    statuses = {r["status"] for r in ws_rows}

    # Compute status
    if statuses <= {"done", "stable"}:
        status = "done"
    elif "blocked" in statuses:
        status = "blocked"
    elif "in-progress" in statuses or "review" in statuses:
        status = "in-progress"
    else:
        status = "planned"

    # Compute progress: count tasks across all workstreams
    placeholders = ",".join("?" * len(ws_ids))
    task_rows = db.execute(
        f"SELECT status FROM tasks WHERE workstream_id IN ({placeholders}) AND deleted_at IS NULL",
        ws_ids
    ).fetchall()
    total_tasks = len(task_rows)
    done_tasks = sum(1 for t in task_rows if t["status"] in ("done", "in_review"))

    ws_total = len(ws_rows)
    ws_done = sum(1 for r in ws_rows if r["status"] in ("done", "stable"))

    parts = []
    if total_tasks > 0:
        pct = int(done_tasks / total_tasks * 100)
        parts.append(f"Tasks: {done_tasks}/{total_tasks} ({pct}%)")
    if ws_total > 1:
        parts.append(f"WS: {ws_done}/{ws_total}")

    return status, " | ".join(parts)


def _build_user_open_id_map(db):
    """Build assignee name -> feishu_open_id map from users table.
    Indexes by name, display_name, and common variants (stripped @, first part of dotted name)."""
    result = {}
    try:
        rows = db.execute("SELECT name, display_name, feishu_open_id FROM users WHERE feishu_open_id != ''").fetchall()
        for r in rows:
            oid = r["feishu_open_id"]
            name = r["name"]
            disp = r["display_name"] or ""
            result[name.lower()] = oid
            result[name.lstrip("@").lower()] = oid
            if disp:
                result[disp.lower()] = oid
                result[disp.lstrip("@").lower()] = oid
            # Also index by first part of dotted name (e.g. "alice" from "alice.smith")
            if "." in name:
                result[name.split(".")[0].lower()] = oid
            if "." in disp:
                result[disp.split(".")[0].lower()] = oid
    except Exception:
        pass
    return result


def _save_feishu_open_id(db, assignee_name, open_id):
    """Store feishu_open_id for a user, creating the user if needed.

    Deduplication priority:
    1. Match by feishu_open_id (same Feishu person, possibly different name)
    2. Match by name or display_name
    3. Create new user
    """
    if not assignee_name or not open_id:
        return
    # First: look up by feishu_open_id to prevent duplicates for same person
    by_oid = db.execute("SELECT id, name FROM users WHERE feishu_open_id=?",
                        (open_id,)).fetchone()
    if by_oid:
        # Same Feishu person — update name if it changed (Feishu is authoritative)
        if by_oid["name"] != assignee_name:
            db.execute("UPDATE users SET name=?, display_name=? WHERE id=?",
                       (assignee_name, assignee_name, by_oid["id"]))
            db.commit()
        return
    # Second: look up by name/display_name
    existing = db.execute("SELECT id, feishu_open_id FROM users WHERE name=? OR display_name=?",
                          (assignee_name, assignee_name)).fetchone()
    if existing:
        if not existing["feishu_open_id"] or existing["feishu_open_id"] != open_id:
            db.execute("UPDATE users SET feishu_open_id=? WHERE id=?", (open_id, existing["id"]))
            db.commit()
    else:
        uid = uuid.uuid4().hex[:8]
        db.execute("INSERT OR IGNORE INTO users (id, name, display_name, feishu_open_id) VALUES (?,?,?,?)",
                   (uid, assignee_name, assignee_name, open_id))
        db.commit()


def _extract_person_field(field_value):
    """Extract (name, open_id) from a Feishu Person field value."""
    if not field_value or not isinstance(field_value, list):
        return None, None
    for person in field_value:
        if isinstance(person, dict) and person.get("id"):
            name = person.get("name") or person.get("en_name") or ""
            return name, person["id"]
    return None, None


def _bug_attachments_to_json(field_value):
    """Normalize a Feishu Attachment field (问题图片) to a JSON-encoded string
    of {file_token, name, size, type} dicts. Returns '' when the field is empty.

    Keeping only the stable metadata (not tmp_url, which expires) means two
    consecutive PULLs produce the same string, so vals_differ stays False
    and there's no churn.
    """
    if not field_value or not isinstance(field_value, list):
        return ""
    out = []
    for att in field_value:
        if not isinstance(att, dict):
            continue
        token = att.get("file_token")
        if not token:
            continue
        out.append({
            "file_token": token,
            "name": att.get("name", ""),
            "size": att.get("size", 0),
            "type": att.get("type", ""),
        })
    return json.dumps(out, ensure_ascii=False, sort_keys=True) if out else ""


def _extract_duplex_link_rids(field_value):
    """Extract record_ids from a Feishu DuplexLink field (returns list)."""
    if not field_value:
        return []
    if isinstance(field_value, dict):
        return field_value.get("record_ids", [])
    if isinstance(field_value, list):
        rids = []
        for item in field_value:
            if isinstance(item, str):
                rids.append(item)
            elif isinstance(item, dict):
                rids.extend(item.get("record_ids", []))
        return rids
    return []


def _sync_bug_task_links(db, bug_id, task_kids):
    """Sync bug_task_links for a bug to match the given task kanban_ids."""
    try:
        existing = {r["task_id"] for r in
                    db.execute("SELECT task_id FROM bug_task_links WHERE bug_id=?", (bug_id,)).fetchall()}
    except Exception:
        return  # table may not exist yet
    wanted = set(task_kids)
    for tid in wanted - existing:
        db.execute("INSERT OR IGNORE INTO bug_task_links (bug_id, task_id) VALUES (?, ?)", (bug_id, tid))
    for tid in existing - wanted:
        db.execute("DELETE FROM bug_task_links WHERE bug_id=? AND task_id=?", (bug_id, tid))


def _extract_native_parent(fields, record_id_to_kid):
    """Extract parent kanban_id from Feishu's native 父记录 (parent record) field."""
    parent_field = fields.get("\u7236\u8bb0\u5f55")  # 父记录
    if not parent_field:
        return None
    if isinstance(parent_field, dict):
        rids = parent_field.get("record_ids", [])
    elif isinstance(parent_field, list) and parent_field:
        rids = parent_field[0].get("record_ids", []) if isinstance(parent_field[0], dict) else []
    else:
        return None
    if rids and rids[0] in record_id_to_kid:
        return record_id_to_kid[rids[0]]
    return None


def sync_tasks_v2(db, proj_record_map, member_record_map=None):
    """Two-way sync all tasks+blockers to the centralized Tasks table."""
    tasks_tid = _state["tasks_table"]

    # Load last-sync timestamps for conflict detection
    last_sync_ts = _state.get("last_sync_ts_tasks", {})

    # Build user open_id map for Person field
    user_open_id_map = _build_user_open_id_map(db)

    # Build workstream lookups (all projects)
    ws_rows = db.execute(
        "SELECT w.id, w.title_en, w.title_zh, w.priority, w.project_id "
        "FROM workstreams w WHERE w.deleted_at IS NULL"
    ).fetchall()
    ws_names = {r["id"]: (r["title_zh"] or r["title_en"]) for r in ws_rows}
    ws_priority = {r["id"]: r["priority"] for r in ws_rows}
    ws_project = {r["id"]: r["project_id"] for r in ws_rows}
    ws_name_to_id = {}
    for r in ws_rows:
        # Key by (project_id, ws_name) to avoid cross-project collisions
        ws_name_to_id[(r["project_id"], r["title_en"])] = r["id"]

    # Build local items
    local_items = {}

    for t in db.execute("SELECT * FROM tasks WHERE deleted_at IS NULL").fetchall():
        wid = t["workstream_id"]
        if wid not in ws_names:
            continue
        task_priority = (t["priority"] if "priority" in t.keys() and t["priority"] else
                         ws_priority.get(wid, "medium"))
        local_items[t["id"]] = {
            "kanban_id": t["id"], "type": "Task",
            "title": t["title_zh"] or t["title_en"] or "",
            "workstream": ws_names.get(wid, ""),
            "project_id": ws_project.get(wid, ""),
            "status": t["status"] or "todo",
            "priority": task_priority,
            "assignee": t["assignee"] or "",
            "start_date": t["start_date"] or "" if "start_date" in t.keys() else "",
            "due_date": t["due_date"] or "",
            "notes": t["notes"] or "",
            "parent_task_id": t["parent_task_id"] or "" if "parent_task_id" in t.keys() else "",
            "updated_at": t["updated_at"] or t["created_at"] or "",
        }

    for b in db.execute("SELECT * FROM blockers WHERE deleted_at IS NULL").fetchall():
        wid = b["workstream_id"]
        if wid not in ws_names:
            continue
        local_items[b["id"]] = {
            "kanban_id": b["id"], "type": "Blocker",
            "title": b["description_zh"] or b["description_en"] or "",
            "workstream": ws_names.get(wid, ""),
            "project_id": ws_project.get(wid, ""),
            "status": "done" if b["resolved"] else "blocked",
            "priority": ws_priority.get(wid, "medium"),
            "assignee": b["assignee"] if "assignee" in b.keys() else "",
            "start_date": "", "due_date": "",
            "notes": b["notes"] if "notes" in b.keys() else "",
            "parent_task_id": "",
            "updated_at": (b["updated_at"] if "updated_at" in b.keys() and b["updated_at"] else
                            (b["resolved_at"] if b["resolved_at"] else None) or b["created_at"] or ""),
        }

    # Get remote records
    remote_records, remote_complete = list_records(tasks_tid)
    if remote_complete:
        remote_records = _dedupe_remote_records(remote_records, tasks_tid, label="tasks")
    remote_by_kid = {}
    remote_new = []
    for rec in remote_records:
        kid = _text(rec.get("fields", {}).get("kanban_id", ""))
        if kid:
            remote_by_kid[kid] = rec
        else:
            remote_new.append(rec)

    pushed, pulled, created_remote, created_local, deleted_remote = 0, 0, 0, 0, 0

    # Push local -> Feishu
    for kid, local in local_items.items():
        ff = {
            "Title": local["title"], "Workstream": local["workstream"],
            "Type": local["type"], "Status": local["status"],
            "Priority": local["priority"],
            "Notes": local["notes"],
            "kanban_id": kid, "updated_at": local["updated_at"],
        }
        # Date fields: convert to epoch ms for Feishu DateTime fields
        sd_ms = _date_to_ms(local["start_date"])
        if sd_ms:
            ff["Start Date"] = sd_ms
        dd_ms = _date_to_ms(local["due_date"])
        if dd_ms:
            ff["Due Date"] = dd_ms
        # DuplexLink to project
        proj_rid = proj_record_map.get(local["project_id"])
        if proj_rid:
            ff["Project"] = [proj_rid]
        # DuplexLink to member (Executor)
        if member_record_map and local["assignee"]:
            member_rid = member_record_map.get(local["assignee"].lower())
            if member_rid:
                ff["Executor"] = [member_rid]
        # Person field (Executor Feishu) — single source of truth for assignee
        assignee_key = local["assignee"].lstrip("@").lower() if local["assignee"] else ""
        if assignee_key:
            if assignee_key in user_open_id_map:
                ff["Executor (Feishu)"] = [{"id": user_open_id_map[assignee_key]}]
            else:
                print(f"[sync] WARNING: assignee '{local['assignee']}' has no feishu_open_id — "
                      f"task '{local['title'][:40]}' will have no executor on Bitable")
        # Parent task ID for subtask hierarchy
        if local.get("parent_task_id"):
            ff["Parent Task ID"] = local["parent_task_id"]

        if kid in remote_by_kid:
            remote = remote_by_kid[kid]
            rf = remote.get("fields", {})
            remote_ts = _text(rf.get("updated_at", ""))
            last_sync = last_sync_ts.get(kid, "")

            # Build local/remote value dicts for comparison
            # Resolve remote assignee from Executor (Feishu) person field
            _rpname, _rpoid = _extract_person_field(rf.get("Executor (Feishu)"))
            remote_assignee = _rpname or ""
            # Normalize: if remote person field is empty AND local assignee
            # is a user without feishu_open_id (e.g. bot agent), treat as match.
            if not remote_assignee and local["assignee"]:
                if local["assignee"].lstrip("@").lower() not in user_open_id_map:
                    remote_assignee = local["assignee"]
            if local["type"] == "Blocker":
                r_status = _text(rf.get("Status", ""))
                remote_vals = {
                    "title_en": _text(rf.get("Title", "")),
                    "status": "done" if r_status == "done" else "blocked",
                    "assignee": remote_assignee,
                    "notes": _text(rf.get("Notes", "")),
                }
                local_vals = {
                    "title_en": local["title"],
                    "status": local["status"],
                    "assignee": local["assignee"],
                    "notes": local["notes"],
                }
                etype = "blocker"
            else:
                remote_vals = {
                    "title_en": _text(rf.get("Title", "")),
                    "status": _text(rf.get("Status", "")),
                    "assignee": remote_assignee,
                    "start_date": _ms_to_date(rf.get("Start Date")),
                    "due_date": _ms_to_date(rf.get("Due Date")),
                    "notes": _text(rf.get("Notes", "")),
                }
                local_vals = {
                    "title_en": local["title"],
                    "status": local["status"],
                    "assignee": local["assignee"],
                    "start_date": local["start_date"],
                    "due_date": local["due_date"],
                    "notes": local["notes"],
                }
                etype = "task"

            local_changed = local["updated_at"] > last_sync if last_sync else False
            remote_changed = remote_ts > last_sync if last_sync else False

            if remote_vals == local_vals:
                pass  # In sync — nothing to do
            elif local_changed and remote_changed:
                # Both sides changed since last sync — record conflicts
                _record_conflicts(db, etype, kid, local_vals, remote_vals,
                                  local["updated_at"], remote_ts)
                print(f"  [sync-tasks] CONFLICT {kid} '{local['title'][:30]}' local_s={local_vals.get('status')} remote_s={remote_vals.get('status')}", flush=True)
            elif local_changed:
                # Only local changed — push to Feishu
                ts = now_iso()
                ff["updated_at"] = ts
                update_record(tasks_tid, remote["record_id"], ff)
                pushed += 1
                print(f"  [sync-tasks] PUSH {kid} '{local['title'][:30]}' status={local_vals.get('status')} (local_ts={local['updated_at']} remote_ts={remote_ts} last_sync={last_sync})", flush=True)
            else:
                # Values differ but local didn't change — remote must have changed.
                # Note: text 'updated_at' field is sync-managed, so manual Feishu UI
                # edits (e.g. dropdown Status changes) don't bump it. Trust the
                # observed value difference and pull from Feishu.
                _apply_remote_v2(db, kid, local, rf)
                update_record(tasks_tid, remote["record_id"], {"updated_at": now_iso()})
                pulled += 1
                print(f"  [sync-tasks] PULL {kid} '{local['title'][:30]}' local_s={local_vals.get('status')} remote_s={remote_vals.get('status')} (remote_changed={remote_changed} remote_ts={remote_ts} last_sync={last_sync})", flush=True)

            # Track last sync timestamp for this entity
            last_sync_ts[kid] = now_iso()
        else:
            # Not found in remote — could be Feishu deletion or incomplete read
            prev_synced = set(_state.get("synced_kids_tasks", []))
            if kid in prev_synced:
                if remote_complete:
                    # Complete read confirms deletion on Feishu side
                    table = "blockers" if local["type"] == "Blocker" else "tasks"
                    db.execute(f"UPDATE {table} SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                               (now_iso(), kid))
                    print(f"  [feishu-del] {local['type']} '{local['title'][:40]}' deleted from Feishu -> soft-deleted locally", flush=True)
                    deleted_remote += 1
                # else: incomplete read — skip, do not treat as deletion or create duplicate
            else:
                new_rid = create_record(tasks_tid, ff)
                if new_rid:
                    created_remote += 1
                    remote_by_kid[kid] = {"record_id": new_rid, "fields": ff}

    # Pull Feishu-only records (with kanban_id but not in local)
    for kid, remote in remote_by_kid.items():
        if kid in local_items:
            continue
        was_deleted = (
            db.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NOT NULL", (kid,)).fetchone()
            or db.execute("SELECT id FROM blockers WHERE id=? AND deleted_at IS NOT NULL", (kid,)).fetchone()
        )
        if was_deleted:
            # Only hard-delete from Feishu if we got a complete read
            # (otherwise the soft-delete may have been caused by a prior incomplete read)
            if remote_complete:
                delete_record(tasks_tid, remote["record_id"])
                deleted_remote += 1
            continue
        fields = remote.get("fields", {})
        title = _text(fields.get("Title", ""))
        if not title:
            continue
        ws_name = _text(fields.get("Workstream", ""))
        # Resolve workstream: try to find via project link first
        ws_id = _resolve_workstream(db, fields, ws_name, ws_name_to_id, proj_record_map)
        if not ws_id:
            continue
        item_type = _text(fields.get("Type", "Task"))
        status = _text(fields.get("Status", "todo"))
        # Executor (Feishu) person field is the single source of truth
        pname, poid = _extract_person_field(fields.get("Executor (Feishu)"))
        assignee = ""
        if pname and poid:
            _save_feishu_open_id(db, pname, poid)
            assignee = pname
        title_en, title_zh = _split_bilingual(title)
        if item_type == "Blocker":
            desc_en, desc_zh = title_en or title, title_zh
            db.execute(
                "INSERT OR IGNORE INTO blockers (id, workstream_id, description_en, description_zh, "
                "assignee, notes, resolved, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, desc_en, desc_zh, assignee,
                 _text(fields.get("Notes", "")),
                 1 if status == "done" else 0, now_iso())
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO tasks (id, workstream_id, title_en, title_zh, assignee, status, "
                "start_date, due_date, notes, parent_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, title_en or title, title_zh, assignee, status or "todo",
                 _ms_to_date(fields.get("Start Date")) or None,
                 _ms_to_date(fields.get("Due Date")) or None,
                 _text(fields.get("Notes", "")),
                 _text(fields.get("Parent Task ID", "")) or None, now_iso())
            )
        created_local += 1

    # Pull brand-new Feishu records (no kanban_id)
    for rec in remote_new:
        fields = rec.get("fields", {})
        title = _text(fields.get("Title", ""))
        if not title:
            continue
        ws_name = _text(fields.get("Workstream", ""))
        ws_id = _resolve_workstream(db, fields, ws_name, ws_name_to_id, proj_record_map)
        if not ws_id:
            continue
        item_type = _text(fields.get("Type", "Task"))
        status = _text(fields.get("Status", "todo"))
        kid = uuid.uuid4().hex[:8]
        # Executor (Feishu) person field is the single source of truth
        pname, poid = _extract_person_field(fields.get("Executor (Feishu)"))
        assignee = ""
        if pname and poid:
            _save_feishu_open_id(db, pname, poid)
            assignee = pname
        title_en, title_zh = _split_bilingual(title)
        if item_type == "Blocker":
            desc_en, desc_zh = title_en or title, title_zh
            db.execute(
                "INSERT OR IGNORE INTO blockers (id, workstream_id, description_en, description_zh, "
                "assignee, notes, resolved, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, desc_en, desc_zh, assignee,
                 _text(fields.get("Notes", "")),
                 1 if status == "done" else 0, now_iso())
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO tasks (id, workstream_id, title_en, title_zh, assignee, status, "
                "start_date, due_date, notes, parent_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, title_en or title, title_zh, assignee, status or "todo",
                 _ms_to_date(fields.get("Start Date")) or None,
                 _ms_to_date(fields.get("Due Date")) or None,
                 _text(fields.get("Notes", "")),
                 _text(fields.get("Parent Task ID", "")) or None, now_iso())
            )
        update_record(tasks_tid, rec["record_id"], {"kanban_id": kid, "updated_at": now_iso()})
        created_local += 1

    # ── Push parent hierarchy to Feishu native 父记录 field ──
    kid_to_rid = {kid: rec["record_id"] for kid, rec in remote_by_kid.items()}
    record_id_to_kid = {v: k for k, v in kid_to_rid.items()}
    pushed_parents = _state.get("pushed_parents_central", {})
    parents_changed = False
    for kid, local in local_items.items():
        parent_kid = local.get("parent_task_id")
        if not parent_kid or local["type"] == "Blocker":
            continue
        child_rid = kid_to_rid.get(kid)
        parent_rid = kid_to_rid.get(parent_kid)
        if not child_rid or not parent_rid:
            continue
        # Check if already pushed this exact parent (Feishu doesn't return 父记录 in list_records)
        if pushed_parents.get(kid) == parent_kid:
            continue
        # Also check via Feishu native field if available
        if kid in remote_by_kid:
            rf = remote_by_kid[kid].get("fields", {})
            existing_parent = _extract_native_parent(rf, record_id_to_kid)
            if existing_parent == parent_kid:
                pushed_parents[kid] = parent_kid
                parents_changed = True
                continue
        try:
            update_record(tasks_tid, child_rid,
                          {"\u7236\u8bb0\u5f55": {"record_ids": [parent_rid]}})
            pushed_parents[kid] = parent_kid
            parents_changed = True
            print(f"  [parent] central: set {kid} -> {parent_kid}", flush=True)
        except Exception as e:
            print(f"  [parent] central err: {kid} -> {parent_kid}: {e}", flush=True)
    if parents_changed:
        _state["pushed_parents_central"] = pushed_parents
        save_state()

    # Clean up soft-deletes — only push deletions to Feishu with complete read
    if remote_complete:
        for table in ("tasks", "blockers"):
            deleted = db.execute(f"SELECT id FROM {table} WHERE deleted_at IS NOT NULL").fetchall()
            for row in deleted:
                if row["id"] in remote_by_kid:
                    delete_record(tasks_tid, remote_by_kid[row["id"]]["record_id"])
                    deleted_remote += 1

    # Save synced kanban_ids only from complete reads to avoid poisoning state
    if remote_complete:
        _state["synced_kids_tasks"] = list(remote_by_kid.keys())
    _state["last_sync_ts_tasks"] = last_sync_ts
    save_state()

    db.commit()
    return {"pushed": pushed, "pulled": pulled, "created_remote": created_remote,
            "created_local": created_local, "deleted_remote": deleted_remote}


def _auto_create_workstream(db, project_id, ws_name):
    """Auto-create a workstream when Feishu has one that doesn't exist locally.
    Returns None if the project doesn't exist (FK would fail)."""
    if not db.execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone():
        return None
    wid = uuid.uuid4().hex[:8]
    db.execute(
        "INSERT INTO workstreams (id, project_id, title_en, priority, status, created_at, updated_at) "
        "VALUES (?, ?, ?, 'medium', 'planned', ?, ?)",
        (wid, project_id, ws_name, now_iso(), now_iso())
    )
    db.commit()
    print(f"  [auto-ws] Created workstream '{ws_name}' ({wid}) for project {project_id}", flush=True)
    return wid


def _resolve_workstream(db, fields, ws_name, ws_name_to_id, proj_record_map):
    """Resolve workstream ID from Feishu fields. Uses Project link if available.
    Auto-creates the workstream if it doesn't exist locally."""
    # Try to get project_id from DuplexLink
    project_links = _link_ids(fields.get("Project"))
    project_id = None
    if project_links:
        # Reverse-lookup: find kanban project_id from feishu record_id
        rid = project_links[0]
        for kid, rec_id in proj_record_map.items():
            if rec_id == rid:
                project_id = kid
                break

    if project_id and ws_name:
        ws_id = ws_name_to_id.get((project_id, ws_name))
        if ws_id:
            return ws_id
        # Auto-create workstream from Feishu
        wid = _auto_create_workstream(db, project_id, ws_name)
        if wid:
            ws_name_to_id[(project_id, ws_name)] = wid
        return wid

    # Fallback: try all projects
    if ws_name:
        for (pid, wname), wid in ws_name_to_id.items():
            if wname == ws_name:
                return wid
    return None


def _apply_remote_v2(db, kid, local, remote_fields):
    """Apply a Feishu edit back to local DB (v2 with start_date)."""
    title = _text(remote_fields.get("Title", ""))
    status = _text(remote_fields.get("Status", ""))
    # Executor (Feishu) person field is the single source of truth
    person_name, person_oid = _extract_person_field(remote_fields.get("Executor (Feishu)"))
    assignee = ""
    if person_name and person_oid:
        _save_feishu_open_id(db, person_name, person_oid)
        assignee = person_name
    new_en, new_zh = _split_bilingual(title)
    if local["type"] == "Blocker":
        resolved = 1 if status == "done" else 0
        # Preserve existing language column when remote changes to the other language
        desc_en = new_en or local.get("description_en") or title
        desc_zh = new_zh or local.get("description_zh") or ""
        notes = _text(remote_fields.get("Notes", ""))
        db.execute(
            "UPDATE blockers SET description_en=?, description_zh=?, assignee=?, notes=?, "
            "resolved=?, resolved_at=?, updated_at=? WHERE id=?",
            (desc_en, desc_zh, assignee, notes, resolved,
             now_iso() if resolved else None, now_iso(), kid)
        )
    else:
        # Preserve existing language column when remote changes to the other language
        # e.g. user replaces English with Chinese → update title_zh, keep existing title_en
        title_en = new_en or local.get("title_en") or title
        title_zh = new_zh or local.get("title_zh") or ""
        remote_parent = _text(remote_fields.get("Parent Task ID", ""))
        parent_id = remote_parent or local.get("parent_task_id") or None
        db.execute(
            "UPDATE tasks SET title_en=?, title_zh=?, assignee=?, status=?, start_date=?, due_date=?, notes=?, parent_task_id=?, updated_at=? WHERE id=?",
            (title_en, title_zh, assignee, status or "todo",
             _ms_to_date(remote_fields.get("Start Date")) or None,
             _ms_to_date(remote_fields.get("Due Date")) or None,
             _text(remote_fields.get("Notes", "")), parent_id, now_iso(), kid))
    db.commit()


def _record_conflicts(db, entity_type, entity_id, local_vals, remote_vals, local_ts, remote_ts):
    """Insert field-level conflicts into sync_conflicts table.
    Returns number of conflicts recorded."""
    count = 0
    for field, local_v in local_vals.items():
        remote_v = remote_vals.get(field, "")
        if str(local_v or "") != str(remote_v or ""):
            cid = str(uuid.uuid4())
            db.execute(
                "INSERT INTO sync_conflicts "
                "(id, entity_type, entity_id, field_name, local_value, remote_value, "
                "local_updated, remote_updated) VALUES (?,?,?,?,?,?,?,?)",
                (cid, entity_type, entity_id, field, str(local_v or ""),
                 str(remote_v or ""), local_ts, remote_ts))
            count += 1
    if count:
        db.commit()
        print(f"  [conflict] {entity_type} {entity_id}: {count} field(s) differ", flush=True)
    return count


def sync_members_v2(db):
    """Sync users to the Members table. Returns name->record_id map for DuplexLinks."""
    members_tid = _state.get("members_table")
    if not members_tid:
        return {}

    users = db.execute("SELECT * FROM users ORDER BY name").fetchall()
    local_users = {}
    for u in users:
        name = u["display_name"] if ("display_name" in u.keys() and u["display_name"]) else u["name"]
        fields = {
            "Name": name,
            "kanban_id": u["id"],
        }
        if "role" in u.keys() and u["role"]:
            fields["Role"] = u["role"]
        local_users[u["id"]] = fields

    remote_records, _remote_complete = list_records(members_tid)
    remote_by_kid = {}
    for rec in remote_records:
        kid = _text(rec.get("fields", {}).get("kanban_id", ""))
        if kid:
            remote_by_kid[kid] = rec

    # Build name -> record_id map (for linking tasks to members)
    member_record_map = {}
    for kid, rec in remote_by_kid.items():
        name = _text(rec.get("fields", {}).get("Name", ""))
        if name:
            member_record_map[name.lower()] = rec["record_id"]

    for uid, lu in local_users.items():
        if uid in remote_by_kid:
            rf = remote_by_kid[uid].get("fields", {})
            if _text(rf.get("Name", "")) != lu["Name"]:
                update_record(members_tid, remote_by_kid[uid]["record_id"], lu)
                member_record_map[lu["Name"].lower()] = remote_by_kid[uid]["record_id"]
        else:
            rid = create_record(members_tid, lu)
            if rid:
                member_record_map[lu["Name"].lower()] = rid

    return member_record_map


def sync_bugs_v2(db, proj_record_map, table_key="bugs_table",
                 source_filter="manual", state_suffix=""):
    """Two-way sync bugs to a Feishu Bitable table.

    table_key: state key for the Feishu table ID (e.g. 'bugs_table', 'rd_bugs_table')
    source_filter: only sync bugs with this source value ('manual' or 'agent')
    state_suffix: suffix for state keys to keep sync state separate (e.g. '_rd')

    Feishu field mapping (as restructured by team):
      Title              ↔ title (text)
      问题时间             ↔ issue_time (datetime, epoch ms in Feishu)
      问题版本             ↔ issue_version (single-select text)
      设备ID              ↔ device_id (single-select text, e.g. '160', '162')
      功能                ↔ feature (single-select)
      优先级              ↔ severity  (P0→critical, P1→high, P2→medium, P3→low)
      复现频率             ↔ repro_rate (single-select)
      Status             ↔ status   (To Do→open, In Progress→fixing, Fix Complete→fix_complete, To Verify→to_verify, Done→closed)
      Reporter (人员)     ↔ reporter (Person field → name text)
      Assignee (人员)     ↔ assignee (Person field → name text)
      Environment        ↔ environment (text)
      Steps to Reproduce ↔ steps_to_reproduce (text)
      问题图片             → issue_images (Attachment array → JSON of {file_token,name,size,type}; pull-only — pushing files is out of scope)
      Project            ↔ project_id (DuplexLink)
      Related Task       ↔ bug_task_links (DuplexLink, many-to-many)
      kanban_id          ↔ id
      updated_at         ↔ updated_at
    """
    bugs_tid = _state.get(table_key)
    if not bugs_tid:
        return

    try:
        db.execute("SELECT 1 FROM bugs LIMIT 0")
    except Exception:
        return

    _state_key_ts = f"last_sync_ts_bugs{state_suffix}"
    _state_key_kids = f"synced_kids_bugs{state_suffix}"
    last_sync_ts_bugs = _state.get(_state_key_ts, {})

    # ── Mapping dicts ────────────────────────────────────────────────────
    # Kanban severity → Feishu 优先级
    SEV_TO_FEISHU = {"critical": "P0", "high": "P1", "medium": "P2", "low": "P3"}
    FEISHU_TO_SEV = {"P0": "critical", "P1": "high", "P2": "medium", "P3": "low"}

    # Kanban status → Feishu Status
    STATUS_TO_FEISHU = {
        "open": "To Do", "investigating": "In Progress", "fixing": "In Progress",
        "fix_complete": "Fix Complete",
        "to_verify": "To Verify", "resolved": "Done", "closed": "Done", "wontfix": "Done",
    }
    FEISHU_TO_STATUS = {
        "To Do": "open", "In Progress": "fixing",
        "Fix Complete": "fix_complete",
        "To Verify": "to_verify", "Done": "closed",
    }

    VALID_STATUSES = ("open", "investigating", "fixing", "fix_complete", "to_verify", "resolved", "closed", "wontfix")
    VALID_SEVS = ("critical", "high", "medium", "low")

    # Feature (功能) → project_id auto-mapping.
    # Loaded from config/feature_to_project.json if present; otherwise empty
    # (bugs without a project_id stay unmapped). See docs/SETUP.md.
    FEATURE_TO_PROJECT = _load_feature_to_project_map()

    def _get_col(b, col):
        """Safe column access for sqlite3.Row."""
        try:
            return b[col] or ""
        except (IndexError, KeyError):
            return ""

    # ── Build user open_id map for Person field push ─────────────────────
    user_open_id_map = _build_user_open_id_map(db)

    # ── Build local bugs ─────────────────────────────────────────────────
    bugs = db.execute(
        "SELECT * FROM bugs WHERE deleted_at IS NULL AND COALESCE(source,'manual')=? ORDER BY created_at DESC",
        (source_filter,)
    ).fetchall()
    bug_task_map = {}
    try:
        for row in db.execute("SELECT bug_id, task_id FROM bug_task_links").fetchall():
            bug_task_map.setdefault(row["bug_id"], []).append(row["task_id"])
    except Exception:
        pass

    local_bugs = {}
    for b in bugs:
        local_bugs[b["id"]] = {
            "kanban_id": b["id"],
            "title": b["title"],
            "severity": b["severity"],
            "status": b["status"],
            "reporter": b["reporter"] or "",
            "assignee": b["assignee"] or "",
            "environment": b["environment"] or "",
            "steps_to_reproduce": b["steps_to_reproduce"] or "",
            "description": b["description"] or "",
            "project_id": b["project_id"] or "",
            "task_id": b["task_id"] or "",
            "task_ids": bug_task_map.get(b["id"], []),
            "issue_time": _get_col(b, "issue_time"),
            "feature": _get_col(b, "feature"),
            "repro_rate": _get_col(b, "repro_rate"),
            "issue_version": _get_col(b, "issue_version"),
            "device_id": _get_col(b, "device_id"),
            "issue_images": _get_col(b, "issue_images"),  # JSON text
            "updated_at": b["updated_at"] or b["created_at"] or "",
        }

    # ── Build task record maps (both directions) ─────────────────────────
    tasks_tid = _state.get("tasks_table")
    task_record_map = {}
    task_rid_to_kid = {}
    if tasks_tid:
        _task_recs, _ = list_records(tasks_tid)
        for rec in _task_recs:
            kid = _text(rec.get("fields", {}).get("kanban_id", ""))
            if kid:
                task_record_map[kid] = rec["record_id"]
                task_rid_to_kid[rec["record_id"]] = kid

    # ── Get remote records ───────────────────────────────────────────────
    remote_records, remote_complete = list_records(bugs_tid)
    if remote_complete:
        remote_records = _dedupe_remote_records(remote_records, bugs_tid, label="bugs")
    remote_by_kid = {}
    remote_new = []
    for rec in remote_records:
        kid = _text(rec.get("fields", {}).get("kanban_id", ""))
        if kid:
            remote_by_kid[kid] = rec
        else:
            remote_new.append(rec)

    pushed, pulled, created_remote, created_local = 0, 0, 0, 0

    # ── Push local → Feishu ──────────────────────────────────────────────
    for kid, local in local_bugs.items():
        ff = {
            "Title": local["title"],
            "Status": STATUS_TO_FEISHU.get(local["status"], "To Do"),
            "Environment": local["environment"],
            "Steps to Reproduce": local["steps_to_reproduce"],
            "Bug ID": _get_col(local, "display_id"),
            "kanban_id": kid,
            "updated_at": local["updated_at"],
        }
        # Map severity → 优先级
        if local["severity"] in SEV_TO_FEISHU:
            ff["优先级"] = SEV_TO_FEISHU[local["severity"]]
        # Map feature, repro_rate
        if local["feature"]:
            ff["功能"] = local["feature"]
        if local["repro_rate"]:
            ff["复现频率"] = local["repro_rate"]
        if local["issue_version"]:
            ff["问题版本"] = local["issue_version"]
        if local["device_id"]:
            ff["设备ID"] = local["device_id"]
        # issue_images are pull-only from Feishu — pushing would require a
        # separate file upload API. Intentionally omitted from ff.
        # issue_time → 问题时间 (epoch ms)
        if local["issue_time"]:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(local["issue_time"])
                ff["问题时间"] = int(dt.timestamp() * 1000)
            except Exception:
                pass
        # Fix metadata: 修复方法 / 修复版本 / 修复日期
        if _get_col(local, "fix_method"):
            ff["修复方法"] = _get_col(local, "fix_method")
        if _get_col(local, "fix_version"):
            ff["修复版本"] = _get_col(local, "fix_version")
        if _get_col(local, "fix_date"):
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(_get_col(local, "fix_date"))
                ff["修复日期"] = int(dt.timestamp() * 1000)
            except Exception:
                pass
        # Person fields: push as user open_id if available (old bugs table uses
        # Person fields named "Reporter (人员 )" / "Assignee (人员 )"; rd-bugs-list
        # uses plain text fields named "Reporter" / "Assignee")
        if table_key == "rd_bugs_table":
            # Text fields — just push the name string
            if local["reporter"]:
                ff["Reporter"] = local["reporter"]
            if local["assignee"]:
                ff["Assignee"] = local["assignee"]
        else:
            # Person fields — push open_id for Feishu @mention
            if local["reporter"]:
                oid = user_open_id_map.get(local["reporter"].lower())
                if oid:
                    ff["Reporter (人员 )"] = [{"id": oid}]
            if local["assignee"]:
                oid = user_open_id_map.get(local["assignee"].lower())
                if oid:
                    ff["Assignee (人员 )"] = [{"id": oid}]
        # DuplexLink to project
        proj_rid = proj_record_map.get(local["project_id"])
        if proj_rid:
            ff["Project"] = [proj_rid]
        # DuplexLink to tasks (many-to-many)
        linked_rids = [task_record_map[tid] for tid in local.get("task_ids", [])
                       if tid in task_record_map]
        if not linked_rids and local.get("task_id") and local["task_id"] in task_record_map:
            linked_rids = [task_record_map[local["task_id"]]]
        if linked_rids:
            ff["Related Task"] = linked_rids

        if kid in remote_by_kid:
            remote = remote_by_kid[kid]
            rf = remote.get("fields", {})
            remote_ts = _text(rf.get("updated_at", ""))

            # ── Build comparison dicts ────────────────────────────
            # Extract person fields
            rpt_name, rpt_oid = _extract_person_field(rf.get("Reporter (人员 )"))
            asg_name, asg_oid = _extract_person_field(rf.get("Assignee (人员 )"))
            if rpt_name and rpt_oid:
                _save_feishu_open_id(db, rpt_name, rpt_oid)
            if asg_name and asg_oid:
                _save_feishu_open_id(db, asg_name, asg_oid)

            r_status = FEISHU_TO_STATUS.get(_text(rf.get("Status", "")), "open")
            r_severity = FEISHU_TO_SEV.get(_text(rf.get("优先级", "")), "medium")
            r_feature = _text(rf.get("功能", ""))
            r_repro = _text(rf.get("复现频率", ""))
            r_reporter = rpt_name or ""
            r_assignee = asg_name or ""
            # Normalize: empty Person field for users without feishu_open_id ≠ change.
            # Otherwise the comparison would always diff and force a destructive PULL.
            if not r_reporter and local["reporter"]:
                if local["reporter"].lstrip("@").lower() not in user_open_id_map:
                    r_reporter = local["reporter"]
            if not r_assignee and local["assignee"]:
                if local["assignee"].lstrip("@").lower() not in user_open_id_map:
                    r_assignee = local["assignee"]
            r_issue_time = ""
            raw_it = rf.get("问题时间")
            if raw_it and isinstance(raw_it, (int, float)):
                try:
                    from datetime import datetime
                    r_issue_time = datetime.fromtimestamp(raw_it / 1000, tz=TZ).strftime("%Y-%m-%d %H:%M")
                except Exception:
                    pass

            r_issue_version = _text(rf.get("问题版本", ""))
            r_device_id = _text(rf.get("设备ID", ""))
            r_issue_images_json = _bug_attachments_to_json(rf.get("问题图片"))
            r_fix_method = _text(rf.get("修复方法", ""))
            r_fix_version = _text(rf.get("修复版本", ""))
            r_fix_date = ""
            raw_fd = rf.get("修复日期")
            if raw_fd and isinstance(raw_fd, (int, float)):
                try:
                    from datetime import datetime
                    r_fix_date = datetime.fromtimestamp(raw_fd / 1000, tz=TZ).strftime("%Y-%m-%d")
                except Exception:
                    pass

            remote_vals = {
                "title": _text(rf.get("Title", "")),
                "status": r_status,
                "assignee": r_assignee,
                "severity": r_severity,
                "reporter": r_reporter,
                "environment": _text(rf.get("Environment", "")),
                "steps": _text(rf.get("Steps to Reproduce", "")),
                "feature": r_feature,
                "repro_rate": r_repro,
                "issue_time": r_issue_time,
                "issue_version": r_issue_version,
                "device_id": r_device_id,
                "issue_images": r_issue_images_json,
                "fix_method": r_fix_method,
                "fix_version": r_fix_version,
                "fix_date": r_fix_date,
            }
            local_vals = {
                "title": local["title"],
                "status": local["status"],
                "assignee": local["assignee"],
                "severity": local["severity"],
                "reporter": local["reporter"],
                "environment": local["environment"],
                "steps": local["steps_to_reproduce"],
                "feature": local["feature"],
                "repro_rate": local["repro_rate"],
                "issue_time": local["issue_time"],
                "issue_version": local["issue_version"],
                "device_id": local["device_id"],
                "issue_images": local["issue_images"] or "",
                "fix_method": _get_col(local, "fix_method"),
                "fix_version": _get_col(local, "fix_version"),
                "fix_date": _get_col(local, "fix_date"),
            }

            # ── Sync decision (last_sync_ts aware) ───────────────
            last_sync = last_sync_ts_bugs.get(kid, "")
            local_changed = local["updated_at"] > last_sync if last_sync else False
            remote_changed = remote_ts > last_sync if last_sync else False

            if remote_vals == local_vals:
                pass  # In sync — nothing to do
            elif local_changed and remote_changed:
                _record_conflicts(db, "bug", kid, local_vals, remote_vals,
                                  local["updated_at"], remote_ts)
                print(f"  [sync-bugs] CONFLICT {kid} local_s={local_vals.get('status')} remote_s={remote_vals.get('status')}", flush=True)
            elif local_changed:
                # Only local changed — push to Feishu
                ts = now_iso()
                ff["updated_at"] = ts
                update_record(bugs_tid, remote["record_id"], ff)
                pushed += 1
                print(f"  [sync-bugs] PUSH {kid} status={local_vals.get('status')} (local_ts={local['updated_at']} remote_ts={remote_ts} last_sync={last_sync})", flush=True)
            else:
                # Values differ but local didn't change — remote (Feishu UI edit)
                # is the source of truth. Pull from Feishu.
                if r_status not in VALID_STATUSES:
                    r_status = "open"
                if r_severity not in VALID_SEVS:
                    r_severity = "medium"
                # FK constraint: empty string project_id fails. Use None instead.
                r_project_id = FEATURE_TO_PROJECT.get(r_feature, "") or local.get("project_id", "") or None
                db.execute(
                    "UPDATE bugs SET title=?, status=?, assignee=?, severity=?, "
                    "reporter=?, environment=?, steps_to_reproduce=?, "
                    "feature=?, repro_rate=?, issue_time=?, "
                    "issue_version=?, device_id=?, issue_images=?, "
                    "fix_method=?, fix_version=?, fix_date=?, "
                    "project_id=?, updated_at=? WHERE id=?",
                    (_text(rf.get("Title", "")), r_status,
                     r_assignee, r_severity,
                     r_reporter, _text(rf.get("Environment", "")),
                     _text(rf.get("Steps to Reproduce", "")),
                     r_feature, r_repro, r_issue_time,
                     r_issue_version, r_device_id, r_issue_images_json,
                     r_fix_method, r_fix_version, r_fix_date,
                     r_project_id, now_iso(), kid)
                )
                # Sync Task DuplexLink → bug_task_links
                remote_task_rids = _extract_duplex_link_rids(rf.get("Related Task"))
                remote_task_kids = [task_rid_to_kid[rid] for rid in remote_task_rids
                                    if rid in task_rid_to_kid]
                if remote_task_kids:
                    _sync_bug_task_links(db, kid, remote_task_kids)
                update_record(bugs_tid, remote["record_id"], {"updated_at": now_iso()})
                pulled += 1
                print(f"  [sync-bugs] PULL {kid} local_s={local_vals.get('status')} remote_s={remote_vals.get('status')} (remote_ts={remote_ts} last_sync={last_sync})", flush=True)

            last_sync_ts_bugs[kid] = now_iso()
        else:
            # Bug exists in kanban but not in Feishu.
            # Check if it was previously synced — if so, the user deleted it
            # on Feishu and we should soft-delete locally instead of recreating.
            prev_synced = set(_state.get("synced_kids_bugs", []))
            if kid in prev_synced:
                if remote_complete:
                    db.execute("UPDATE bugs SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                               (now_iso(), kid))
                    print(f"  [feishu-del] bug '{local['title'][:40]}' deleted from Feishu -> soft-deleted locally", flush=True)
                # else: incomplete read — skip, do not treat as deletion or recreate
            else:
                if create_record(bugs_tid, ff):
                    created_remote += 1

    # ── Pull new Feishu bugs ─────────────────────────────────────────────
    for rec in remote_new:
        f = rec.get("fields", {})
        title = _text(f.get("Title", ""))
        if not title:
            continue
        kid = uuid.uuid4().hex[:8]

        # Map values
        _bug_status = FEISHU_TO_STATUS.get(_text(f.get("Status", "")), "open")
        if _bug_status not in VALID_STATUSES:
            _bug_status = "open"
        _bug_severity = FEISHU_TO_SEV.get(_text(f.get("优先级", "")), "medium")
        if _bug_severity not in VALID_SEVS:
            _bug_severity = "medium"

        # Person fields
        rpt_name, rpt_oid = _extract_person_field(f.get("Reporter (人员 )"))
        asg_name, asg_oid = _extract_person_field(f.get("Assignee (人员 )"))
        if rpt_name and rpt_oid:
            _save_feishu_open_id(db, rpt_name, rpt_oid)
        if asg_name and asg_oid:
            _save_feishu_open_id(db, asg_name, asg_oid)

        # Feature, repro_rate
        _feature = _text(f.get("功能", ""))
        _repro = _text(f.get("复现频率", ""))

        # issue_time
        _issue_time = ""
        raw_it = f.get("问题时间")
        if raw_it and isinstance(raw_it, (int, float)):
            try:
                from datetime import datetime
                _issue_time = datetime.fromtimestamp(raw_it / 1000, tz=TZ).strftime("%Y-%m-%d %H:%M")
            except Exception:
                pass

        # Auto-map feature → project_id (None if not mapped, to satisfy FK constraint)
        _project_id = FEATURE_TO_PROJECT.get(_feature) or None

        _issue_version = _text(f.get("问题版本", ""))
        _device_id = _text(f.get("设备ID", ""))
        _issue_images_json = _bug_attachments_to_json(f.get("问题图片"))
        _fix_method = _text(f.get("修复方法", ""))
        _fix_version = _text(f.get("修复版本", ""))
        _fix_date = ""
        raw_fd = f.get("修复日期")
        if raw_fd and isinstance(raw_fd, (int, float)):
            try:
                from datetime import datetime
                _fix_date = datetime.fromtimestamp(raw_fd / 1000, tz=TZ).strftime("%Y-%m-%d")
            except Exception:
                pass

        db.execute(
            "INSERT OR IGNORE INTO bugs (id, title, severity, status, reporter, "
            "assignee, environment, steps_to_reproduce, feature, repro_rate, issue_time, "
            "issue_version, device_id, issue_images, source, "
            "fix_method, fix_version, fix_date, "
            "project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kid, title, _bug_severity, _bug_status,
             rpt_name or "", asg_name or "",
             _text(f.get("Environment", "")), _text(f.get("Steps to Reproduce", "")),
             _feature, _repro, _issue_time,
             _issue_version, _device_id, _issue_images_json, source_filter,
             _fix_method, _fix_version, _fix_date,
             _project_id, now_iso(), now_iso())
        )
        # Sync Task DuplexLink → bug_task_links for new bugs
        remote_task_rids = _extract_duplex_link_rids(f.get("Related Task"))
        remote_task_kids = [task_rid_to_kid[rid] for rid in remote_task_rids
                            if rid in task_rid_to_kid]
        if remote_task_kids:
            _sync_bug_task_links(db, kid, remote_task_kids)
            db.execute("UPDATE bugs SET task_id=? WHERE id=?", (remote_task_kids[0], kid))
        # Generate display_id for the new bug and push it back
        _new_display_id = ""
        try:
            from helpers import generate_bug_display_id
            _new_display_id = generate_bug_display_id(db, source_filter)
            db.execute("UPDATE bugs SET display_id=? WHERE id=?", (_new_display_id, kid))
        except Exception:
            pass
        update_record(bugs_tid, rec["record_id"], {"kanban_id": kid, "Bug ID": _new_display_id, "updated_at": now_iso()})
        created_local += 1

    # Clean up soft-deletes — only push deletions to Feishu with complete read
    if remote_complete:
        deleted = db.execute(
            "SELECT id FROM bugs WHERE deleted_at IS NOT NULL AND COALESCE(source,'manual')=?",
            (source_filter,)
        ).fetchall()
        for row in deleted:
            if row["id"] in remote_by_kid:
                delete_record(bugs_tid, remote_by_kid[row["id"]]["record_id"])

    # Save synced kanban_ids only from complete reads to avoid poisoning state
    if remote_complete:
        _state[_state_key_kids] = list(remote_by_kid.keys())
    _state[_state_key_ts] = last_sync_ts_bugs
    save_state()
    db.commit()


# ══════════════════════════════════════════════════════════════════════════
# Per-project table sync (bi-directional)
# ══════════════════════════════════════════════════════════════════════════

def sync_project_items(db, project_id, feishu_table_id):
    """Two-way sync tasks+blockers for one project to its own Feishu table."""
    # Load last-sync timestamps for conflict detection
    ls_key = f"last_sync_ts_{project_id}"
    last_sync_ts = _state.get(ls_key, {})

    user_open_id_map = _build_user_open_id_map(db)
    ws_rows = db.execute(
        "SELECT id, title_en, title_zh, priority FROM workstreams WHERE project_id=? AND deleted_at IS NULL",
        (project_id,)
    ).fetchall()
    ws_names = {r["id"]: (r["title_zh"] or r["title_en"]) for r in ws_rows}
    ws_priority = {r["id"]: r["priority"] for r in ws_rows}
    ws_ids = set(ws_names.keys())
    ws_name_to_id = {v: k for k, v in ws_names.items()}

    local_items = {}

    for t in db.execute("SELECT * FROM tasks WHERE deleted_at IS NULL").fetchall():
        if t["workstream_id"] not in ws_ids:
            continue
        local_items[t["id"]] = {
            "kanban_id": t["id"], "type": "Task",
            "title": t["title_zh"] or t["title_en"] or "",
            "workstream": ws_names.get(t["workstream_id"], ""),
            "status": t["status"] or "todo",
            "priority": ws_priority.get(t["workstream_id"], "medium"),
            "assignee": t["assignee"] or "",
            "start_date": t["start_date"] or "" if "start_date" in t.keys() else "",
            "due_date": t["due_date"] or "",
            "notes": t["notes"] or "",
            "parent_task_id": t["parent_task_id"] or "" if "parent_task_id" in t.keys() else "",
            "updated_at": t["updated_at"] or t["created_at"] or "",
        }

    for b in db.execute("SELECT * FROM blockers WHERE deleted_at IS NULL").fetchall():
        if b["workstream_id"] not in ws_ids:
            continue
        local_items[b["id"]] = {
            "kanban_id": b["id"], "type": "Blocker",
            "title": b["description_zh"] or b["description_en"] or "",
            "workstream": ws_names.get(b["workstream_id"], ""),
            "status": "done" if b["resolved"] else "blocked",
            "priority": ws_priority.get(b["workstream_id"], "medium"),
            "assignee": b["assignee"] if "assignee" in b.keys() else "",
            "start_date": "", "due_date": "",
            "notes": b["notes"] if "notes" in b.keys() else "",
            "parent_task_id": "",
            "updated_at": (b["updated_at"] if "updated_at" in b.keys() and b["updated_at"] else
                            (b["resolved_at"] if b["resolved_at"] else None) or b["created_at"] or ""),
        }

    remote_records, remote_complete = list_records(feishu_table_id)
    if remote_complete:
        remote_records = _dedupe_remote_records(remote_records, feishu_table_id, label=f"proj:{project_id[:8]}")
    remote_by_kid = {}
    remote_new = []
    record_id_to_kid = {}
    for rec in remote_records:
        kid = _text(rec.get("fields", {}).get("kanban_id", ""))
        if kid:
            remote_by_kid[kid] = rec
            record_id_to_kid[rec["record_id"]] = kid
        else:
            remote_new.append(rec)

    pushed, pulled, created_remote, created_local, deleted_remote = 0, 0, 0, 0, 0

    for kid, local in local_items.items():
        ff = {
            "Title": local["title"], "Workstream": local["workstream"],
            "Type": local["type"], "Status": local["status"],
            "Priority": local["priority"],
            "Notes": local["notes"],
            "kanban_id": kid, "updated_at": local["updated_at"],
        }
        sd_ms = _date_to_ms(local["start_date"])
        if sd_ms:
            ff["Start Date"] = sd_ms
        dd_ms = _date_to_ms(local["due_date"])
        if dd_ms:
            ff["Due Date"] = dd_ms
        # Person field (Executor Feishu) — single source of truth for assignee
        assignee_key = local["assignee"].lstrip("@").lower() if local["assignee"] else ""
        if assignee_key:
            if assignee_key in user_open_id_map:
                ff["Executor (Feishu)"] = [{"id": user_open_id_map[assignee_key]}]
            else:
                print(f"[sync] WARNING: assignee '{local['assignee']}' has no feishu_open_id — "
                      f"task '{local['title'][:40]}' will have no executor on Bitable")

        if kid in remote_by_kid:
            remote = remote_by_kid[kid]
            rf = remote.get("fields", {})
            remote_ts = _text(rf.get("updated_at", ""))
            last_sync = last_sync_ts.get(kid, "")

            # Resolve remote assignee from Executor (Feishu) person field.
            # For blockers, Feishu Person field may have multiple users — we take the first.
            _rpname2, _rpoid2 = _extract_person_field(rf.get("Executor (Feishu)"))
            remote_assignee = _rpname2 or ""
            # Normalize: if remote person field is empty AND local assignee
            # has no feishu_open_id (e.g. bot agent), treat as match.
            if not remote_assignee and local["assignee"]:
                if local["assignee"].lstrip("@").lower() not in user_open_id_map:
                    remote_assignee = local["assignee"]
            if local["type"] == "Blocker":
                # Blockers don't use start/due dates — only compare the
                # fields kanban actually persists for a blocker.
                r_status = _text(rf.get("Status", ""))
                remote_vals = {
                    "title_en": _text(rf.get("Title", "")),
                    "status": "done" if r_status == "done" else "blocked",
                    "assignee": remote_assignee,
                    "notes": _text(rf.get("Notes", "")),
                }
                local_vals = {
                    "title_en": local["title"],
                    "status": local["status"],
                    "assignee": local["assignee"],
                    "notes": local["notes"],
                }
            else:
                remote_vals = {
                    "title_en": _text(rf.get("Title", "")),
                    "status": _text(rf.get("Status", "")),
                    "assignee": remote_assignee,
                    "start_date": _ms_to_date(rf.get("Start Date")),
                    "due_date": _ms_to_date(rf.get("Due Date")),
                    "notes": _text(rf.get("Notes", "")),
                }
                local_vals = {
                    "title_en": local["title"],
                    "status": local["status"],
                    "assignee": local["assignee"],
                    "start_date": local["start_date"],
                    "due_date": local["due_date"],
                    "notes": local["notes"],
                }
            # Check native parent hierarchy (父记录)
            native_parent = _extract_native_parent(rf, record_id_to_kid)
            parent_changed = native_parent and native_parent != local.get("parent_task_id", "")

            local_changed = local["updated_at"] > last_sync if last_sync else False
            remote_changed = remote_ts > last_sync if last_sync else False
            vals_differ = remote_vals != local_vals

            if not vals_differ and not parent_changed:
                pass  # In sync
            elif vals_differ and local_changed and remote_changed:
                # Both sides changed since last sync — record conflicts
                etype = "blocker" if local["type"] == "Blocker" else "task"
                _record_conflicts(db, etype, kid, local_vals, remote_vals,
                                  local["updated_at"], remote_ts)
                if parent_changed:
                    db.execute("UPDATE tasks SET parent_task_id=?, updated_at=? WHERE id=?",
                               (native_parent, now_iso(), kid))
                    db.commit()
                print(f"  [sync-proj:{project_id[:8]}] CONFLICT {kid} '{local['title'][:30]}' local_s={local_vals.get('status')} remote_s={remote_vals.get('status')}", flush=True)
            elif vals_differ and local_changed:
                # Only local changed — push to Feishu
                ts = now_iso()
                ff["updated_at"] = ts
                update_record(feishu_table_id, remote["record_id"], ff)
                pushed += 1
                print(f"  [sync-proj:{project_id[:8]}] PUSH {kid} '{local['title'][:30]}' status={local_vals.get('status')} (local_ts={local['updated_at']} remote_ts={remote_ts} last_sync={last_sync})", flush=True)
            elif vals_differ:
                # Values differ but local didn't change — remote must have changed.
                # Manual Feishu UI edits don't bump the sync-managed text updated_at,
                # so trust the observed value difference and pull from Feishu.
                _apply_remote_v2(db, kid, local, rf)
                if parent_changed:
                    db.execute("UPDATE tasks SET parent_task_id=?, updated_at=? WHERE id=?",
                               (native_parent, now_iso(), kid))
                    db.commit()
                update_record(feishu_table_id, remote["record_id"], {"updated_at": now_iso()})
                pulled += 1
                print(f"  [sync-proj:{project_id[:8]}] PULL {kid} '{local['title'][:30]}' local_s={local_vals.get('status')} remote_s={remote_vals.get('status')} (remote_changed={remote_changed} remote_ts={remote_ts} last_sync={last_sync})", flush=True)
            elif parent_changed:
                # Values match but parent hierarchy changed — apply parent only
                db.execute("UPDATE tasks SET parent_task_id=?, updated_at=? WHERE id=?",
                           (native_parent, now_iso(), kid))
                db.commit()

            last_sync_ts[kid] = now_iso()
        else:
            # Not found in remote — could be Feishu deletion or incomplete read
            prev_key = f"synced_kids_{project_id}"
            prev_synced = set(_state.get(prev_key, []))
            if kid in prev_synced:
                if remote_complete:
                    table = "blockers" if local["type"] == "Blocker" else "tasks"
                    db.execute(f"UPDATE {table} SET deleted_at=? WHERE id=? AND deleted_at IS NULL",
                               (now_iso(), kid))
                    print(f"  [feishu-del] per-project '{local['title'][:40]}' -> soft-deleted locally", flush=True)
                    deleted_remote += 1
                # else: incomplete read — skip, do not treat as deletion
            else:
                new_rid = create_record(feishu_table_id, ff)
                if new_rid:
                    created_remote += 1
                    remote_by_kid[kid] = {"record_id": new_rid, "fields": ff}
                    record_id_to_kid[new_rid] = kid

    for kid, remote in remote_by_kid.items():
        if kid in local_items:
            continue
        was_deleted = (
            db.execute("SELECT id FROM tasks WHERE id=? AND deleted_at IS NOT NULL", (kid,)).fetchone()
            or db.execute("SELECT id FROM blockers WHERE id=? AND deleted_at IS NOT NULL", (kid,)).fetchone()
        )
        if was_deleted:
            if remote_complete:
                delete_record(feishu_table_id, remote["record_id"])
                deleted_remote += 1
            continue
        fields = remote.get("fields", {})
        title = _text(fields.get("Title", ""))
        if not title:
            continue
        ws_name = _text(fields.get("Workstream", ""))
        ws_id = ws_name_to_id.get(ws_name, "")
        if not ws_id:
            if ws_name:
                ws_id = _auto_create_workstream(db, project_id, ws_name)
                if not ws_id:
                    continue
                ws_name_to_id[ws_name] = ws_id
            else:
                continue
        item_type = _text(fields.get("Type", "Task"))
        status = _text(fields.get("Status", "todo"))
        # Executor (Feishu) person field is the single source of truth
        pname, poid = _extract_person_field(fields.get("Executor (Feishu)"))
        assignee = ""
        if pname and poid:
            _save_feishu_open_id(db, pname, poid)
            assignee = pname
        # Resolve parent from Feishu native 父记录 hierarchy
        parent_id = _extract_native_parent(fields, record_id_to_kid)
        title_en, title_zh = _split_bilingual(title)
        if item_type == "Blocker":
            desc_en, desc_zh = title_en or title, title_zh
            db.execute(
                "INSERT OR IGNORE INTO blockers (id, workstream_id, description_en, description_zh, "
                "assignee, notes, resolved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, desc_en, desc_zh, assignee,
                 _text(fields.get("Notes", "")),
                 1 if status == "done" else 0, now_iso())
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO tasks (id, workstream_id, title_en, title_zh, assignee, status, "
                "start_date, due_date, notes, parent_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, title_en or title, title_zh, assignee, status or "todo",
                 _ms_to_date(fields.get("Start Date")) or None,
                 _ms_to_date(fields.get("Due Date")) or None, _text(fields.get("Notes", "")),
                 parent_id or None, now_iso())
            )
        created_local += 1

    for rec in remote_new:
        fields = rec.get("fields", {})
        title = _text(fields.get("Title", ""))
        if not title:
            continue
        ws_name = _text(fields.get("Workstream", ""))
        ws_id = ws_name_to_id.get(ws_name, "")
        if not ws_id:
            if ws_name:
                ws_id = _auto_create_workstream(db, project_id, ws_name)
                if not ws_id:
                    continue
                ws_name_to_id[ws_name] = ws_id
            else:
                continue
        item_type = _text(fields.get("Type", "Task"))
        status = _text(fields.get("Status", "todo"))
        kid = uuid.uuid4().hex[:8]
        # Executor (Feishu) person field is the single source of truth
        pname, poid = _extract_person_field(fields.get("Executor (Feishu)"))
        assignee = ""
        if pname and poid:
            _save_feishu_open_id(db, pname, poid)
            assignee = pname
        # Resolve parent from Feishu native 父记录 hierarchy
        parent_id = _extract_native_parent(fields, record_id_to_kid)
        title_en, title_zh = _split_bilingual(title)
        if item_type == "Blocker":
            desc_en, desc_zh = title_en or title, title_zh
            db.execute(
                "INSERT OR IGNORE INTO blockers (id, workstream_id, description_en, description_zh, "
                "assignee, notes, resolved, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, desc_en, desc_zh, assignee,
                 _text(fields.get("Notes", "")),
                 1 if status == "done" else 0, now_iso())
            )
        else:
            db.execute(
                "INSERT OR IGNORE INTO tasks (id, workstream_id, title_en, title_zh, assignee, status, "
                "start_date, due_date, notes, parent_task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (kid, ws_id, title_en or title, title_zh, assignee, status or "todo",
                 _ms_to_date(fields.get("Start Date")) or None,
                 _ms_to_date(fields.get("Due Date")) or None, _text(fields.get("Notes", "")),
                 parent_id or None, now_iso())
            )
        update_record(feishu_table_id, rec["record_id"], {"kanban_id": kid, "updated_at": now_iso()})
        created_local += 1

    # ── Push parent hierarchy to Feishu native 父记录 field ──
    kid_to_rid = {kid: rec["record_id"] for kid, rec in remote_by_kid.items()}
    state_key = f"pushed_parents_{project_id}"
    pushed_parents = _state.get(state_key, {})
    parents_changed = False
    for kid, local in local_items.items():
        parent_kid = local.get("parent_task_id")
        if not parent_kid or local["type"] == "Blocker":
            continue
        child_rid = kid_to_rid.get(kid)
        parent_rid = kid_to_rid.get(parent_kid)
        if not child_rid or not parent_rid:
            continue
        # Check if already pushed this exact parent
        if pushed_parents.get(kid) == parent_kid:
            continue
        if kid in remote_by_kid:
            rf = remote_by_kid[kid].get("fields", {})
            existing_parent = _extract_native_parent(rf, record_id_to_kid)
            if existing_parent == parent_kid:
                pushed_parents[kid] = parent_kid
                parents_changed = True
                continue
        try:
            update_record(feishu_table_id, child_rid,
                          {"\u7236\u8bb0\u5f55": {"record_ids": [parent_rid]}})
            pushed_parents[kid] = parent_kid
            parents_changed = True
            print(f"  [parent] project: set {kid} -> {parent_kid}", flush=True)
        except Exception as e:
            print(f"  [parent] project err: {kid} -> {parent_kid}: {e}", flush=True)
    if parents_changed:
        _state[state_key] = pushed_parents
        save_state()

    # Clean up soft-deletes — only push deletions to Feishu with complete read
    if remote_complete:
        for table in ("tasks", "blockers"):
            deleted = db.execute(f"SELECT id FROM {table} WHERE deleted_at IS NOT NULL").fetchall()
            for row in deleted:
                if row["id"] in remote_by_kid:
                    delete_record(feishu_table_id, remote_by_kid[row["id"]]["record_id"])
                    deleted_remote += 1

    # Save synced kanban_ids only from complete reads to avoid poisoning state
    if remote_complete:
        _state[f"synced_kids_{project_id}"] = list(remote_by_kid.keys())
    _state[f"last_sync_ts_{project_id}"] = last_sync_ts
    save_state()

    db.commit()
    return {"pushed": pushed, "pulled": pulled, "created_remote": created_remote,
            "created_local": created_local, "deleted_remote": deleted_remote}


# ══════════════════════════════════════════════════════════════════════════
# Main sync cycle
# ══════════════════════════════════════════════════════════════════════════

def sync_once():
    db = get_db()
    try:
        ts = datetime.now().strftime("%H:%M:%S")
        all_stats = []

        proj_stats, proj_record_map = sync_projects_v2(db)
        if sum(proj_stats.values()) > 0:
            parts = [f"{v} {k}" for k, v in proj_stats.items() if v]
            all_stats.append(f"Projects: {', '.join(parts)}")

        # Sync members before tasks so we have the name->record_id map for Executor DuplexLink
        member_record_map = sync_members_v2(db)

        task_stats = sync_tasks_v2(db, proj_record_map, member_record_map)
        ops = sum(task_stats.values())
        if ops > 0:
            parts = []
            if task_stats["pushed"]: parts.append(f"{task_stats['pushed']} pushed")
            if task_stats["pulled"]: parts.append(f"{task_stats['pulled']} pulled")
            if task_stats["created_remote"]: parts.append(f"{task_stats['created_remote']} new->feishu")
            if task_stats["created_local"]: parts.append(f"{task_stats['created_local']} new->local")
            if task_stats["deleted_remote"]: parts.append(f"{task_stats['deleted_remote']} del->feishu")
            all_stats.append(f"Tasks: {', '.join(parts)}")

        sync_bugs_v2(db, proj_record_map)
        sync_bugs_v2(db, proj_record_map, table_key="rd_bugs_table",
                     source_filter="agent", state_suffix="_rd")

        # Per-project table sync (bi-directional)
        project_tables = _state.get("project_tables", {})
        for pid, feishu_tid in project_tables.items():
            stats = sync_project_items(db, pid, feishu_tid)
            ops = sum(stats.values())
            if ops > 0:
                parts = []
                if stats["pushed"]: parts.append(f"{stats['pushed']} pushed")
                if stats["pulled"]: parts.append(f"{stats['pulled']} pulled")
                if stats["created_remote"]: parts.append(f"{stats['created_remote']} new->feishu")
                if stats["created_local"]: parts.append(f"{stats['created_local']} new->local")
                if stats["deleted_remote"]: parts.append(f"{stats['deleted_remote']} del->feishu")
                row = db.execute("SELECT name_en FROM projects WHERE id=?", (pid,)).fetchone()
                pname = row["name_en"] if row else pid
                all_stats.append(f"{pname}: {', '.join(parts)}")

        # Check recurring tasks (creates task instances when due)
        try:
            req = urllib.request.Request("http://127.0.0.1:8666/api/recurring-tasks/check",
                                         data=b"", method="POST",
                                         headers={"Content-Type": "application/json",
                                                  "X-Kanban-User": "system"})
            resp = urllib.request.urlopen(req, timeout=5)
            result = json.loads(resp.read())
            if result.get("created"):
                print(f"  [recurring] created {len(result['created'])} tasks", flush=True)
        except Exception as e:
            print(f"  [recurring] error: {e}", flush=True)
    finally:
        db.close()

    if all_stats:
        print(f"[{ts}] Sync: {'; '.join(all_stats)}", flush=True)
    else:
        print(f"[{ts}] Sync: no changes", flush=True)


REQUIRED_STATUS_OPTIONS = ["todo", "doing", "in_review", "done", "blocked", "abandoned"]

# Both bugs_table and rd_bugs_table use the same Feishu-native Status options
# so QA sees an identical Status filter across both tables. The sync's
# STATUS_TO_FEISHU mapping pushes Feishu-native names regardless.
REQUIRED_BUG_STATUS_OPTIONS = [
    "To Do", "In Progress", "Fix Complete", "To Verify", "Done",
]


def _ensure_bug_status_options():
    """Patch the Status field on both bugs_table and rd_bugs_table so their
    options include every Feishu-native value the kanban will push. Idempotent.
    Does NOT remove existing extra options (for safety) — only adds missing ones."""
    app_token = bt()
    targets = []
    if _state.get("bugs_table"):
        targets.append(("bugs_table", _state["bugs_table"], REQUIRED_BUG_STATUS_OPTIONS))
    if _state.get("rd_bugs_table"):
        targets.append(("rd_bugs_table", _state["rd_bugs_table"], REQUIRED_BUG_STATUS_OPTIONS))
    for label, table_id, required in targets:
        try:
            resp = feishu_api(f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
            if resp.get("code") != 0:
                print(f"  [bug-status-options] {label}: fields fetch failed code={resp.get('code')}", flush=True)
                continue
            for field in resp.get("data", {}).get("items", []):
                if field.get("field_name") != "Status":
                    continue
                options = field.get("property", {}).get("options", []) or []
                existing_names = {o.get("name") for o in options}
                missing = [s for s in required if s not in existing_names]
                if not missing:
                    break
                for s in missing:
                    options.append({"name": s})
                resp2 = feishu_api(
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field['field_id']}",
                    method="PUT",
                    data={"field_name": "Status", "type": 3,
                          "property": {"options": options}},
                )
                if resp2.get("code") == 0:
                    print(f"  [bug-status-options] {label}: added {missing}", flush=True)
                else:
                    print(f"  [bug-status-options] {label}: PUT failed code={resp2.get('code')} msg={resp2.get('msg','')[:200]}", flush=True)
                break
        except Exception as e:
            print(f"  [bug-status-options] {label}: error {e}", flush=True)


def _ensure_status_options():
    """Patch all Bitable tables (central Tasks + per-project tables) so their Status
    field includes every option in REQUIRED_STATUS_OPTIONS. Idempotent: only writes
    when an option is missing. Runs every startup so newly added statuses propagate."""
    app_token = bt()
    targets = []
    if _state.get("tasks_table"):
        targets.append(("central Tasks", _state["tasks_table"]))
    for project_id, table_id in _state.get("project_tables", {}).items():
        targets.append((f"project {project_id}", table_id))
    if not targets:
        return
    for label, table_id in targets:
        try:
            resp = feishu_api(f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields")
            if resp.get("code") != 0:
                # 1254041 = TableIdNotFound — skip stale per-project entries quietly
                if resp.get("code") != 1254041:
                    print(f"  [status-options] {label}: fields fetch failed code={resp.get('code')}", flush=True)
                continue
            for field in resp.get("data", {}).get("items", []):
                if field.get("field_name") != "Status":
                    continue
                options = field.get("property", {}).get("options", []) or []
                existing_names = {o.get("name") for o in options}
                missing = [s for s in REQUIRED_STATUS_OPTIONS if s not in existing_names]
                if not missing:
                    break
                for s in missing:
                    options.append({"name": s})
                resp2 = feishu_api(
                    f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field['field_id']}",
                    method="PUT",
                    data={"field_name": field.get("field_name", "Status"),
                          "type": 3,
                          "property": {"options": options}},
                )
                if resp2.get("code") == 0:
                    print(f"  [status-options] {label}: added {missing} to Status field", flush=True)
                else:
                    print(f"  [status-options] {label}: PUT failed code={resp2.get('code')} msg={resp2.get('msg','')[:200]}", flush=True)
                break
        except Exception as e:
            print(f"  [status-options] {label}: error {e}", flush=True)


def main():
    if not APP_ID or not APP_SECRET:
        print("Error: FEISHU_APP_ID and FEISHU_APP_SECRET must be set", flush=True)
        sys.exit(1)

    load_state()
    if not bt():
        print("Error: Bitable not set up.", flush=True)
        sys.exit(1)

    print(f"Feishu Sync starting (interval={SYNC_INTERVAL}s)", flush=True)
    print(f"  DB: {DB_PATH}", flush=True)
    print(f"  Bitable: {bt()}", flush=True)
    print(f"  Projects table: {_state.get('projects_table')}", flush=True)
    print(f"  Tasks table: {_state.get('tasks_table')}", flush=True)
    print(f"  Members table: {_state.get('members_table')}", flush=True)
    print(f"  RD Bugs table: {_state.get('rd_bugs_table', '(not set)')}", flush=True)
    pt = _state.get("project_tables", {})
    if pt:
        print(f"  Per-project tables: {len(pt)}", flush=True)

    _ensure_status_options()
    _ensure_bug_status_options()

    print("Running initial sync...", flush=True)
    try:
        sync_once()
    except Exception as e:
        import traceback
        print(f"Initial sync error: {e}", flush=True)
        traceback.print_exc()

    print(f"Entering sync loop (every {SYNC_INTERVAL}s)...", flush=True)
    while True:
        time.sleep(SYNC_INTERVAL)
        try:
            sync_once()
        except Exception as e:
            import traceback
            print(f"Sync error: {e}", flush=True)
            traceback.print_exc()


if __name__ == "__main__":
    main()

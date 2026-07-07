#!/usr/bin/env python3
"""
Feishu Bitable Migration — restructures the kanban Bitable layout.

Migrates from per-project tables to a centralized model inspired by
Feishu's project management template:

  Old layout:
    - Overview table (one row per project with stats)
    - One table per project (flat tasks + blockers)

  New layout:
    - 🚩 Projects table (with computed fields, DuplexLink to Tasks)
    - ✅ Tasks table (centralized, with kanban/Gantt/calendar views)
    - 🧑🏻‍💻 Members table (with Feishu User field, DuplexLink to Tasks)
    - 📝 Weekly Reports table (with form view)

Usage:
    python feishu_migrate.py --profile team           # run migration
    python feishu_migrate.py --profile team --dry-run  # preview only
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────
def load_dotenv(path):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_profile = "default"
for i, arg in enumerate(sys.argv):
    if arg == "--profile" and i + 1 < len(sys.argv):
        _profile = sys.argv[i + 1]

DRY_RUN = "--dry-run" in sys.argv
CLEANUP_LEGACY = "--cleanup-legacy" in sys.argv
RESTORE_PROJECTS = "--restore-projects" in sys.argv
ADD_PERSON_FIELD = "--add-person-field" in sys.argv
ADD_SUBTASK_FIELDS = "--add-subtask-fields" in sys.argv
HIDE_INTERNAL_FIELDS = "--hide-internal-fields" in sys.argv

_base = Path(__file__).parent
if _profile != "default":
    load_dotenv(_base / f".env.{_profile}")
load_dotenv(_base / ".env")

APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
DATA_DIR = Path(os.environ.get("KANBAN_DATA_DIR", _base / "data"))
STATE_FILE = (DATA_DIR / f"feishu_sync_state_{_profile}.json"
              if _profile != "default"
              else DATA_DIR / "feishu_sync_state.json")

# ── HTTP / Auth ───────────────────────────────────────────────────────────
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
_token_cache = {"token": "", "expires_at": 0}


def _request(url, method="GET", data=None, headers=None):
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with _opener.open(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        print(f"  HTTP {e.code}: {err_body[:500]}", flush=True)
        return {"code": e.code, "msg": err_body[:300]}


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


# ── Bitable helpers ───────────────────────────────────────────────────────
def list_tables(app_token):
    resp = feishu_api(f"/bitable/v1/apps/{app_token}/tables?page_size=100")
    return resp.get("data", {}).get("items", [])


def create_table(app_token, name):
    resp = feishu_api(f"/bitable/v1/apps/{app_token}/tables",
                      method="POST", data={"table": {"name": name}})
    if resp.get("code") != 0:
        print(f"  ERROR creating table '{name}': {resp}", flush=True)
        return None
    tid = resp.get("data", {}).get("table_id")
    print(f"  Created table '{name}' -> {tid}", flush=True)
    return tid


def delete_table(app_token, table_id):
    resp = feishu_api(f"/bitable/v1/apps/{app_token}/tables/{table_id}",
                      method="DELETE")
    if resp.get("code") != 0:
        print(f"  ERROR deleting table {table_id}: {resp}", flush=True)
        return False
    print(f"  Deleted table {table_id}", flush=True)
    return True


def update_field(app_token, table_id, field_id, field_name, field_type=1):
    """Rename an existing field."""
    resp = feishu_api(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
        method="PUT", data={"field_name": field_name, "type": field_type})
    if resp.get("code") != 0:
        print(f"  ERROR renaming field to '{field_name}': {resp}", flush=True)
        return False
    print(f"    Renamed field {field_id} -> '{field_name}'", flush=True)
    return True


def delete_field(app_token, table_id, field_id):
    """Delete a field from a table."""
    resp = feishu_api(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields/{field_id}",
        method="DELETE")
    if resp.get("code") != 0:
        print(f"  ERROR deleting field {field_id}: {resp}", flush=True)
        return False
    print(f"    Deleted field {field_id}", flush=True)
    return True


def list_fields(app_token, table_id):
    resp = feishu_api(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields?page_size=100")
    return resp.get("data", {}).get("items", [])


def create_field(app_token, table_id, field_name, field_type, prop=None):
    data = {"field_name": field_name, "type": field_type}
    if prop:
        data["property"] = prop
    resp = feishu_api(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
        method="POST", data=data)
    if resp.get("code") != 0:
        print(f"  ERROR creating field '{field_name}': {resp}", flush=True)
        return None
    fid = resp.get("data", {}).get("field", {}).get("field_id")
    print(f"    Field '{field_name}' (type {field_type}) -> {fid}", flush=True)
    return fid


def list_views(app_token, table_id):
    resp = feishu_api(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/views?page_size=100")
    return resp.get("data", {}).get("items", [])


def create_view(app_token, table_id, view_name, view_type):
    resp = feishu_api(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/views",
        method="POST", data={"view_name": view_name, "view_type": view_type})
    if resp.get("code") != 0:
        print(f"  ERROR creating view '{view_name}': {resp}", flush=True)
        return None
    vid = resp.get("data", {}).get("view", {}).get("view_id")
    print(f"    View '{view_name}' ({view_type}) -> {vid}", flush=True)
    return vid


def list_records(app_token, table_id):
    records = []
    page_token = ""
    while True:
        url = f"/bitable/v1/apps/{app_token}/tables/{table_id}/records?page_size=100"
        if page_token:
            url += f"&page_token={page_token}"
        resp = feishu_api(url)
        if resp.get("code") != 0:
            break
        items = resp.get("data", {}).get("items", [])
        records.extend(items)
        if not resp.get("data", {}).get("has_more"):
            break
        page_token = resp["data"].get("page_token", "")
    return records


def create_record(app_token, table_id, fields):
    resp = feishu_api(
        f"/bitable/v1/apps/{app_token}/tables/{table_id}/records",
        method="POST", data={"fields": fields})
    if resp.get("code") == 0:
        return resp.get("data", {}).get("record", {}).get("record_id")
    return None


def _date_to_ms(date_str):
    """Convert date string to epoch ms for Feishu DateTime fields."""
    if not date_str:
        return None
    from datetime import datetime as dt
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
        try:
            return int(dt.strptime(date_str, fmt).timestamp() * 1000)
        except ValueError:
            continue
    return None


def _text(val):
    if val is None:
        return ""
    if isinstance(val, str):
        return val
    if isinstance(val, (int, float)):
        return str(int(val)) if isinstance(val, float) and val == int(val) else str(val)
    if isinstance(val, list):
        return "".join(
            seg.get("text", str(seg)) if isinstance(seg, dict) else str(seg)
            for seg in val)
    return str(val)


# ── Migration ─────────────────────────────────────────────────────────────
class Migration:
    def __init__(self, app_token, state):
        self.app_token = app_token
        self.state = state
        self.new_state = deepcopy(state)
        self.existing_tables = {}  # name -> table_id

    def find_or_create_table(self, name):
        """Find existing table by name, or create it."""
        if name in self.existing_tables:
            tid = self.existing_tables[name]
            print(f"  Table '{name}' already exists -> {tid}", flush=True)
            return tid
        if DRY_RUN:
            print(f"  [DRY RUN] Would create table '{name}'", flush=True)
            return f"dry-run-{name}"
        return create_table(self.app_token, name)

    def ensure_fields(self, table_id, desired_fields):
        """Create fields that don't already exist on a table.
        desired_fields: list of (name, type, property_or_None)
        Returns dict of field_name -> field_id.
        """
        if DRY_RUN:
            for name, ftype, _ in desired_fields:
                print(f"    [DRY RUN] Would create field '{name}' (type {ftype})",
                      flush=True)
            return {}

        existing = list_fields(self.app_token, table_id)
        existing_names = {f["field_name"]: f["field_id"] for f in existing}
        result = dict(existing_names)

        for name, ftype, prop in desired_fields:
            if name in existing_names:
                print(f"    Field '{name}' already exists", flush=True)
                continue
            fid = create_field(self.app_token, table_id, name, ftype, prop)
            if fid:
                result[name] = fid
        return result

    def ensure_views(self, table_id, desired_views):
        """Create views that don't already exist.
        desired_views: list of (name, type_string)
        """
        if DRY_RUN:
            for name, vtype in desired_views:
                print(f"    [DRY RUN] Would create view '{name}' ({vtype})",
                      flush=True)
            return

        existing = list_views(self.app_token, table_id)
        existing_names = {v["view_name"] for v in existing}

        for name, vtype in desired_views:
            if name in existing_names:
                print(f"    View '{name}' already exists", flush=True)
                continue
            create_view(self.app_token, table_id, name, vtype)

    def run(self):
        at = self.app_token
        print(f"\n{'='*60}", flush=True)
        print(f"Feishu Bitable Migration", flush=True)
        print(f"  Bitable: {at}", flush=True)
        print(f"  Profile: {_profile}", flush=True)
        print(f"  Dry run: {DRY_RUN}", flush=True)
        print(f"{'='*60}\n", flush=True)

        # Discover existing tables
        tables = list_tables(at)
        self.existing_tables = {t["name"]: t["table_id"] for t in tables}
        print(f"Existing tables: {list(self.existing_tables.keys())}\n", flush=True)

        # ── Step 1: Create tables ─────────────────────────────────────
        print("Step 1: Create/find tables...", flush=True)
        projects_tid = self.find_or_create_table("🚩 Projects")
        tasks_tid = self.find_or_create_table("✅ Tasks")
        members_tid = self.find_or_create_table("🧑🏻‍💻 Members")
        reports_tid = self.find_or_create_table("📝 Weekly Reports")
        bugs_tid = self.find_or_create_table("🐛 Bugs")

        # ── Step 2: Create fields ─────────────────────────────────────
        print("\nStep 2: Create fields...", flush=True)

        # Projects table fields
        print(f"\n  Projects table ({projects_tid}):", flush=True)
        proj_fields = self.ensure_fields(projects_tid, [
            ("Project", 1, None),          # Text — primary
            ("Description", 1, None),      # Text
            ("Status", 3, {"options": [    # SingleSelect
                {"name": "planned"}, {"name": "in-progress"},
                {"name": "blocked"}, {"name": "review"},
                {"name": "done"}, {"name": "stable"},
            ]}),
            ("Color", 1, None),            # Text
            ("kanban_id", 1, None),        # Text — sync key
            ("updated_at", 1, None),       # Text — sync timestamp
        ])

        # Tasks table fields
        print(f"\n  Tasks table ({tasks_tid}):", flush=True)
        task_fields = self.ensure_fields(tasks_tid, [
            ("Title", 1, None),            # Text — primary
            ("Type", 3, {"options": [      # SingleSelect
                {"name": "Task"}, {"name": "Blocker"},
            ]}),
            ("Workstream", 1, None),       # Text
            ("Status", 3, {"options": [    # SingleSelect
                {"name": "todo"}, {"name": "doing"},
                {"name": "done"}, {"name": "blocked"},
            ]}),
            ("Priority", 3, {"options": [  # SingleSelect
                {"name": "critical"}, {"name": "high"},
                {"name": "medium"}, {"name": "low"},
            ]}),
            ("Assignee", 1, None),         # Text — sync-compatible
            ("Start Date", 5, {"date_formatter": "yyyy/MM/dd"}),  # DateTime
            ("Due Date", 5, {"date_formatter": "yyyy/MM/dd"}),    # DateTime
            ("Notes", 1, None),            # Text
            ("kanban_id", 1, None),        # Text — sync key
            ("updated_at", 1, None),       # Text — sync timestamp
        ])

        # Members table fields
        print(f"\n  Members table ({members_tid}):", flush=True)
        member_fields = self.ensure_fields(members_tid, [
            ("Name", 1, None),             # Text — primary
            ("Department", 3, {"options": [  # SingleSelect
                {"name": "Engineering"}, {"name": "Product"},
                {"name": "Design"}, {"name": "Operations"},
            ]}),
            ("kanban_id", 1, None),        # Text — sync key
        ])

        # Weekly Reports table fields
        print(f"\n  Reports table ({reports_tid}):", flush=True)
        report_fields = self.ensure_fields(reports_tid, [
            ("Title", 1, None),            # Text — primary
            ("Date", 5, {"date_formatter": "yyyy/MM/dd"}),  # DateTime
            ("Reporter", 1, None),         # Text (could be User type but text for simplicity)
            ("Content", 1, None),          # Text
        ])

        # Bugs table fields
        print(f"\n  Bugs table ({bugs_tid}):", flush=True)
        bug_fields = self.ensure_fields(bugs_tid, [
            ("Title", 1, None),            # Text — primary
            ("Description", 1, None),      # Text
            ("Severity", 3, {"options": [  # SingleSelect
                {"name": "critical"}, {"name": "high"},
                {"name": "medium"}, {"name": "low"},
            ]}),
            ("Status", 3, {"options": [    # SingleSelect — Feishu-native names
                {"name": "To Do"}, {"name": "In Progress"},
                {"name": "Fix Complete"},
                {"name": "To Verify"}, {"name": "Done"},
            ]}),
            ("Reporter", 1, None),         # Text
            ("Assignee", 1, None),         # Text
            ("Environment", 1, None),      # Text
            ("Steps to Reproduce", 1, None),  # Text
            ("修复方法", 1, None),           # Text — fix method
            ("修复版本", 1, None),           # Text — fix version
            ("修复日期", 5, {"date_formatter": "yyyy/MM/dd"}),  # Date — fix date
            ("kanban_id", 1, None),        # Text — sync key
            ("updated_at", 1, None),       # Text — sync timestamp
        ])

        # ── Step 3: Create DuplexLinks ────────────────────────────────
        print("\nStep 3: Create cross-table links...", flush=True)

        if not DRY_RUN:
            # Projects <-> Tasks
            self.ensure_fields(tasks_tid, [
                ("Project", 21, {
                    "table_id": projects_tid,
                    "back_field_name": "Tasks",
                }),
            ])

            # Tasks <-> Members (executor)
            self.ensure_fields(tasks_tid, [
                ("Executor", 21, {
                    "table_id": members_tid,
                    "back_field_name": "Assigned Tasks",
                }),
            ])

            # Projects -> Weekly Reports (single link)
            self.ensure_fields(projects_tid, [
                ("Weekly Reports", 21, {
                    "table_id": reports_tid,
                    "back_field_name": "Project",
                }),
            ])

            # Bugs <-> Projects
            self.ensure_fields(bugs_tid, [
                ("Project", 21, {
                    "table_id": projects_tid,
                    "back_field_name": "Bugs",
                }),
            ])

            # Bugs <-> Tasks
            self.ensure_fields(bugs_tid, [
                ("Related Task", 21, {
                    "table_id": tasks_tid,
                    "back_field_name": "Bugs",
                }),
            ])
        else:
            print("  [DRY RUN] Would create DuplexLinks:", flush=True)
            print("    Tasks.Project <-> Projects.Tasks", flush=True)
            print("    Tasks.Executor <-> Members.Assigned Tasks", flush=True)
            print("    Projects.Weekly Reports <-> Reports.Project", flush=True)
            print("    Bugs.Project <-> Projects.Bugs", flush=True)
            print("    Bugs.Related Task <-> Tasks.Bugs", flush=True)

        # ── Step 4: Add computed fields to Projects ───────────────────
        print("\nStep 4: Computed fields on Projects...", flush=True)
        if not DRY_RUN and "Tasks" in (proj_fields or {}):
            # Lookup: count of linked tasks
            self.ensure_fields(projects_tid, [
                ("Task Count", 19, {
                    "back_field_id_of_lookup_field": proj_fields.get("Tasks"),
                    "lookup_field_id_to_reference": task_fields.get("Title"),
                    "value_type": "count",
                }),
            ])
            # Note: Formula for completion % — may need manual setup
            # as formula syntax depends on exact field IDs
            print("  Note: 'Completion %' formula may need manual config in Feishu",
                  flush=True)
        else:
            print("  [DRY RUN or skipped] Computed fields require DuplexLinks first",
                  flush=True)

        # ── Step 5: Create views ──────────────────────────────────────
        print("\nStep 5: Create views...", flush=True)

        print(f"\n  Tasks views:", flush=True)
        self.ensure_views(tasks_tid, [
            ("📋 All Tasks", "grid"),
            ("🔄 Status Board", "kanban"),
            ("📅 Gantt Chart", "gantt"),
            ("🗓 Calendar", "grid"),      # calendar type may not be API-creatable
        ])

        print(f"\n  Projects views:", flush=True)
        self.ensure_views(projects_tid, [
            ("📋 All Projects", "grid"),
            ("🔄 By Status", "kanban"),
        ])

        print(f"\n  Members views:", flush=True)
        self.ensure_views(members_tid, [
            ("👥 All Members", "grid"),
            ("🖼 Gallery", "gallery"),
        ])

        print(f"\n  Reports views:", flush=True)
        self.ensure_views(reports_tid, [
            ("📋 All Reports", "grid"),
            ("📝 Submit Report", "form"),
            ("📅 By Week", "grid"),
        ])

        print(f"\n  Bugs views:", flush=True)
        self.ensure_views(bugs_tid, [
            ("📋 All Bugs", "grid"),
            ("🔄 By Severity", "kanban"),
            ("📝 Report Bug", "form"),
        ])

        # ── Step 6: Also add views to legacy per-project tables ───────
        legacy_tables = self.state.get("project_tables", {})
        if legacy_tables:
            print(f"\nStep 6: Add views to {len(legacy_tables)} legacy project table(s)...",
                  flush=True)
            for pid, ftid in legacy_tables.items():
                # First ensure Start Date field exists
                self.ensure_fields(ftid, [
                    ("Start Date", 5, {"date_formatter": "yyyy/MM/dd"}),
                ])
                self.ensure_views(ftid, [
                    ("🔄 Status Board", "kanban"),
                    ("📅 Gantt Chart", "gantt"),
                ])

        # ── Step 7: Migrate data from legacy tables ───────────────────
        if not DRY_RUN and legacy_tables:
            print(f"\nStep 7: Migrate data from legacy tables...", flush=True)
            self._migrate_data(projects_tid, tasks_tid)
        else:
            print(f"\nStep 7: [DRY RUN or no legacy] Skipping data migration",
                  flush=True)

        # ── Step 8: Update state file ─────────────────────────────────
        print("\nStep 8: Update state file...", flush=True)
        self.new_state["projects_table"] = projects_tid
        self.new_state["tasks_table"] = tasks_tid
        self.new_state["members_table"] = members_tid
        self.new_state["reports_table"] = reports_tid
        self.new_state["bugs_table"] = bugs_tid
        # Keep legacy tables for reference
        self.new_state["legacy_overview_table"] = self.state.get("overview_table")
        self.new_state["legacy_project_tables"] = self.state.get("project_tables", {})

        if not DRY_RUN:
            backup_path = STATE_FILE.with_suffix(".json.bak")
            if STATE_FILE.exists():
                backup_path.write_text(STATE_FILE.read_text())
                print(f"  Backed up state to {backup_path}", flush=True)
            STATE_FILE.write_text(json.dumps(self.new_state, indent=2))
            print(f"  Saved new state to {STATE_FILE}", flush=True)
        else:
            print(f"  [DRY RUN] Would save state:", flush=True)
            print(json.dumps(self.new_state, indent=2), flush=True)

        print(f"\n{'='*60}", flush=True)
        print(f"Migration {'preview' if DRY_RUN else 'complete'}!", flush=True)
        print(f"{'='*60}\n", flush=True)

    def _migrate_data(self, projects_tid, tasks_tid):
        """Migrate records from legacy Overview + per-project tables."""
        at = self.app_token
        overview_tid = self.state.get("overview_table")
        project_tables = self.state.get("project_tables", {})

        # Build project kanban_id -> new record_id mapping
        proj_record_map = {}  # kanban_id -> record_id in new Projects table

        # Check if new Projects table already has records
        existing_proj_records = list_records(at, projects_tid)
        for rec in existing_proj_records:
            kid = _text(rec.get("fields", {}).get("kanban_id", ""))
            if kid:
                proj_record_map[kid] = rec["record_id"]

        # Migrate from Overview table
        if overview_tid:
            print(f"  Migrating from Overview table ({overview_tid})...", flush=True)
            overview_records = list_records(at, overview_tid)
            for rec in overview_records:
                f = rec.get("fields", {})
                kid = _text(f.get("kanban_id", ""))
                if not kid or kid in proj_record_map:
                    continue
                new_fields = {
                    "Project": _text(f.get("Project", "")),
                    "Description": _text(f.get("Description", "")),
                    "kanban_id": kid,
                    "updated_at": _text(f.get("updated_at", "")),
                }
                rid = create_record(at, projects_tid, new_fields)
                if rid:
                    proj_record_map[kid] = rid
                    print(f"    Project '{new_fields['Project']}' -> {rid}", flush=True)

        # Check existing tasks in new table
        existing_task_records = list_records(at, tasks_tid)
        existing_task_kids = {
            _text(r.get("fields", {}).get("kanban_id", ""))
            for r in existing_task_records
        }

        # Migrate from per-project tables
        migrated_tasks = 0
        for pid, ftid in project_tables.items():
            print(f"  Migrating tasks from project {pid} ({ftid})...", flush=True)
            records = list_records(at, ftid)
            proj_rid = proj_record_map.get(pid)

            for rec in records:
                f = rec.get("fields", {})
                kid = _text(f.get("kanban_id", ""))
                if not kid or kid in existing_task_kids:
                    continue

                new_fields = {
                    "Title": _text(f.get("Title", "")),
                    "Type": _text(f.get("Type", "Task")),
                    "Workstream": _text(f.get("Workstream", "")),
                    "Status": _text(f.get("Status", "todo")),
                    "Priority": _text(f.get("Priority", "medium")),
                    "Assignee": _text(f.get("Assignee", "")),
                    "Due Date": _text(f.get("Due Date", "")) or None,
                    "Notes": _text(f.get("Notes", "")),
                    "kanban_id": kid,
                    "updated_at": _text(f.get("updated_at", "")),
                }
                # Remove None values
                new_fields = {k: v for k, v in new_fields.items() if v is not None}

                # Set DuplexLink to project
                if proj_rid:
                    new_fields["Project"] = [proj_rid]

                rid = create_record(at, tasks_tid, new_fields)
                if rid:
                    migrated_tasks += 1
                    existing_task_kids.add(kid)

            print(f"    Migrated from this table", flush=True)

        print(f"  Total tasks migrated: {migrated_tasks}", flush=True)


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    if not APP_ID or not APP_SECRET:
        print("Error: FEISHU_APP_ID and FEISHU_APP_SECRET must be set", flush=True)
        sys.exit(1)

    if not STATE_FILE.exists():
        print(f"Error: State file not found: {STATE_FILE}", flush=True)
        print("Run feishu_sync.py first to set up the initial state.", flush=True)
        sys.exit(1)

    state = json.loads(STATE_FILE.read_text())
    app_token = state.get("bitable_app_token", "")
    if not app_token:
        print("Error: No bitable_app_token in state file", flush=True)
        sys.exit(1)

    # Verify auth works
    print("Authenticating...", flush=True)
    get_token()
    print("  OK\n", flush=True)

    if CLEANUP_LEGACY:
        cleanup_legacy(app_token, state)
    elif RESTORE_PROJECTS:
        restore_project_tables(app_token, state)
    elif ADD_PERSON_FIELD:
        add_person_field(app_token, state)
    elif ADD_SUBTASK_FIELDS:
        add_subtask_fields(app_token, state)
    elif HIDE_INTERNAL_FIELDS:
        hide_internal_fields(app_token, state)
    else:
        migration = Migration(app_token, state)
        migration.run()


def cleanup_legacy(app_token, state):
    """Delete legacy v1 tables (Overview + per-project) from Feishu Bitable."""
    print("=" * 60, flush=True)
    print("Cleanup: Removing legacy v1 tables from Feishu Bitable", flush=True)
    print("=" * 60, flush=True)

    overview_tid = state.get("overview_table") or state.get("legacy_overview_table")
    project_tables = state.get("legacy_project_tables") or state.get("project_tables", {})

    tables_to_delete = []
    if overview_tid:
        tables_to_delete.append(("Projects Overview", overview_tid))
    for pid, tid in project_tables.items():
        tables_to_delete.append((f"Project {pid}", tid))

    if not tables_to_delete:
        print("  No legacy tables found in state file.", flush=True)
        return

    print(f"\n  Found {len(tables_to_delete)} legacy table(s) to delete:", flush=True)
    for name, tid in tables_to_delete:
        print(f"    - {name}: {tid}", flush=True)

    if DRY_RUN:
        print("\n  [DRY RUN] Would delete above tables and update state file.", flush=True)
        return

    for name, tid in tables_to_delete:
        print(f"\n  Deleting {name} ({tid})...", flush=True)
        delete_table(app_token, tid)

    # Update state file — remove legacy keys
    for key in ("overview_table", "legacy_overview_table", "project_tables", "legacy_project_tables"):
        state.pop(key, None)

    backup_path = STATE_FILE.with_suffix(".json.bak")
    if STATE_FILE.exists():
        backup_path.write_text(STATE_FILE.read_text())
        print(f"\n  Backed up state to {backup_path}", flush=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"  Updated state file (removed legacy keys)", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"Cleanup complete! Removed {len(tables_to_delete)} legacy table(s).", flush=True)
    print(f"{'='*60}\n", flush=True)


def restore_project_tables(app_token, state):
    """Recreate per-project tables, add fields/views, populate from DB."""
    import sqlite3
    DB_PATH = DATA_DIR / "kanban.db"

    print("=" * 60, flush=True)
    print("Restore: Recreating per-project Feishu Bitable tables", flush=True)
    print("=" * 60, flush=True)

    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row

    projects = db.execute(
        "SELECT id, name_en FROM projects WHERE deleted_at IS NULL ORDER BY sort_order, name_en"
    ).fetchall()
    print(f"\n  Found {len(projects)} project(s) in DB", flush=True)

    project_fields = [
        ("Title", 1, None),
        ("Workstream", 1, None),
        ("Type", 3, {"options": [{"name": "Task"}, {"name": "Blocker"}]}),
        ("Status", 3, {"options": [
            {"name": "todo"}, {"name": "doing"}, {"name": "in_review"}, {"name": "done"}, {"name": "blocked"},
        ]}),
        ("Priority", 3, {"options": [
            {"name": "critical"}, {"name": "high"}, {"name": "medium"}, {"name": "low"},
        ]}),
        ("Assignee", 1, None),
        ("Start Date", 5, {"date_formatter": "yyyy/MM/dd"}),
        ("Due Date", 5, {"date_formatter": "yyyy/MM/dd"}),
        ("Notes", 1, None),
        ("kanban_id", 1, None),
        ("updated_at", 1, None),
    ]

    project_views = [
        ("🔄 Status Board", "kanban"),
        ("📅 Gantt Chart", "gantt"),
    ]

    m = Migration(app_token, state)
    # Load existing tables so we don't recreate if they already exist
    tables = list_tables(app_token)
    m.existing_tables = {t["name"]: t["table_id"] for t in tables}

    new_project_tables = {}

    for p in projects:
        pid, name = p["id"], p["name_en"]
        print(f"\n  Project: {name} ({pid})", flush=True)

        # Create table
        tid = m.find_or_create_table(name)
        if not tid:
            print(f"    ERROR: Could not create table for {name}", flush=True)
            continue
        new_project_tables[pid] = tid

        # Rename default primary field to "Title" (Feishu auto-creates "多行文本")
        existing_fields = list_fields(app_token, tid)
        if existing_fields and existing_fields[0]["field_name"] != "Title":
            update_field(app_token, tid, existing_fields[0]["field_id"], "Title", field_type=1)

        # Add remaining fields (Title already exists as the renamed primary)
        print(f"    Adding fields...", flush=True)
        remaining_fields = [(n, t, p) for n, t, p in project_fields if n != "Title"]
        m.ensure_fields(tid, remaining_fields)

        # Add views
        print(f"    Adding views...", flush=True)
        m.ensure_views(tid, project_views)

        # Populate with tasks + blockers from DB
        ws_rows = db.execute(
            "SELECT id, title_en, priority FROM workstreams WHERE project_id=? AND deleted_at IS NULL",
            (pid,)
        ).fetchall()
        ws_names = {r["id"]: r["title_en"] for r in ws_rows}
        ws_priority = {r["id"]: r["priority"] for r in ws_rows}
        ws_ids = set(ws_names.keys())

        # Check existing records to avoid duplicates
        existing_records = list_records(app_token, tid)
        existing_kids = {
            _text(r.get("fields", {}).get("kanban_id", ""))
            for r in existing_records
        }

        count = 0
        for t in db.execute("SELECT * FROM tasks WHERE deleted_at IS NULL").fetchall():
            if t["workstream_id"] not in ws_ids:
                continue
            if t["id"] in existing_kids:
                continue
            start_date = t["start_date"] if "start_date" in t.keys() else None
            ff = {
                "Title": t["title_en"] or t["title_zh"] or "",
                "Workstream": ws_names.get(t["workstream_id"], ""),
                "Type": "Task",
                "Status": t["status"] or "todo",
                "Priority": ws_priority.get(t["workstream_id"], "medium"),
                "Assignee": t["assignee"] or "",
                "Notes": t["notes"] or "",
                "kanban_id": t["id"],
                "updated_at": t["updated_at"] or t["created_at"] or "",
            }
            sd_ms = _date_to_ms(start_date)
            if sd_ms:
                ff["Start Date"] = sd_ms
            dd_ms = _date_to_ms(t["due_date"])
            if dd_ms:
                ff["Due Date"] = dd_ms
            create_record(app_token, tid, ff)
            count += 1

        for b in db.execute("SELECT * FROM blockers WHERE deleted_at IS NULL").fetchall():
            if b["workstream_id"] not in ws_ids:
                continue
            if b["id"] in existing_kids:
                continue
            ff = {
                "Title": b["description_en"] or b["description_zh"] or "",
                "Workstream": ws_names.get(b["workstream_id"], ""),
                "Type": "Blocker",
                "Status": "done" if b["resolved"] else "blocked",
                "Priority": ws_priority.get(b["workstream_id"], "medium"),
                "Assignee": "",
                "Notes": "",
                "kanban_id": b["id"],
                "updated_at": (b["resolved_at"] or b["created_at"] or ""),
            }
            create_record(app_token, tid, ff)
            count += 1

        print(f"    Populated {count} record(s)", flush=True)

    db.close()

    # Update state file
    state["project_tables"] = new_project_tables
    backup_path = STATE_FILE.with_suffix(".json.bak")
    if STATE_FILE.exists():
        backup_path.write_text(STATE_FILE.read_text())
        print(f"\n  Backed up state to {backup_path}", flush=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"  Updated state file with {len(new_project_tables)} project table(s)", flush=True)

    print(f"\n{'='*60}", flush=True)
    print(f"Restore complete! Created {len(new_project_tables)} project table(s).", flush=True)
    print(f"{'='*60}\n", flush=True)


def add_person_field(app_token, state):
    """Add 'Executor (Feishu)' Person field (type 11) to centralized Tasks table and per-project tables."""
    tables = _collect_task_tables(state)
    _add_field_to_tables(app_token, tables, "Executor (Feishu)", 11, "Person")


def add_subtask_fields(app_token, state):
    """Add 'Parent Task ID' text field to all task tables for subtask hierarchy."""
    tables = _collect_task_tables(state)
    _add_field_to_tables(app_token, tables, "Parent Task ID", 1, "Text")


def _collect_task_tables(state):
    tables = []
    tasks_tid = state.get("tasks_table")
    if tasks_tid:
        tables.append(("Tasks (centralized)", tasks_tid))
    for pid, tid in state.get("project_tables", {}).items():
        tables.append((f"Project {pid}", tid))
    return tables


def _add_field_to_tables(app_token, tables, field_name, field_type, label):
    for tbl_label, tid in tables:
        existing = list_fields(app_token, tid)
        names = [f.get("field_name", "") for f in existing]
        if field_name in names:
            print(f"  {tbl_label}: '{field_name}' already exists, skipping", flush=True)
            continue
        fid = create_field(app_token, tid, field_name, field_type)
        if fid:
            print(f"  {tbl_label}: Added '{field_name}' {label} field -> {fid}", flush=True)
        else:
            print(f"  {tbl_label}: FAILED to add {label} field", flush=True)
    print(f"\nDone! '{field_name}' field added to all task tables.", flush=True)


def hide_internal_fields(app_token, state):
    """Hide kanban_id, updated_at, and Parent Task ID from default grid views in all task tables."""
    hidden_names = {"kanban_id", "updated_at", "Parent Task ID"}
    tables = _collect_task_tables(state)

    # Also include bugs table
    bugs_tid = state.get("bugs_table")
    if bugs_tid:
        tables.append(("Bugs", bugs_tid))

    for tbl_label, tid in tables:
        # Get field IDs for the internal fields
        fields = list_fields(app_token, tid)
        hide_ids = []
        for f in fields:
            if f.get("field_name", "") in hidden_names:
                hide_ids.append(f["field_id"])

        if not hide_ids:
            print(f"  {tbl_label}: No internal fields found to hide", flush=True)
            continue

        # Get all views for this table
        views = list_views(app_token, tid)
        for view in views:
            vid = view.get("view_id", "")
            vname = view.get("view_name", "")
            vtype = view.get("view_type", "")
            # Only modify grid views (type "grid")
            if vtype not in ("grid", ""):
                continue

            # Use the view field visibility API: PATCH view with hidden fields
            # Build field_config to set visible=false for internal fields
            field_config = {}
            for fid in hide_ids:
                field_config[fid] = {"hidden": True}

            resp = feishu_api(
                f"/bitable/v1/apps/{app_token}/tables/{tid}/views/{vid}",
                method="PATCH",
                data={"property": {"field_config": field_config}}
            )
            if resp.get("code") == 0:
                print(f"  {tbl_label} / view '{vname}': Hid {len(hide_ids)} internal field(s)", flush=True)
            else:
                print(f"  {tbl_label} / view '{vname}': ERROR hiding fields: {resp}", flush=True)

    print("\nDone! Internal fields hidden from grid views.", flush=True)


if __name__ == "__main__":
    main()

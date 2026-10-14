"""Regression coverage for the optional Feishu Top Issues sync."""

import importlib.util
import json
from pathlib import Path

import pytest

from db import get_db
from feishu_issues import FIELDS, TABLE_NAME, snapshot, sync_issues, to_fields


@pytest.fixture(autouse=True)
def isolated_issue_database(tmp_path, monkeypatch):
    import db
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "issues.db")
    db.init_db()
    with db.get_db() as conn:
        for name, role in (("test-human", "human"), ("test-bot", "bot")):
            conn.execute("INSERT INTO users (id,name,role) VALUES (?,?,?)", (name, name, role))


class FakeTransport:
    def __init__(self, *, configured=True):
        self._state = {"issues_table": "tbl-issues" if configured else ""}
        self.records = {}
        self.complete = True
        self.fail_writes = 0
        self.read_calls = 0
        self.write_calls = []
        self.saved = 0

    def bt(self):
        return "app-test"

    def list_records(self, table):
        assert table == self._state.get("issues_table", "tbl-issues")
        self.read_calls += 1
        return list(self.records.values()), self.complete

    def feishu_api(self, path, method="GET", data=None):
        self.write_calls.append((path, method, data))
        if self.fail_writes:
            self.fail_writes -= 1
            return {"code": 999, "msg": "injected write failure"}
        rid = path.rsplit("/", 1)[-1] if method == "PUT" else None
        if method == "POST":
            rid = f"rec-{len(self.records) + 1}"
        if method in ("POST", "PUT") and "/records" in path:
            self.records[rid] = {"record_id": rid, "fields": dict(data["fields"])}
            return {"code": 0, "data": {"record": {"record_id": rid}}}
        raise AssertionError(f"Unexpected fake Feishu request: {method} {path}")

    def save_state(self):
        self.saved += 1


@pytest.fixture
def issue_factory(client, human_headers):
    made = []

    def create(**changes):
        payload = {
            "title": "Feishu sync regression",
            "content": "Issue body",
            "raised_by": "test-human",
            "raised_date": "2026-10-14",
            "category": "operations",
            "priority": "medium",
            "rank": 10,
            "owner": "",
            "status": "open",
            "resolution_criteria": "",
            "resolution": "",
            "task_ids": [],
            "bug_ids": [],
        }
        payload.update(changes)
        response = client.post("/api/issues", json=payload, headers=human_headers)
        assert response.status_code == 200, response.text
        iid = response.json()["id"]
        made.append(iid)
        return iid

    create.track = made.append
    yield create
    with get_db() as conn:
        for iid in made:
            conn.execute("DELETE FROM issues WHERE id=?", (iid,))
            conn.execute("DELETE FROM sync_conflicts WHERE entity_type='issue' AND entity_id=?", (iid,))


def get_issue(iid):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()
        return dict(row) if row else None


def issue_snapshot(iid):
    from helpers import issue_to_dict

    with get_db() as conn:
        return snapshot(issue_to_dict(conn.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone()))


def remote_record(iid, values, display_id="ISS-REMOTE-001", rid="rec-1"):
    return {"record_id": rid, "fields": to_fields(values, iid, display_id)}


def test_unconfigured_sync_is_noop(issue_factory):
    issue_factory()
    transport = FakeTransport(configured=False)

    assert sync_issues(None, transport) == {"pushed": 0, "pulled": 0, "conflicts": 0, "errors": 0}
    assert transport.read_calls == 0
    assert transport.write_calls == []
    assert "issues_baselines" not in transport._state


def test_local_issue_is_created_remotely_and_acknowledged(issue_factory):
    iid = issue_factory()
    transport = FakeTransport()

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    assert stats["pushed"] == 1
    assert len(transport.records) == 1
    record = next(iter(transport.records.values()))
    assert record["fields"]["kanban_id"] == iid
    assert transport._state["issues_baselines"][iid] == issue_snapshot(iid)
    assert transport.saved >= 1


def test_new_remote_issue_is_pulled_and_canonical_id_backfilled(issue_factory):
    local_seed = issue_factory()
    values = issue_snapshot(local_seed)
    values["title"] = "Created in Feishu"
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record("", values, rid="rec-1")

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    # The remote record has no canonical ID, so sync assigns one and persists it.
    assert stats["pulled"] == 1
    assert any(r["fields"].get("kanban_id") for r in transport.records.values())
    imported = next(row for row in _all_issues() if row["title"] == "Created in Feishu")
    issue_factory.track(imported["id"])
    assert transport.records["rec-1"]["fields"]["kanban_id"] == imported["id"]


def _all_issues():
    with get_db() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM issues").fetchall()]


def test_remote_field_change_is_found_even_without_timestamp_change(issue_factory):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base)
    transport._state["issues_baselines"] = {iid: dict(base)}
    transport._state["last_sync_ts_issues"] = {iid: "unchanged timestamp"}
    transport.records["rec-1"]["fields"]["Title"] = "Edited remotely"

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    assert stats["pulled"] == 1
    assert get_issue(iid)["title"] == "Edited remotely"


def test_disjoint_local_and_remote_edits_merge(issue_factory, client, human_headers):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base)
    transport._state["issues_baselines"] = {iid: dict(base)}
    assert client.put(f"/api/issues/{iid}", json={"owner": "local-owner"}, headers=human_headers).status_code == 200
    transport.records["rec-1"]["fields"]["Priority"] = "high"

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    row = get_issue(iid)
    assert stats["conflicts"] == 0
    assert row["owner"] == "local-owner"
    assert row["priority"] == "high"
    pushed = transport.records["rec-1"]["fields"]
    assert pushed["Owner"] == "local-owner", (stats, transport.write_calls)
    assert pushed["Priority"] == "high"


def test_overlapping_edits_conflict_without_overwrite_and_deduplicate(issue_factory, client, human_headers):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base)
    transport._state["issues_baselines"] = {iid: dict(base)}
    client.put(f"/api/issues/{iid}", json={"title": "Local title"}, headers=human_headers)
    transport.records["rec-1"]["fields"]["Title"] = "Remote title"

    with get_db() as conn:
        first = sync_issues(conn, transport)
    with get_db() as conn:
        second = sync_issues(conn, transport)
    with get_db() as conn:
        conflicts = conn.execute(
            "SELECT * FROM sync_conflicts WHERE entity_type='issue' AND entity_id=? AND resolved=0",
            (iid,),
        ).fetchall()

    assert first["conflicts"] == second["conflicts"] == 1
    assert len(conflicts) == 1
    assert (conflicts[0]["local_value"], conflicts[0]["remote_value"]) == ("Local title", "Remote title")
    assert get_issue(iid)["title"] == "Local title"
    assert transport.records["rec-1"]["fields"]["Title"] == "Remote title"
    assert transport._state["issues_baselines"][iid] == base


@pytest.mark.parametrize("resolution,manual,expected", [
    ("local", None, "Local title"),
    ("remote", None, "Remote title"),
    ("manual", "Reviewed title", "Reviewed title"),
])
def test_conflict_resolution_is_honored_on_next_sync(
    issue_factory, client, human_headers, resolution, manual, expected
):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base)
    transport._state["issues_baselines"] = {iid: dict(base)}
    client.put(f"/api/issues/{iid}", json={"title": "Local title"}, headers=human_headers)
    transport.records["rec-1"]["fields"]["Title"] = "Remote title"
    with get_db() as conn:
        sync_issues(conn, transport)
        conflict = conn.execute(
            "SELECT id FROM sync_conflicts WHERE entity_type='issue' AND entity_id=? AND resolved=0", (iid,)
        ).fetchone()
    body = {"resolution": resolution}
    if manual is not None:
        body["manual_value"] = manual
    assert client.put(f"/api/sync-conflicts/{conflict['id']}/resolve", json=body,
                      headers=human_headers).status_code == 200

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    assert stats["conflicts"] == 0
    assert get_issue(iid)["title"] == expected
    assert transport.records["rec-1"]["fields"]["Title"] == expected, (stats, transport.write_calls)


def test_failed_create_does_not_advance_baseline_and_retries(issue_factory):
    iid = issue_factory()
    transport = FakeTransport()
    transport.fail_writes = 1
    with get_db() as conn:
        first = sync_issues(conn, transport)
    assert first["errors"] == 1
    assert iid not in transport._state.get("issues_baselines", {})
    assert transport.records == {}

    with get_db() as conn:
        second = sync_issues(conn, transport)
    assert second["pushed"] == 1
    assert iid in transport._state["issues_baselines"]
    assert len(transport.records) == 1


def test_failed_update_retains_baseline_and_retries(issue_factory, client, human_headers):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base, get_issue(iid)["display_id"])
    transport._state["issues_baselines"] = {iid: dict(base)}
    client.put(f"/api/issues/{iid}", headers=human_headers, json={"title": "Local change"})
    transport.fail_writes = 1
    with get_db() as conn:
        first = sync_issues(conn, transport)
    assert first["errors"] == 1
    assert transport._state["issues_baselines"][iid] == base
    assert transport.records["rec-1"]["fields"]["Title"] == base["title"]
    with get_db() as conn:
        second = sync_issues(conn, transport)
    assert second["pushed"] == 1
    assert transport.records["rec-1"]["fields"]["Title"] == "Local change"


def test_duplicate_remote_identity_changes_neither_record(issue_factory):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base, rid="rec-1")
    transport.records["rec-2"] = remote_record(iid, base | {"title": "Duplicate"}, rid="rec-2")
    with get_db() as conn:
        stats = sync_issues(conn, transport)
    assert stats["errors"] == 2
    assert transport.write_calls == []
    assert issue_snapshot(iid) == base


def test_bulk_remote_resolution_applies_closure_evidence_together(issue_factory, client, human_headers):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    remote = base | {"status": "closed", "resolution_criteria": "Acceptance", "resolution": "Reviewed"}
    transport.records["rec-1"] = remote_record(iid, remote, get_issue(iid)["display_id"])
    # First connection with different values needs explicit human resolution.
    with get_db() as conn:
        stats = sync_issues(conn, transport)
    assert stats["conflicts"] == 3
    response = client.post("/api/sync-conflicts/resolve-all", headers=human_headers, json={"resolution": "remote"})
    assert response.status_code == 200, response.text
    with get_db() as conn:
        synced = sync_issues(conn, transport)
    assert synced["conflicts"] == 0
    assert get_issue(iid)["status"] == "closed"


def test_successful_sync_does_not_write_again(issue_factory):
    iid = issue_factory()
    transport = FakeTransport()
    with get_db() as conn:
        sync_issues(conn, transport)
    count = len(transport.write_calls)
    with get_db() as conn:
        stats = sync_issues(conn, transport)
    assert stats == {"pushed": 0, "pulled": 0, "conflicts": 0, "errors": 0}
    assert len(transport.write_calls) == count


def test_api_edit_during_remote_request_is_preserved(issue_factory, client, human_headers):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base | {"title": "Remote change"})
    transport._state["issues_baselines"] = {iid: base}
    write = transport.feishu_api
    def concurrent_edit(*args, **kwargs):
        response = client.put(f"/api/issues/{iid}", headers=human_headers, json={"title": "Concurrent local edit"})
        assert response.status_code == 200
        return write(*args, **kwargs)
    transport.feishu_api = concurrent_edit
    with get_db() as conn:
        stats = sync_issues(conn, transport)
    assert stats["errors"] == 1
    assert get_issue(iid)["title"] == "Concurrent local edit"
    assert transport._state["issues_baselines"][iid] == base


def test_incomplete_remote_read_neither_creates_nor_deletes(issue_factory):
    iid = issue_factory()
    base = issue_snapshot(iid)
    remote_iid = "remote-keep"
    remote_seed = issue_factory(title="Remote-only seed")
    remote_values = issue_snapshot(remote_seed)
    transport = FakeTransport()
    transport.complete = False
    transport.records["rec-existing"] = remote_record(remote_iid, remote_values, rid="rec-existing")
    before = dict(transport.records)

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    assert stats["errors"] == 1
    assert transport.records == before
    assert iid not in transport._state.get("issues_baselines", {})
    assert get_issue(iid) is not None


@pytest.mark.parametrize("direction", ["archive", "restore"])
def test_archived_checkbox_is_explicitly_two_way(issue_factory, direction):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base)
    transport._state["issues_baselines"] = {iid: dict(base)}
    if direction == "archive":
        transport.records["rec-1"]["fields"]["Archived"] = True
    else:
        with get_db() as conn:
            conn.execute("UPDATE issues SET deleted_at='2026-10-14 00:00:00' WHERE id=?", (iid,))
        base["deleted_at"] = "archived"
        transport._state["issues_baselines"][iid] = dict(base)
        transport.records["rec-1"]["fields"]["Archived"] = False

    with get_db() as conn:
        stats = sync_issues(conn, transport)
    if direction == "archive":
        assert stats["pulled"] == 1
        assert get_issue(iid)["deleted_at"] is not None
        with get_db() as conn:
            conn.execute("UPDATE issues SET deleted_at=NULL WHERE id=?", (iid,))
        with get_db() as conn:
            restore_stats = sync_issues(conn, transport)
        assert restore_stats["pushed"] == 1
        assert transport.records["rec-1"]["fields"]["Archived"] is False
    else:
        assert stats["pushed"] == 1
        assert get_issue(iid)["deleted_at"] is None


@pytest.mark.parametrize("field,value", [
    ("Status", "not-a-status"),
    ("Rank", -1),
    ("Status", "closed"),
])
def test_invalid_remote_issue_is_rejected_without_local_change(issue_factory, field, value):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base)
    transport.records["rec-1"]["fields"][field] = value
    transport._state["issues_baselines"] = {iid: dict(base)}

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    assert stats["errors"] == 1
    assert issue_snapshot(iid) == base
    assert transport._state["issues_baselines"][iid] == base


@pytest.mark.parametrize("field", ["Task IDs", "Bug IDs"])
def test_malformed_remote_link_json_is_rejected(issue_factory, field):
    iid = issue_factory()
    base = issue_snapshot(iid)
    transport = FakeTransport()
    transport.records["rec-1"] = remote_record(iid, base)
    transport.records["rec-1"]["fields"][field] = "{not-json"
    transport._state["issues_baselines"] = {iid: dict(base)}

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    assert stats["errors"] == 1
    assert issue_snapshot(iid) == base


def test_missing_remote_baseline_record_is_retained_and_reported(issue_factory):
    iid = issue_factory()
    transport = FakeTransport()
    transport._state["issues_baselines"] = {iid: issue_snapshot(iid)}

    with get_db() as conn:
        stats = sync_issues(conn, transport)

    assert stats["errors"] == 1
    assert transport.records == {}
    assert iid in transport._state["issues_baselines"]
    assert get_issue(iid) is not None


def test_setup_preview_is_local_and_does_not_import_live_sync(monkeypatch, capsys):
    script = Path(__file__).parents[1] / "scripts" / "setup_issues_bitable.py"
    spec = importlib.util.spec_from_file_location("setup_issues_bitable_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setitem(__import__("sys").modules, "feishu_sync", None)
    monkeypatch.setattr(__import__("sys"), "argv", [str(script)])

    module.main()

    output = capsys.readouterr().out
    assert TABLE_NAME in output
    assert "Preview only" in output
    assert json.loads(output.split("Preview only", 1)[0])["fields"] == {
        key: list(value) for key, value in FIELDS.items()
    }


class FakeProvisionTransport:
    def __init__(self, fail_field=None):
        self._state = {}
        self.saved = 0
        self.calls = []
        self.tables = []
        self.fields = {}
        self.fail_field = fail_field

    def bt(self):
        return "app-test"

    def save_state(self):
        self.saved += 1

    def feishu_api(self, path, method="GET", data=None):
        self.calls.append((path, method, data))
        suffix = path.removeprefix("/bitable/v1/apps/app-test")
        if suffix.startswith("/tables?"):
            return {"code": 0, "data": {"items": self.tables, "has_more": False}}
        if suffix == "/tables" and method == "POST":
            table = {"name": data["table"]["name"], "table_id": "tbl-created"}
            self.tables.append(table)
            self.fields["tbl-created"] = []
            return {"code": 0, "data": {"table_id": "tbl-created"}}
        if "/fields?" in suffix:
            tid = suffix.split("/")[2]
            return {"code": 0, "data": {"items": self.fields.setdefault(tid, []), "has_more": False}}
        if suffix.endswith("/fields") and method == "POST":
            if data["field_name"] == self.fail_field:
                return {"code": 1, "msg": "injected schema failure"}
            tid = suffix.split("/")[2]
            field = {"field_name": data["field_name"], "type": data["type"],
                     "field_id": f"fld-{len(self.fields[tid]) + 1}",
                     "property": data.get("property", {})}
            self.fields[tid].append(field)
            return {"code": 0, "data": {}}
        if "/fields/" in suffix and method == "PUT":
            return {"code": 0, "data": {}}
        raise AssertionError(f"Unexpected provisioning request: {method} {path}")


def test_setup_provision_is_idempotent_and_saves_selected_table():
    script = Path(__file__).parents[1] / "scripts" / "setup_issues_bitable.py"
    spec = importlib.util.spec_from_file_location("setup_issues_bitable_provision_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transport = FakeProvisionTransport()

    assert module.provision(transport) == "tbl-created"
    first_field_count = len(transport.fields["tbl-created"])
    call_count = len(transport.calls)
    assert module.provision(transport) == "tbl-created"

    assert len(transport.fields["tbl-created"]) == first_field_count
    assert len(transport.calls) == call_count + 1  # configured-table field inspection only
    assert transport._state["issues_table"] == "tbl-created"
    assert transport.saved == 2


def test_setup_provision_failure_does_not_enable_partial_schema():
    script = Path(__file__).parents[1] / "scripts" / "setup_issues_bitable.py"
    spec = importlib.util.spec_from_file_location("setup_issues_bitable_failure_test", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    transport = FakeProvisionTransport(fail_field="Status")

    with pytest.raises(RuntimeError, match="schema request failed"):
        module.provision(transport)

    assert "issues_table" not in transport._state
    assert transport.saved == 0

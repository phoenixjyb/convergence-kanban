import json

from db import DATA_DIR, get_db


def _remove_state_files():
    for path in DATA_DIR.glob("feishu_sync_state*.json"):
        path.unlink()


def test_sync_status_without_state_file(client, monkeypatch):
    _remove_state_files()
    monkeypatch.delenv("FEISHU_APP_ID", raising=False)
    monkeypatch.delenv("FEISHU_APP_SECRET", raising=False)

    r = client.get("/api/sync/status")
    assert r.status_code == 200
    data = r.json()
    assert data["enabled"] is False
    assert data["state_file"] is None
    assert "Feishu is not configured" in data["reason"]
    assert "db_counts" in data
    assert "unresolved_conflicts" in data


def test_sync_status_summarizes_state_file_safely(client):
    _remove_state_files()
    state_path = DATA_DIR / "feishu_sync_state_team.json"
    state_path.write_text(json.dumps({
        "bitable_app_token": "appTokenSecretValue",
        "projects_table": "tblProjectsSecret",
        "tasks_table": "tblTasksSecret",
        "bugs_table": "tblQABugsSecret",
        "rd_bugs_table": "tblRDBugsSecret",
        "synced_kids_projects": ["p1", "p2"],
        "last_sync_ts_tasks": {"t1": "2026-07-07 10:00:00", "t2": "2026-07-07 10:05:00"},
        "last_sync_ts_bugs": {"b1": "2026-07-07 10:06:00"},
        "last_sync_ts_bugs_rd": {"r1": "2026-07-07 10:07:00"},
    }), encoding="utf-8")

    with get_db() as conn:
        conn.execute(
            "INSERT INTO sync_conflicts (id, entity_type, entity_id, field_name, local_value, remote_value, local_updated, remote_updated) "
            "VALUES ('sync-test-conflict', 'task', 't1', 'status', 'todo', 'doing', '2026-07-07 10:00:00', '2026-07-07 10:01:00')"
        )

    r = client.get("/api/sync/status")
    assert r.status_code == 200
    data = r.json()
    body = json.dumps(data)
    assert data["enabled"] is True
    assert data["state_file"] == "feishu_sync_state_team.json"
    assert data["tables"]["tasks"]["record_count"] == 2
    assert data["tables"]["tasks"]["latest_sync_at"] == "2026-07-07 10:05:00"
    assert data["tables"]["qa_bugs"]["latest_sync_at"] == "2026-07-07 10:06:00"
    assert data["tables"]["rd_bugs"]["latest_sync_at"] == "2026-07-07 10:07:00"
    assert data["unresolved_conflicts"] >= 1
    assert "bug_hygiene" in data
    assert "local_active_count" in data["tables"]["qa_bugs"]
    assert "state_map_delta" in data["tables"]["qa_bugs"]
    assert "appTokenSecretValue" not in body
    assert "tblQABugsSecret" not in body


def test_sync_status_reports_bug_hygiene(client):
    _remove_state_files()
    state_path = DATA_DIR / "feishu_sync_state_team.json"
    state_path.write_text(json.dumps({
        "projects_table": "tblProjectsSecret",
        "tasks_table": "tblTasksSecret",
        "bugs_table": "tblQABugsSecret",
        "rd_bugs_table": "tblRDBugsSecret",
        "last_sync_ts_bugs": {
            "sync-status-missing-id": "2026-07-07 10:06:00",
        },
        "last_sync_ts_bugs_rd": {
            "sync-status-legacy-id": "2026-07-07 10:07:00",
        },
    }), encoding="utf-8")

    with get_db() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO bugs
            (id, title, source, display_id, status, fix_method, fix_version, fix_date)
            VALUES
            ('sync-status-missing-id', 'Missing display id', 'manual', '', 'fix_complete', '', '', ''),
            ('sync-status-legacy-id', 'Legacy display id', 'agent', 'RD-0707-001', 'closed', '', '', '')
            """
        )

    r = client.get("/api/sync/status")
    assert r.status_code == 200
    data = r.json()
    hygiene = data["bug_hygiene"]
    assert hygiene["qa_bugs"]["missing_display_id"] >= 1
    assert hygiene["qa_bugs"]["fixed_missing_metadata"] >= 1
    assert hygiene["rd_bugs"]["legacy_display_id"] >= 1
    assert hygiene["rd_bugs"]["fixed_missing_metadata"] >= 1
    assert data["tables"]["qa_bugs"]["local_active_count"] >= 1
    assert "tblQABugsSecret" not in json.dumps(data)

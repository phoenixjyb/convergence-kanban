"""Tests for CSV bulk import endpoints (tasks and bugs)."""

import io
import uuid

import pytest


def _make_csv(rows: list[dict]) -> bytes:
    """Build a CSV file from a list of dicts, union of all keys as columns."""
    if not rows:
        return b""
    import csv
    # Collect all keys across all rows to handle varying columns
    all_keys: list[str] = []
    seen: set[str] = set()
    for r in rows:
        for k in r:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return buf.getvalue().encode()


def _seed_project_and_workstream(client, human_headers):
    """Create a project and workstream, return (project_id, workstream_id)."""
    resp = client.post("/api/projects", json={"name_en": "Import Test"},
                       headers=human_headers)
    pid = resp.json()["id"]
    resp = client.post("/api/workstreams",
                       json={"project_id": pid, "title_en": "WS-Import"},
                       headers=human_headers)
    wid = resp.json()["id"]
    return pid, wid


# ── Task import ──────────────────────────────────────────────────────────

def test_import_tasks_valid(client, human_headers):
    pid, wid = _seed_project_and_workstream(client, human_headers)

    csv_data = _make_csv([
        {"title_en": "Task A", "workstream_id": wid, "priority": "high"},
        {"title_en": "Task B", "workstream_id": wid, "status": "doing", "assignee": "alice"},
    ])
    resp = client.post(
        "/api/import/tasks",
        files={"file": ("tasks.csv", csv_data, "text/csv")},
        headers={"X-Kanban-User": "test-human"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0
    assert body["errors"] == []


def test_import_tasks_missing_required(client, human_headers):
    _pid, wid = _seed_project_and_workstream(client, human_headers)

    csv_data = _make_csv([
        {"title_en": "", "workstream_id": wid},           # missing title
        {"title_en": "Good Task", "workstream_id": ""},    # missing workstream
        {"title_en": "Also Good", "workstream_id": wid},   # valid
    ])
    resp = client.post(
        "/api/import/tasks",
        files={"file": ("tasks.csv", csv_data, "text/csv")},
        headers={"X-Kanban-User": "test-human"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2
    assert len(body["errors"]) == 2


def test_import_tasks_invalid_workstream(client, human_headers):
    csv_data = _make_csv([
        {"title_en": "Orphan", "workstream_id": "nonexistent-ws"},
    ])
    resp = client.post(
        "/api/import/tasks",
        files={"file": ("tasks.csv", csv_data, "text/csv")},
        headers={"X-Kanban-User": "test-human"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert "not found" in body["errors"][0]


def test_import_tasks_empty_file(client, human_headers):
    resp = client.post(
        "/api/import/tasks",
        files={"file": ("empty.csv", b"", "text/csv")},
        headers={"X-Kanban-User": "test-human"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 0
    assert body["skipped"] == 0


# ── Bug import ───────────────────────────────────────────────────────────

def test_import_bugs_valid(client, human_headers):
    pid, _wid = _seed_project_and_workstream(client, human_headers)

    csv_data = _make_csv([
        {"title": "Bug 1", "severity": "high", "project_id": pid, "description": "oops"},
        {"title": "Bug 2", "severity": "low", "project_id": pid},
    ])
    resp = client.post(
        "/api/import/bugs",
        files={"file": ("bugs.csv", csv_data, "text/csv")},
        headers={"X-Kanban-User": "test-human"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 2
    assert body["skipped"] == 0


def test_import_bugs_missing_required(client, human_headers):
    pid, _ = _seed_project_and_workstream(client, human_headers)

    csv_data = _make_csv([
        {"title": "", "severity": "high", "project_id": pid},     # missing title
        {"title": "Good Bug", "severity": "high", "project_id": ""},  # missing project
        {"title": "Valid", "severity": "medium", "project_id": pid},   # valid
    ])
    resp = client.post(
        "/api/import/bugs",
        files={"file": ("bugs.csv", csv_data, "text/csv")},
        headers={"X-Kanban-User": "test-human"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 1
    assert body["skipped"] == 2


def test_import_bugs_empty_file(client, human_headers):
    resp = client.post(
        "/api/import/bugs",
        files={"file": ("empty.csv", b"", "text/csv")},
        headers={"X-Kanban-User": "test-human"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["imported"] == 0
    assert body["skipped"] == 0

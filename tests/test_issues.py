"""Cross-team issue API and governance regression coverage."""

import re

import pytest

from db import get_db, init_db


def make_issue(client, headers, **fields):
    response = client.post("/api/issues", headers=headers, json={
        "title": "Outdoor screen readability", "content": "Users cannot read controls in sunlight",
        "category": "product_experience", **fields,
    })
    assert response.status_code == 200, response.text
    return response.json()["id"]


def test_issue_submission_does_not_require_project_or_bug(client, human_headers):
    iid = make_issue(client, human_headers)
    row = client.get(f"/api/issues/{iid}").json()
    assert re.fullmatch(r"ISS-\d{6}-\d{3,}", row["display_id"])
    assert row["raised_by"] == "test-human"
    assert row["raised_date"]
    assert row["project_id"] is None
    assert row["task_ids"] == row["bug_ids"] == []
    assert row["status"] == "open"


@pytest.mark.parametrize("category", ["hardware", "software", "product_experience", "process", "delivery", "operations", "other"])
def test_issue_categories(client, human_headers, category):
    iid = make_issue(client, human_headers, category=category)
    assert any(row["id"] == iid for row in client.get(f"/api/issues?category={category}").json())


def test_issue_closure_needs_human_and_resolution(client, human_headers, bot_headers):
    iid = make_issue(client, bot_headers)
    url = f"/api/issues/{iid}"
    assert client.put(url, headers=human_headers, json={"status": "closed"}).status_code == 400
    evidence = {"status": "closed", "resolution_criteria": "Readable outdoors", "resolution": "QA approved hardware sample"}
    assert client.put(url, headers=bot_headers, json=evidence).status_code == 403
    assert client.put(url, headers=human_headers, json=evidence).status_code == 200
    assert client.get(url).json()["status"] == "closed"
    assert client.put(url, headers=human_headers, json={"resolution": ""}).status_code == 400
    assert client.put(url, headers=human_headers, json={"status": "open"}).status_code == 200


def test_issue_delete_restore_and_comments(client, human_headers, bot_headers):
    iid = make_issue(client, human_headers)
    url = f"/api/issues/{iid}"
    assert client.post(f"/api/comments/issue/{iid}", headers=bot_headers, json={"body": "Gathered feedback"}).status_code == 200
    assert client.get(f"/api/comments/issue/{iid}").json()["comments"][0]["body"] == "Gathered feedback"
    assert client.delete(url, headers=bot_headers).status_code == 403
    assert client.delete(url, headers=human_headers).status_code == 200
    assert client.get(url).status_code == 404
    assert not any(row["id"] == iid for row in client.get("/api/issues").json())
    assert any(row["id"] == iid for row in client.get("/api/issues?include_deleted=true").json())
    assert client.post(url + "/restore", headers=bot_headers).status_code == 403
    assert client.post(url + "/restore", headers=human_headers).status_code == 200
    assert client.get(url).status_code == 200


def test_issue_reference_validation_and_clear(client, human_headers):
    project = client.post("/api/projects", headers=human_headers, json={"name_en": "Issue links"}).json()["id"]
    wid = client.post("/api/workstreams", headers=human_headers, json={"project_id": project, "title_en": "Test hardware"}).json()["id"]
    tid = client.post("/api/tasks", headers=human_headers, json={"workstream_id": wid, "title_en": "Prototype"}).json()["id"]
    iid = make_issue(client, human_headers, project_id=project, workstream_id=wid, task_ids=[tid])
    url = f"/api/issues/{iid}"
    assert client.put(url, headers=human_headers, json={"task_ids": ["missing-task"]}).status_code == 400
    assert client.put(url, headers=human_headers, json={"project_id": None, "workstream_id": None, "task_ids": []}).status_code == 200
    assert client.get(url).json()["project_id"] is None
    assert client.put(url, headers=human_headers, json={"title": None}).status_code == 400


@pytest.mark.parametrize("fields", [{"title": "  "}, {"content": "\n"}, {"category": "unknown"}, {"rank": -1}, {"due_date": "not-a-date"}])
def test_issue_invalid_submissions(client, human_headers, fields):
    response = client.post("/api/issues", headers=human_headers, json={"title": "Issue", "content": "Problem", **fields})
    assert response.status_code in (400, 422)


def test_issue_ranked_before_unranked_and_closed_last(client, human_headers):
    first = make_issue(client, human_headers, rank=1)
    second = make_issue(client, human_headers, rank=2)
    unranked = make_issue(client, human_headers, rank=0)
    closed = make_issue(client, human_headers, rank=1, status="closed", resolution_criteria="Check", resolution="Approved")
    order = [r["id"] for r in client.get("/api/issues").json()]
    assert order.index(first) < order.index(second) < order.index(unranked) < order.index(closed)


def test_issue_migration_preserves_conflicts_and_is_idempotent(client, human_headers):
    iid = make_issue(client, human_headers)
    with get_db() as db:
        db.execute("INSERT INTO sync_conflicts (id,entity_type,entity_id,field_name) VALUES ('issue-migration-check','issue',?,'title')", (iid,))
    init_db()
    init_db()
    with get_db() as db:
        assert db.execute("SELECT entity_id FROM sync_conflicts WHERE id='issue-migration-check'").fetchone()["entity_id"] == iid
    assert client.get(f"/api/issues/{iid}").status_code == 200


def test_issue_unauthenticated_write(client):
    assert client.post("/api/issues", json={"title": "Issue", "content": "Problem"}).status_code == 401


def test_old_conflict_schema_preserves_resolved_rows_during_upgrade(tmp_path, monkeypatch):
    import db
    with get_db() as conn:
        schema = conn.execute("SELECT sql FROM sqlite_master WHERE name='sync_conflicts'").fetchone()["sql"]
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "legacy.db")
    with db.get_db() as conn:
        conn.execute(schema.replace("('task','blocker','bug','issue')", "('task','blocker','bug')"))
        conn.execute("INSERT INTO sync_conflicts (id,entity_type,entity_id,field_name,resolved,resolution,resolved_by) VALUES ('legacy','bug','old-bug','title',1,'local','reviewer')")
    db.init_db()
    with db.get_db() as conn:
        row = conn.execute("SELECT * FROM sync_conflicts WHERE id='legacy'").fetchone()
        assert row["resolved"] == 1
        assert row["resolved_by"] == "reviewer"
        assert "'issue'" in conn.execute("SELECT sql FROM sqlite_master WHERE name='sync_conflicts'").fetchone()["sql"]

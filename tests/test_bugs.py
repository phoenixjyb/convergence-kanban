"""Bug CRUD and task linking tests."""


def test_bug_create(client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "BugP"},
                      headers=human_headers).json()["id"]
    r = client.post("/api/bugs", json={
        "title": "Crash on startup", "severity": "critical",
        "reporter": "test-human", "project_id": pid,
        "feature": "navigation", "repro_rate": "100%"
    }, headers=human_headers)
    assert r.status_code == 200
    bug = r.json()
    assert "id" in bug


def test_bug_update(client, human_headers):
    r = client.post("/api/bugs", json={
        "title": "Minor UI issue", "severity": "low"
    }, headers=human_headers)
    bug_id = r.json()["id"]

    r = client.put(f"/api/bugs/{bug_id}", json={
        "status": "investigating", "assignee": "test-human"
    }, headers=human_headers)
    assert r.status_code == 200

    r = client.get(f"/api/bugs/{bug_id}")
    assert r.json()["status"] == "investigating"
    assert r.json()["assignee"] == "test-human"


def test_bug_list_and_get(client, human_headers):
    client.post("/api/bugs", json={"title": "ListBug1", "severity": "high"},
                headers=human_headers)
    r = client.get("/api/bugs")
    assert r.status_code == 200
    bugs = r.json()
    assert any(b["title"] == "ListBug1" for b in bugs)


def test_bug_new_fields_roundtrip(client, human_headers):
    """v1.4.5: device_id, issue_version, issue_images round-trip (team-added fields)."""
    bug_id = client.post("/api/bugs", json={
        "title": "Device fails on AGX Orin (unit-B)",
        "severity": "high",
        "device_id": "160",
        "issue_version": "v1.4.4",
        "issue_images": [
            {"file_token": "tok_a", "name": "screenshot.jpg", "size": 1024, "type": "image/jpeg"},
        ],
    }, headers=human_headers).json()["id"]

    # GET single bug — issue_images is returned as a parsed list
    r = client.get(f"/api/bugs/{bug_id}")
    assert r.status_code == 200
    b = r.json()
    assert b["device_id"] == "160"
    assert b["issue_version"] == "v1.4.4"
    assert isinstance(b["issue_images"], list)
    assert len(b["issue_images"]) == 1
    assert b["issue_images"][0]["file_token"] == "tok_a"
    assert b["issue_images"][0]["name"] == "screenshot.jpg"

    # List endpoint also returns parsed list
    bugs = client.get("/api/bugs").json()
    me = next(x for x in bugs if x["id"] == bug_id)
    assert isinstance(me["issue_images"], list) and len(me["issue_images"]) == 1

    # PUT updates
    r = client.put(f"/api/bugs/{bug_id}", json={
        "device_id": "162",
        "issue_version": "v1.4.5",
        "issue_images": [
            {"file_token": "tok_b", "name": "log.txt", "size": 5000, "type": "text/plain"},
            {"file_token": "tok_c", "name": "recording.mp4", "size": 1000000, "type": "video/mp4"},
        ],
    }, headers=human_headers)
    assert r.status_code == 200

    b = client.get(f"/api/bugs/{bug_id}").json()
    assert b["device_id"] == "162"
    assert b["issue_version"] == "v1.4.5"
    assert len(b["issue_images"]) == 2
    assert [a["file_token"] for a in b["issue_images"]] == ["tok_b", "tok_c"]


def test_bug_issue_images_defaults_to_empty_list(client, human_headers):
    """Bugs without attachments return [] for issue_images, not '' or None."""
    bug_id = client.post("/api/bugs", json={
        "title": "No attachments", "severity": "low"
    }, headers=human_headers).json()["id"]
    b = client.get(f"/api/bugs/{bug_id}").json()
    assert b["issue_images"] == []


def test_bug_task_linking(client, human_headers):
    # Create bug
    bug_id = client.post("/api/bugs", json={
        "title": "Link Test Bug", "severity": "medium"
    }, headers=human_headers).json()["id"]

    # Create task
    pid = client.post("/api/projects", json={"name_en": "LinkP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "LinkWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "LinkTask"
    }, headers=human_headers).json()["id"]

    # Link task to bug (API expects task_ids list)
    r = client.post(f"/api/bugs/{bug_id}/tasks", json={"task_ids": [tid]},
                    headers=human_headers)
    assert r.status_code == 200

    # Verify linked
    r = client.get(f"/api/bugs/{bug_id}/tasks")
    assert r.status_code == 200
    linked = r.json()
    assert any(t["id"] == tid for t in linked)

    # Unlink
    r = client.delete(f"/api/bugs/{bug_id}/tasks/{tid}",
                      headers=human_headers)
    assert r.status_code == 200

    # Verify unlinked
    r = client.get(f"/api/bugs/{bug_id}/tasks")
    assert not any(t["id"] == tid for t in r.json())


def test_bug_delete(client, human_headers):
    bug_id = client.post("/api/bugs", json={
        "title": "DeleteMe", "severity": "low"
    }, headers=human_headers).json()["id"]

    r = client.delete(f"/api/bugs/{bug_id}", headers=human_headers)
    assert r.status_code == 200

    # Should not appear in list anymore
    r = client.get("/api/bugs")
    assert not any(b["id"] == bug_id for b in r.json())


def test_bug_suggest_links(client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "SugP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "SugWS"
    }, headers=human_headers).json()["id"]
    client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Fix crash on startup"
    }, headers=human_headers)

    bug_id = client.post("/api/bugs", json={
        "title": "crash on startup", "severity": "high"
    }, headers=human_headers).json()["id"]

    r = client.get(f"/api/bugs/{bug_id}/suggest-links")
    assert r.status_code == 200


def test_bot_create_coerces_source_to_agent(client, bot_headers):
    """Bots creating bugs are coerced to source=agent (rd-bugs-list)."""
    # Bot with no source — defaults to manual but should be coerced
    r = client.post("/api/bugs", json={"title": "Bot bug, no source"},
                    headers=bot_headers).json()
    bug = client.get("/api/bugs/" + r["id"]).json()
    assert bug["source"] == "agent"
    assert bug["display_id"].startswith("RD-")

    # Bot explicitly setting source=manual — also coerced
    r = client.post("/api/bugs", json={"title": "Bot bug, asks manual",
                                        "source": "manual"},
                    headers=bot_headers).json()
    bug = client.get("/api/bugs/" + r["id"]).json()
    assert bug["source"] == "agent"


def test_human_create_keeps_source_manual(client, human_headers):
    """Humans creating bugs without source default to manual (QA bugs table)."""
    r = client.post("/api/bugs", json={"title": "QA bug"},
                    headers=human_headers).json()
    bug = client.get("/api/bugs/" + r["id"]).json()
    assert bug["source"] == "manual"
    assert bug["display_id"].startswith("BUG-")


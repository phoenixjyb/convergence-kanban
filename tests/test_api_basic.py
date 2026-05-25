"""Basic API integration tests — critical happy paths + bot governance."""

import pytest


# ── Helper to create project + workstream + task ─────────────────────────

def _make_project(client, human_headers, name="Helper Project"):
    return client.post("/api/projects", json={"name_en": name},
                       headers=human_headers).json()["id"]


def _make_ws(client, human_headers, pid, title="Helper WS"):
    return client.post("/api/workstreams", json={
        "project_id": pid, "title_en": title
    }, headers=human_headers).json()["id"]


def _make_task(client, human_headers, wsid, title="Helper Task", **kw):
    payload = {"workstream_id": wsid, "title_en": title, **kw}
    return client.post("/api/tasks", json=payload,
                       headers=human_headers).json()["id"]


def _scaffold(client, human_headers, pname="Scaffold"):
    """Create project + workstream + task, return (pid, wsid, tid)."""
    pid = _make_project(client, human_headers, pname)
    wsid = _make_ws(client, human_headers, pid)
    tid = _make_task(client, human_headers, wsid)
    return pid, wsid, tid


# ══════════════════════════════════════════════════════════════════════════
# 1. Dashboard
# ══════════════════════════════════════════════════════════════════════════

def test_dashboard_returns_200(client):
    r = client.get("/api/dashboard")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_dashboard_structure(client, human_headers):
    """Dashboard items contain expected keys."""
    pid = _make_project(client, human_headers, "DashStruct")
    wsid = _make_ws(client, human_headers, pid, "DashWS")
    _make_task(client, human_headers, wsid, "DashTask")
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    assert "workstreams" in proj
    assert "stats" in proj
    assert "task_progress" in proj
    ws = proj["workstreams"][0]
    assert "tasks" in ws
    assert "blockers" in ws
    assert "task_stats" in ws


def test_dashboard_task_progress_pct(client, human_headers):
    """task_progress.pct is computed correctly."""
    pid = _make_project(client, human_headers, "PctProj")
    wsid = _make_ws(client, human_headers, pid)
    tid = _make_task(client, human_headers, wsid)
    # Mark done
    client.put(f"/api/tasks/{tid}", json={"status": "done"},
               headers=human_headers)
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    assert proj["task_progress"]["pct"] == 100


def test_project_crud(client, human_headers):
    # Create
    r = client.post("/api/projects", json={
        "name_en": "Test Project", "name_zh": "测试项目", "color": "#ff0000"
    }, headers=human_headers)
    assert r.status_code == 200
    pid = r.json()["id"]

    # Read via dashboard
    dash = client.get("/api/dashboard").json()
    names = [p["name_en"] for p in dash]
    assert "Test Project" in names

    # Update
    r = client.put(f"/api/projects/{pid}", json={"name_en": "Updated Project"},
                   headers=human_headers)
    assert r.status_code == 200

    # Delete (soft)
    r = client.delete(f"/api/projects/{pid}", headers=human_headers)
    assert r.status_code == 200

    # Gone from dashboard
    dash = client.get("/api/dashboard").json()
    names = [p["name_en"] for p in dash]
    assert "Updated Project" not in names


def test_full_task_lifecycle(client, human_headers):
    # Setup: project + workstream
    pid = client.post("/api/projects", json={"name_en": "Lifecycle Test"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "WS1"
    }, headers=human_headers).json()["id"]

    # Create task
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "My Task", "assignee": "test-human"
    }, headers=human_headers).json()["id"]

    # Update status: todo → doing → in_review → done
    for status in ["doing", "in_review", "done"]:
        r = client.put(f"/api/tasks/{tid}", json={"status": status},
                       headers=human_headers)
        assert r.status_code == 200

    # Verify final status
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    ws = proj["workstreams"][0]
    task = next(t for t in ws["tasks"] if t["id"] == tid)
    assert task["status"] == "done"


def test_bot_cannot_mark_done(client, human_headers, bot_headers):
    # Setup
    pid = client.post("/api/projects", json={"name_en": "Bot Test"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "Bot WS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Bot Task"
    }, headers=human_headers).json()["id"]

    # Bot sets doing — OK
    r = client.put(f"/api/tasks/{tid}", json={"status": "doing"},
                   headers=bot_headers)
    assert r.status_code == 200

    # Bot sets in_review — OK
    r = client.put(f"/api/tasks/{tid}", json={"status": "in_review"},
                   headers=bot_headers)
    assert r.status_code == 200

    # Bot tries done — 403
    r = client.put(f"/api/tasks/{tid}", json={"status": "done"},
                   headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_create_project(client, bot_headers):
    r = client.post("/api/projects", json={"name_en": "Bot Project"},
                    headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_delete_task(client, human_headers, bot_headers):
    pid = client.post("/api/projects", json={"name_en": "Del Test"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "Del WS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Del Task"
    }, headers=human_headers).json()["id"]

    r = client.delete(f"/api/tasks/{tid}", headers=bot_headers)
    assert r.status_code == 403


def test_bug_crud_and_linking(client, human_headers):
    # Setup
    pid = client.post("/api/projects", json={"name_en": "Bug Test"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "Bug WS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Bug Task"
    }, headers=human_headers).json()["id"]

    # Create bug
    bug_id = client.post("/api/bugs", json={
        "title": "Test bug", "severity": "high", "project_id": pid,
        "feature": "Testing", "repro_rate": "100%"
    }, headers=human_headers).json()["id"]

    # Get bug — verify fields
    bug = client.get(f"/api/bugs/{bug_id}").json()
    assert bug["title"] == "Test bug"
    assert bug["feature"] == "Testing"
    assert bug["repro_rate"] == "100%"

    # Link task
    r = client.post(f"/api/bugs/{bug_id}/tasks", json={"task_ids": [tid]},
                    headers=human_headers)
    assert r.status_code == 200
    assert r.json()["linked"] == 1

    # Verify linked tasks
    linked = client.get(f"/api/bugs/{bug_id}/tasks").json()
    assert len(linked) == 1
    assert linked[0]["id"] == tid

    # Reverse lookup
    task_bugs = client.get(f"/api/tasks/{tid}/bugs").json()
    assert len(task_bugs) == 1
    assert task_bugs[0]["id"] == bug_id

    # Unlink
    r = client.delete(f"/api/bugs/{bug_id}/tasks/{tid}", headers=human_headers)
    assert r.status_code == 200

    # Verify unlinked
    linked = client.get(f"/api/bugs/{bug_id}/tasks").json()
    assert len(linked) == 0


def test_analytics_snapshot(client, human_headers):
    r = client.post("/api/analytics/snapshot", headers=human_headers)
    assert r.status_code == 200

    r = client.get("/api/analytics?days=7")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_users_crud(client, human_headers):
    r = client.get("/api/users")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_activity_log(client):
    r = client.get("/api/activity?limit=10")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_wip_limits(client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "WIP Test"},
                      headers=human_headers).json()["id"]

    # Get defaults (empty)
    r = client.get(f"/api/projects/{pid}/wip-limits")
    assert r.status_code == 200
    assert r.json() == {}

    # Set limits
    r = client.put(f"/api/projects/{pid}/wip-limits",
                   json={"doing": 5, "in_review": 3},
                   headers=human_headers)
    assert r.status_code == 200
    assert r.json()["doing"] == 5
    assert r.json()["in_review"] == 3

    # Verify persisted
    r = client.get(f"/api/projects/{pid}/wip-limits")
    assert r.json()["doing"] == 5


def test_enriched_snapshot(client, human_headers):
    """Snapshot should include bug counts and assignee counts."""
    pid = client.post("/api/projects", json={"name_en": "SnapP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "SnapWS"
    }, headers=human_headers).json()["id"]
    client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "SnapTask", "assignee": "alice"
    }, headers=human_headers)
    client.post("/api/bugs", json={
        "title": "SnapBug", "severity": "low", "project_id": pid
    }, headers=human_headers)

    client.post("/api/analytics/snapshot", headers=human_headers)
    data = client.get("/api/analytics?days=1").json()
    assert len(data) >= 1
    latest = data[-1]
    proj = latest["projects"].get(pid)
    assert proj is not None
    assert "bugs" in proj
    assert "assignees" in proj


def test_workstream_reorder(client, human_headers):
    """Workstream reorder endpoint persists sort_order."""
    pid = client.post("/api/projects", json={"name_en": "Reorder Test"},
                      headers=human_headers).json()["id"]
    ws1 = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "WS-A"
    }, headers=human_headers).json()["id"]
    ws2 = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "WS-B"
    }, headers=human_headers).json()["id"]

    # Reorder: B before A
    r = client.put("/api/workstreams/reorder", json={
        "items": [{"id": ws2, "sort_order": 0}, {"id": ws1, "sort_order": 10}]
    }, headers=human_headers)
    assert r.status_code == 200

    # Verify via dashboard — B should come first
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    assert proj["workstreams"][0]["id"] == ws2
    assert proj["workstreams"][1]["id"] == ws1


def test_task_reorder(client, human_headers):
    """Task reorder endpoint persists sort_order."""
    pid = client.post("/api/projects", json={"name_en": "Task Reorder"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "WS-R"
    }, headers=human_headers).json()["id"]
    t1 = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Task-1"
    }, headers=human_headers).json()["id"]
    t2 = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Task-2"
    }, headers=human_headers).json()["id"]

    # Reorder: T2 before T1
    r = client.put("/api/tasks/reorder", json={
        "items": [{"id": t2, "sort_order": 0}, {"id": t1, "sort_order": 10}]
    }, headers=human_headers)
    assert r.status_code == 200

    # Verify via dashboard
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    tasks = proj["workstreams"][0]["tasks"]
    assert tasks[0]["id"] == t2
    assert tasks[1]["id"] == t1


# ══════════════════════════════════════════════════════════════════════════
# 2. Edge cases — empty strings, long strings, special characters
# ══════════════════════════════════════════════════════════════════════════

def test_project_with_special_characters(client, human_headers):
    """Project names with special chars are accepted."""
    r = client.post("/api/projects", json={
        "name_en": "Test <script>alert('xss')</script>",
        "name_zh": "测试 & 'quotes' \"double\""
    }, headers=human_headers)
    assert r.status_code == 200
    pid = r.json()["id"]
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    assert "<script>" in proj["name_en"]


def test_task_with_very_long_title(client, human_headers):
    """Tasks with titles over 500 chars are rejected; 500 is accepted."""
    pid, wsid, _ = _scaffold(client, human_headers, "LongTitle")
    # 501 chars rejected
    r = client.post("/api/tasks", json={"workstream_id": wsid, "title_en": "A" * 501},
                    headers=human_headers)
    assert r.status_code == 422
    # 500 chars accepted
    tid = _make_task(client, human_headers, wsid, "A" * 500)
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    task = next(t for t in proj["workstreams"][0]["tasks"] if t["id"] == tid)
    assert len(task["title_en"]) == 500


def test_task_with_unicode_emoji(client, human_headers):
    """Tasks with emoji titles work."""
    pid, wsid, _ = _scaffold(client, human_headers, "EmojiProj")
    tid = _make_task(client, human_headers, wsid, "Fix bug 🐛🔥")
    assert tid  # created successfully


def test_project_with_empty_name_zh(client, human_headers):
    """Chinese name defaults to empty string."""
    r = client.post("/api/projects", json={"name_en": "EnOnly"},
                    headers=human_headers)
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 3. Error paths — 404, 422, invalid IDs
# ══════════════════════════════════════════════════════════════════════════

def test_update_nonexistent_project(client, human_headers):
    r = client.put("/api/projects/nonexistent999", json={"name_en": "X"},
                   headers=human_headers)
    assert r.status_code == 404


def test_delete_nonexistent_project(client, human_headers):
    r = client.delete("/api/projects/nonexistent999", headers=human_headers)
    assert r.status_code == 404


def test_update_nonexistent_task(client, human_headers):
    r = client.put("/api/tasks/nonexistent999", json={"status": "doing"},
                   headers=human_headers)
    assert r.status_code == 404


def test_delete_nonexistent_task(client, human_headers):
    r = client.delete("/api/tasks/nonexistent999", headers=human_headers)
    assert r.status_code == 404


def test_update_task_no_fields(client, human_headers):
    """Updating with empty body returns 400."""
    pid, wsid, tid = _scaffold(client, human_headers, "NoFields")
    r = client.put(f"/api/tasks/{tid}", json={}, headers=human_headers)
    assert r.status_code == 400


def test_update_project_no_fields(client, human_headers):
    pid = _make_project(client, human_headers, "NoFieldsP")
    r = client.put(f"/api/projects/{pid}", json={}, headers=human_headers)
    assert r.status_code == 400


def test_update_nonexistent_workstream(client, human_headers):
    r = client.put("/api/workstreams/nonexistent999",
                   json={"title_en": "X"}, headers=human_headers)
    assert r.status_code == 404


def test_delete_nonexistent_workstream(client, human_headers):
    r = client.delete("/api/workstreams/nonexistent999",
                      headers=human_headers)
    assert r.status_code == 404


def test_get_bug_nonexistent(client):
    r = client.get("/api/bugs/nonexistent999")
    assert r.status_code == 404


def test_update_bug_nonexistent(client, human_headers):
    r = client.put("/api/bugs/nonexistent999", json={"title": "X"},
                   headers=human_headers)
    assert r.status_code == 404


def test_task_invalid_status_422(client, human_headers):
    """Invalid status literal returns 422."""
    pid, wsid, tid = _scaffold(client, human_headers, "BadStatus")
    r = client.put(f"/api/tasks/{tid}", json={"status": "invalid_status"},
                   headers=human_headers)
    assert r.status_code == 422


def test_workstream_invalid_priority_422(client, human_headers):
    """Invalid priority literal returns 422."""
    pid = _make_project(client, human_headers, "BadPri")
    wsid = _make_ws(client, human_headers, pid)
    r = client.put(f"/api/workstreams/{wsid}",
                   json={"priority": "ultra_high"}, headers=human_headers)
    assert r.status_code == 422


# ══════════════════════════════════════════════════════════════════════════
# 4. Bug CRUD extended
# ══════════════════════════════════════════════════════════════════════════

def test_bug_update_severity(client, human_headers):
    pid = _make_project(client, human_headers, "BugSev")
    bug_id = client.post("/api/bugs", json={
        "title": "Sev Bug", "severity": "low", "project_id": pid
    }, headers=human_headers).json()["id"]
    r = client.put(f"/api/bugs/{bug_id}", json={"severity": "critical"},
                   headers=human_headers)
    assert r.status_code == 200
    bug = client.get(f"/api/bugs/{bug_id}").json()
    assert bug["severity"] == "critical"


def test_bug_update_status_lifecycle(client, human_headers):
    pid = _make_project(client, human_headers, "BugStatus")
    bug_id = client.post("/api/bugs", json={
        "title": "Status Bug", "severity": "medium", "project_id": pid
    }, headers=human_headers).json()["id"]
    for status in ["investigating", "fixing", "fix_complete", "to_verify", "resolved", "closed"]:
        r = client.put(f"/api/bugs/{bug_id}", json={"status": status},
                       headers=human_headers)
        assert r.status_code == 200
    bug = client.get(f"/api/bugs/{bug_id}").json()
    assert bug["status"] == "closed"
    assert bug["resolved_at"] is not None


def test_bug_list_by_project(client, human_headers):
    pid = _make_project(client, human_headers, "BugListP")
    client.post("/api/bugs", json={
        "title": "B1", "severity": "high", "project_id": pid
    }, headers=human_headers)
    client.post("/api/bugs", json={
        "title": "B2", "severity": "low", "project_id": pid
    }, headers=human_headers)
    bugs = client.get(f"/api/bugs?project_id={pid}").json()
    assert len(bugs) >= 2
    # high severity should come first
    assert bugs[0]["severity"] == "high"


def test_bug_list_by_status(client, human_headers):
    pid = _make_project(client, human_headers, "BugListS")
    bug_id = client.post("/api/bugs", json={
        "title": "BLS", "severity": "medium", "project_id": pid
    }, headers=human_headers).json()["id"]
    client.put(f"/api/bugs/{bug_id}", json={"status": "resolved"},
               headers=human_headers)
    bugs = client.get("/api/bugs?status=resolved").json()
    assert any(b["id"] == bug_id for b in bugs)


def test_bug_delete_soft(client, human_headers):
    pid = _make_project(client, human_headers, "BugDel")
    bug_id = client.post("/api/bugs", json={
        "title": "Del Bug", "severity": "low", "project_id": pid
    }, headers=human_headers).json()["id"]
    r = client.delete(f"/api/bugs/{bug_id}", headers=human_headers)
    assert r.status_code == 200
    r = client.get(f"/api/bugs/{bug_id}")
    assert r.status_code == 404


def test_bug_delete_nonexistent(client, human_headers):
    r = client.delete("/api/bugs/nonexistent999", headers=human_headers)
    assert r.status_code == 404


def test_bug_link_nonexistent_bug(client, human_headers):
    r = client.get("/api/bugs/nonexistent999/tasks")
    assert r.status_code == 404


def test_bug_unlink_nonexistent(client, human_headers):
    r = client.delete("/api/bugs/nonexistent/tasks/nonexistent",
                      headers=human_headers)
    assert r.status_code == 404


def test_bug_suggest_links(client, human_headers):
    pid = _make_project(client, human_headers, "SuggestP")
    wsid = _make_ws(client, human_headers, pid, "Login Feature")
    _make_task(client, human_headers, wsid, "Fix login page")
    bug_id = client.post("/api/bugs", json={
        "title": "Login fails", "severity": "high", "project_id": pid,
        "description": "Login page crashes"
    }, headers=human_headers).json()["id"]
    r = client.get(f"/api/bugs/{bug_id}/suggest-links")
    assert r.status_code == 200
    assert "workstreams" in r.json()
    assert "tasks" in r.json()


def test_task_linked_bugs_nonexistent(client):
    r = client.get("/api/tasks/nonexistent999/bugs")
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# 5. Comments
# ══════════════════════════════════════════════════════════════════════════

def test_comment_create_and_list(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "CmtProj")
    r = client.post(f"/api/comments/task/{tid}", json={"body": "Hello!"},
                    headers=human_headers)
    assert r.status_code == 200
    cid = r.json()["id"]
    r = client.get(f"/api/comments/task/{tid}")
    assert r.status_code == 200
    comments = r.json()["comments"]
    assert any(c["id"] == cid for c in comments)
    assert comments[0]["body"] == "Hello!"


def test_comment_on_nonexistent_task(client, human_headers):
    """Commenting on non-existent entity still works (no FK check)."""
    r = client.post("/api/comments/task/nonexistent999",
                    json={"body": "Ghost comment"}, headers=human_headers)
    # The comment route does not validate entity existence — just inserts
    assert r.status_code == 200


def test_comment_invalid_entity_type(client, human_headers):
    r = client.post("/api/comments/invalid_type/abc",
                    json={"body": "Test"}, headers=human_headers)
    assert r.status_code == 400


def test_comment_list_invalid_entity_type(client):
    r = client.get("/api/comments/invalid_type/abc")
    assert r.status_code == 400


def test_comment_on_bug(client, human_headers):
    pid = _make_project(client, human_headers, "CmtBug")
    bug_id = client.post("/api/bugs", json={
        "title": "CmtBug", "severity": "low", "project_id": pid
    }, headers=human_headers).json()["id"]
    r = client.post(f"/api/comments/bug/{bug_id}",
                    json={"body": "Bug comment"}, headers=human_headers)
    assert r.status_code == 200


def test_comment_on_blocker(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "CmtBlocker")
    bid = client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "Blocked!"
    }, headers=human_headers).json()["id"]
    r = client.post(f"/api/comments/blocker/{bid}",
                    json={"body": "Blocker comment"}, headers=human_headers)
    assert r.status_code == 200


def test_comment_activity_included(client, human_headers):
    """Comment listing includes activity log entries."""
    pid, wsid, tid = _scaffold(client, human_headers, "CmtAct")
    client.post(f"/api/comments/task/{tid}", json={"body": "With activity"},
                headers=human_headers)
    r = client.get(f"/api/comments/task/{tid}")
    data = r.json()
    assert "activity" in data


# ══════════════════════════════════════════════════════════════════════════
# 6. Time tracking
# ══════════════════════════════════════════════════════════════════════════

def test_time_log_and_list(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "TimeLog")
    r = client.post(f"/api/tasks/{tid}/time", json={
        "minutes": 30, "description": "Code review"
    }, headers=human_headers)
    assert r.status_code == 200
    eid = r.json()["id"]
    entries = client.get(f"/api/tasks/{tid}/time").json()
    assert any(e["id"] == eid for e in entries)
    assert entries[0]["minutes"] == 30


def test_time_log_invalid_minutes_zero(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "TimeZero")
    r = client.post(f"/api/tasks/{tid}/time", json={
        "minutes": 0, "description": "Bad"
    }, headers=human_headers)
    assert r.status_code == 422


def test_time_log_invalid_minutes_too_high(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "TimeHigh")
    r = client.post(f"/api/tasks/{tid}/time", json={
        "minutes": 1441, "description": "Too much"
    }, headers=human_headers)
    assert r.status_code == 422


def test_time_log_nonexistent_task(client, human_headers):
    r = client.post("/api/tasks/nonexistent999/time", json={
        "minutes": 10, "description": "Ghost"
    }, headers=human_headers)
    assert r.status_code == 404


def test_time_entry_delete(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "TimeDel")
    eid = client.post(f"/api/tasks/{tid}/time", json={
        "minutes": 15, "description": "Delete me"
    }, headers=human_headers).json()["id"]
    r = client.delete(f"/api/time-entries/{eid}", headers=human_headers)
    assert r.status_code == 200
    entries = client.get(f"/api/tasks/{tid}/time").json()
    assert not any(e["id"] == eid for e in entries)


def test_time_entry_delete_nonexistent(client, human_headers):
    r = client.delete("/api/time-entries/nonexistent999",
                      headers=human_headers)
    assert r.status_code == 404


def test_time_report(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "TimeRpt")
    client.post(f"/api/tasks/{tid}/time", json={
        "minutes": 45, "description": "Report entry"
    }, headers=human_headers)
    r = client.get("/api/time-report")
    assert r.status_code == 200
    data = r.json()
    assert "entries" in data
    assert "total_minutes" in data
    assert "by_user" in data
    assert data["total_minutes"] >= 45


def test_time_report_filter_by_project(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "TimeRptF")
    client.post(f"/api/tasks/{tid}/time", json={
        "minutes": 20, "description": "Filtered"
    }, headers=human_headers)
    r = client.get(f"/api/time-report?project_id={pid}")
    assert r.status_code == 200
    assert r.json()["total_minutes"] >= 20


# ══════════════════════════════════════════════════════════════════════════
# 7. Blockers
# ══════════════════════════════════════════════════════════════════════════

def test_blocker_create_and_list(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "BlockerCL")
    bid = client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "Need API key"
    }, headers=human_headers).json()["id"]
    blockers = client.get(f"/api/blockers?workstream_id={wsid}").json()
    assert any(b["id"] == bid for b in blockers)


def test_blocker_resolve(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "BlockerRes")
    bid = client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "Resolve me"
    }, headers=human_headers).json()["id"]
    r = client.put(f"/api/blockers/{bid}/resolve", headers=human_headers)
    assert r.status_code == 200
    # Resolved blockers excluded from active_only=True list
    blockers = client.get(f"/api/blockers?workstream_id={wsid}").json()
    assert not any(b["id"] == bid for b in blockers)
    # But appear when active_only=False
    all_blockers = client.get(
        f"/api/blockers?workstream_id={wsid}&active_only=false").json()
    assert any(b["id"] == bid for b in all_blockers)


def test_blocker_resolve_nonexistent(client, human_headers):
    r = client.put("/api/blockers/nonexistent999/resolve",
                   headers=human_headers)
    assert r.status_code == 404


def test_blocker_with_assignee_and_notes(client, human_headers):
    """Blockers can carry assignee + notes (v1.4.5 promoted them to first-class)."""
    pid, wsid, _ = _scaffold(client, human_headers, "BlockerAN")
    bid = client.post("/api/blockers", json={
        "workstream_id": wsid,
        "description_en": "Motor 6 encoder error",
        "assignee": "luoxiao.min",
        "notes": "Waiting on hardware replacement",
    }, headers=human_headers).json()["id"]

    # List endpoint returns new fields
    blockers = client.get(f"/api/blockers?workstream_id={wsid}").json()
    b = next(x for x in blockers if x["id"] == bid)
    assert b["assignee"] == "luoxiao.min"
    assert b["notes"] == "Waiting on hardware replacement"

    # Dashboard payload includes them
    r = client.get("/api/dashboard", headers=human_headers).json()
    db_blocker = next(
        b for p in r if p["id"] == pid
        for w in p["workstreams"] if w["id"] == wsid
        for b in w["blockers"] if b["id"] == bid
    )
    assert db_blocker["assignee"] == "luoxiao.min"
    assert db_blocker["notes"] == "Waiting on hardware replacement"


def test_blocker_update(client, human_headers):
    """PUT /api/blockers/{id} updates assignee/notes/description."""
    pid, wsid, _ = _scaffold(client, human_headers, "BlockerUpd")
    bid = client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "Initial"
    }, headers=human_headers).json()["id"]

    r = client.put(f"/api/blockers/{bid}", json={
        "assignee": "alice",
        "notes": "持续观察",
        "description_en": "LiDAR overheating",
    }, headers=human_headers)
    assert r.status_code == 200

    blockers = client.get(f"/api/blockers?workstream_id={wsid}").json()
    b = next(x for x in blockers if x["id"] == bid)
    assert b["assignee"] == "alice"
    assert b["notes"] == "持续观察"
    assert b["description_en"] == "LiDAR overheating"


def test_blocker_list_all(client, human_headers):
    """List blockers without workstream filter."""
    r = client.get("/api/blockers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ══════════════════════════════════════════════════════════════════════════
# 8. Dependencies
# ══════════════════════════════════════════════════════════════════════════

def test_dependency_create_and_check(client, human_headers):
    pid = _make_project(client, human_headers, "DepProj")
    wsid = _make_ws(client, human_headers, pid)
    t1 = _make_task(client, human_headers, wsid, "Dep Task 1")
    t2 = _make_task(client, human_headers, wsid, "Dep Task 2")
    # t2 depends on t1
    r = client.post(f"/api/tasks/{t2}/dependencies", json={
        "depends_on_id": t1, "dep_type": "blocked_by"
    }, headers=human_headers)
    assert r.status_code == 200
    dep_id = r.json()["id"]

    # Check deps
    deps = client.get(f"/api/tasks/{t2}/dependencies").json()
    assert len(deps["blocked_by"]) == 1
    assert deps["blocked_by"][0]["id"] == t1

    # Dependency check: t1 not done, so can_start=False
    check = client.get(f"/api/tasks/{t2}/dependency-check").json()
    assert check["can_start"] is False
    assert len(check["unmet"]) == 1

    # Mark t1 done
    client.put(f"/api/tasks/{t1}", json={"status": "done"},
               headers=human_headers)
    check = client.get(f"/api/tasks/{t2}/dependency-check").json()
    assert check["can_start"] is True
    assert len(check["unmet"]) == 0

    # Remove dependency
    r = client.delete(f"/api/tasks/{t2}/dependencies/{dep_id}",
                      headers=human_headers)
    assert r.status_code == 200


def test_dependency_self_reference(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "DepSelf")
    r = client.post(f"/api/tasks/{tid}/dependencies", json={
        "depends_on_id": tid
    }, headers=human_headers)
    assert r.status_code == 400


def test_dependency_nonexistent_task(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "DepNone")
    r = client.post(f"/api/tasks/{tid}/dependencies", json={
        "depends_on_id": "nonexistent999"
    }, headers=human_headers)
    assert r.status_code == 404


def test_dependency_get_nonexistent_task(client):
    r = client.get("/api/tasks/nonexistent999/dependencies")
    assert r.status_code == 404


def test_dependency_duplicate(client, human_headers):
    pid = _make_project(client, human_headers, "DepDup")
    wsid = _make_ws(client, human_headers, pid)
    t1 = _make_task(client, human_headers, wsid, "DD1")
    t2 = _make_task(client, human_headers, wsid, "DD2")
    client.post(f"/api/tasks/{t2}/dependencies", json={
        "depends_on_id": t1
    }, headers=human_headers)
    r = client.post(f"/api/tasks/{t2}/dependencies", json={
        "depends_on_id": t1
    }, headers=human_headers)
    assert r.status_code == 409


def test_dependency_related_type(client, human_headers):
    pid = _make_project(client, human_headers, "DepRel")
    wsid = _make_ws(client, human_headers, pid)
    t1 = _make_task(client, human_headers, wsid, "Rel1")
    t2 = _make_task(client, human_headers, wsid, "Rel2")
    r = client.post(f"/api/tasks/{t2}/dependencies", json={
        "depends_on_id": t1, "dep_type": "related"
    }, headers=human_headers)
    assert r.status_code == 200
    deps = client.get(f"/api/tasks/{t2}/dependencies").json()
    assert len(deps["related"]) == 1


def test_dependency_remove_nonexistent(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "DepRemNone")
    r = client.delete(f"/api/tasks/{tid}/dependencies/nonexistent999",
                      headers=human_headers)
    assert r.status_code == 404


def test_task_update_doing_warns_unmet_deps(client, human_headers):
    """Setting status to 'doing' returns warnings about unmet deps."""
    pid = _make_project(client, human_headers, "DepWarn")
    wsid = _make_ws(client, human_headers, pid)
    t1 = _make_task(client, human_headers, wsid, "Blocker Task")
    t2 = _make_task(client, human_headers, wsid, "Dependent Task")
    client.post(f"/api/tasks/{t2}/dependencies", json={
        "depends_on_id": t1, "dep_type": "blocked_by"
    }, headers=human_headers)
    r = client.put(f"/api/tasks/{t2}", json={"status": "doing"},
                   headers=human_headers)
    assert r.status_code == 200
    assert len(r.json()["warnings"]) == 1


# ══════════════════════════════════════════════════════════════════════════
# 9. Recurring tasks
# ══════════════════════════════════════════════════════════════════════════

def test_recurring_task_crud(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "RecurCRUD")
    r = client.post("/api/recurring-tasks", json={
        "workstream_id": wsid, "title_en": "Daily standup",
        "schedule": "daily"
    }, headers=human_headers)
    assert r.status_code == 200
    rid = r.json()["id"]

    # List
    recs = client.get(f"/api/recurring-tasks?workstream_id={wsid}").json()
    assert any(rt["id"] == rid for rt in recs)

    # Update
    r = client.put(f"/api/recurring-tasks/{rid}",
                   json={"title_en": "Morning standup"},
                   headers=human_headers)
    assert r.status_code == 200

    # Delete
    r = client.delete(f"/api/recurring-tasks/{rid}", headers=human_headers)
    assert r.status_code == 200


def test_recurring_task_check_trigger(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "RecurTrig")
    client.post("/api/recurring-tasks", json={
        "workstream_id": wsid, "title_en": "Triggered task",
        "schedule": "daily"
    }, headers=human_headers)
    r = client.post("/api/recurring-tasks/check", headers=human_headers)
    assert r.status_code == 200
    assert "created" in r.json()


def test_recurring_task_nonexistent_workstream(client, human_headers):
    r = client.post("/api/recurring-tasks", json={
        "workstream_id": "nonexistent999", "title_en": "Ghost",
        "schedule": "daily"
    }, headers=human_headers)
    assert r.status_code == 404


def test_recurring_task_update_nonexistent(client, human_headers):
    r = client.put("/api/recurring-tasks/nonexistent999",
                   json={"title_en": "X"}, headers=human_headers)
    assert r.status_code == 404


def test_recurring_task_delete_nonexistent(client, human_headers):
    r = client.delete("/api/recurring-tasks/nonexistent999",
                      headers=human_headers)
    assert r.status_code == 404


def test_recurring_task_update_no_fields(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "RecurNoF")
    rid = client.post("/api/recurring-tasks", json={
        "workstream_id": wsid, "title_en": "NoF",
        "schedule": "weekly"
    }, headers=human_headers).json()["id"]
    r = client.put(f"/api/recurring-tasks/{rid}", json={},
                   headers=human_headers)
    assert r.status_code == 400


def test_recurring_task_weekly_schedule(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "RecurWeek")
    r = client.post("/api/recurring-tasks", json={
        "workstream_id": wsid, "title_en": "Weekly review",
        "schedule": "weekly", "day_of_week": 1
    }, headers=human_headers)
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 10. Analytics
# ══════════════════════════════════════════════════════════════════════════

def test_analytics_bug_counts(client, human_headers):
    r = client.get("/api/analytics/bugs?days=7")
    assert r.status_code == 200
    data = r.json()
    assert "opened" in data
    assert "closed" in data


def test_analytics_workload(client, human_headers):
    r = client.get("/api/analytics/workload")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_analytics_blocker_aging(client, human_headers):
    r = client.get("/api/analytics/blockers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_analytics_activity_log(client, human_headers):
    r = client.get("/api/analytics/activity?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_analytics_activity_filter_by_type(client, human_headers):
    r = client.get("/api/analytics/activity?entity_type=task&limit=5")
    assert r.status_code == 200


def test_analytics_snapshot_idempotent(client, human_headers):
    """Snapshot is idempotent — calling twice on same day works."""
    r1 = client.post("/api/analytics/snapshot", headers=human_headers)
    assert r1.status_code == 200
    r2 = client.post("/api/analytics/snapshot", headers=human_headers)
    assert r2.status_code == 200
    assert r1.json()["date"] == r2.json()["date"]


def test_analytics_snapshot_totals(client, human_headers):
    """Snapshot includes totals."""
    client.post("/api/analytics/snapshot", headers=human_headers)
    data = client.get("/api/analytics?days=1").json()
    assert len(data) >= 1
    assert "totals" in data[-1]
    totals = data[-1]["totals"]
    assert "total" in totals


# ══════════════════════════════════════════════════════════════════════════
# 11. Bin (soft delete + restore)
# ══════════════════════════════════════════════════════════════════════════

def test_bin_list(client):
    r = client.get("/api/bin")
    assert r.status_code == 200
    data = r.json()
    assert "projects" in data
    assert "workstreams" in data
    assert "tasks" in data
    assert "blockers" in data
    assert "bugs" in data


def test_bin_delete_project_cascade_restore(client, human_headers):
    """Deleting a project cascades to workstreams + tasks; restore cascades back."""
    pid = _make_project(client, human_headers, "BinCascade")
    wsid = _make_ws(client, human_headers, pid, "BinWS")
    tid = _make_task(client, human_headers, wsid, "BinTask")
    bid = client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "BinBlocker"
    }, headers=human_headers).json()["id"]

    # Delete project (cascade)
    client.delete(f"/api/projects/{pid}", headers=human_headers)

    # All in bin
    bin_data = client.get("/api/bin").json()
    assert any(p["id"] == pid for p in bin_data["projects"])
    assert any(w["id"] == wsid for w in bin_data["workstreams"])
    assert any(t["id"] == tid for t in bin_data["tasks"])

    # Restore project (cascade)
    r = client.post(f"/api/projects/{pid}/restore", headers=human_headers)
    assert r.status_code == 200

    # All restored
    dash = client.get("/api/dashboard").json()
    proj = next((p for p in dash if p["id"] == pid), None)
    assert proj is not None
    assert len(proj["workstreams"]) >= 1


def test_bin_restore_nonexistent(client, human_headers):
    r = client.post("/api/projects/nonexistent999/restore",
                    headers=human_headers)
    assert r.status_code == 404


def test_bin_restore_invalid_type(client, human_headers):
    r = client.post("/api/invalid_type/abc/restore",
                    headers=human_headers)
    assert r.status_code == 400


def test_bin_purge(client, human_headers):
    """Purge permanently deletes a binned item."""
    pid = _make_project(client, human_headers, "PurgeMe")
    client.delete(f"/api/projects/{pid}", headers=human_headers)
    r = client.delete(f"/api/projects/{pid}/purge", headers=human_headers)
    assert r.status_code == 200
    # Cannot restore after purge
    r = client.post(f"/api/projects/{pid}/restore", headers=human_headers)
    assert r.status_code == 404


def test_bin_purge_nonexistent(client, human_headers):
    r = client.delete("/api/projects/nonexistent999/purge",
                      headers=human_headers)
    assert r.status_code == 404


def test_bin_purge_invalid_type(client, human_headers):
    r = client.delete("/api/invalid_type/abc/purge",
                      headers=human_headers)
    assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# 12. Users
# ══════════════════════════════════════════════════════════════════════════

def test_user_create_and_list(client, human_headers):
    r = client.post("/api/users", json={
        "name": "new-test-user-42", "display_name": "Test User 42",
        "role": "human"
    })
    assert r.status_code == 200
    uid = r.json()["id"]
    users = client.get("/api/users").json()
    assert any(u["name"] == "new-test-user-42" for u in users)


def test_user_create_duplicate_returns_existing(client):
    """Creating a user with same name returns existing ID."""
    r1 = client.post("/api/users", json={"name": "dup-user-99"})
    uid1 = r1.json()["id"]
    r2 = client.post("/api/users", json={"name": "dup-user-99"})
    assert r2.json()["id"] == uid1
    assert r2.json().get("existing") is True


def test_user_update(client, human_headers):
    r = client.post("/api/users", json={"name": "upd-user-99"})
    uid = r.json()["id"]
    r = client.put(f"/api/users/{uid}",
                   json={"display_name": "Updated Name"},
                   headers=human_headers)
    assert r.status_code == 200


def test_user_update_nonexistent(client, human_headers):
    r = client.put("/api/users/nonexistent999",
                   json={"display_name": "X"}, headers=human_headers)
    assert r.status_code == 404


def test_user_notification_prefs(client, human_headers):
    r = client.post("/api/users", json={"name": "notif-user-99"})
    uid = r.json()["id"]
    # Get defaults
    r = client.get(f"/api/users/{uid}/notifications")
    assert r.status_code == 200
    assert r.json()["channel"] == "feishu"
    # Update
    r = client.put(f"/api/users/{uid}/notifications",
                   json={"stale_days": 7}, headers=human_headers)
    assert r.status_code == 200
    # Verify
    r = client.get(f"/api/users/{uid}/notifications")
    assert r.json()["stale_days"] == 7


def test_user_notification_prefs_nonexistent(client):
    r = client.get("/api/users/nonexistent999/notifications")
    assert r.status_code == 404


def test_user_activity(client, human_headers):
    r = client.post("/api/users", json={"name": "act-user-99"})
    uid = r.json()["id"]
    r = client.get(f"/api/users/{uid}/activity")
    assert r.status_code == 200


def test_user_activity_nonexistent(client):
    r = client.get("/api/users/nonexistent999/activity")
    assert r.status_code == 404


# ══════════════════════════════════════════════════════════════════════════
# 13. Bot governance (extended)
# ══════════════════════════════════════════════════════════════════════════

def test_bot_cannot_create_workstream(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotWS")
    r = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "Bot WS"
    }, headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_delete_project(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotDelP")
    r = client.delete(f"/api/projects/{pid}", headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_delete_workstream(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotDelWS")
    wsid = _make_ws(client, human_headers, pid)
    r = client.delete(f"/api/workstreams/{wsid}", headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_delete_bug(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotDelBug")
    bug_id = client.post("/api/bugs", json={
        "title": "Bot Bug", "severity": "low", "project_id": pid
    }, headers=human_headers).json()["id"]
    r = client.delete(f"/api/bugs/{bug_id}", headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_change_workstream_priority(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotPriWS")
    wsid = _make_ws(client, human_headers, pid)
    r = client.put(f"/api/workstreams/{wsid}",
                   json={"priority": "critical"}, headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_change_user_role(client, human_headers, bot_headers):
    r = client.post("/api/users", json={"name": "role-target"})
    uid = r.json()["id"]
    r = client.put(f"/api/users/{uid}", json={"role": "bot"},
                   headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_bulk_delete(client, human_headers, bot_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "BotBulkDel")
    r = client.post("/api/tasks/bulk", json={
        "task_ids": [tid], "action": "delete"
    }, headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_bulk_mark_done(client, human_headers, bot_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "BotBulkDone")
    r = client.post("/api/tasks/bulk", json={
        "task_ids": [tid], "action": "update",
        "fields": {"status": "done"}
    }, headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_restore_from_bin(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotRestore")
    client.delete(f"/api/projects/{pid}", headers=human_headers)
    r = client.post(f"/api/projects/{pid}/restore", headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_purge_from_bin(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotPurge")
    client.delete(f"/api/projects/{pid}", headers=human_headers)
    r = client.delete(f"/api/projects/{pid}/purge", headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_set_wip_limits(client, human_headers, bot_headers):
    pid = _make_project(client, human_headers, "BotWIP")
    r = client.put(f"/api/projects/{pid}/wip-limits",
                   json={"doing": 3}, headers=bot_headers)
    assert r.status_code == 403


def test_bot_can_update_task_status_non_done(client, human_headers, bot_headers):
    """Bot can set doing, in_review, blocked."""
    pid, wsid, tid = _scaffold(client, human_headers, "BotOK")
    for status in ["doing", "in_review", "blocked"]:
        r = client.put(f"/api/tasks/{tid}", json={"status": status},
                       headers=bot_headers)
        assert r.status_code == 200


def test_bot_can_create_bug(client, human_headers, bot_headers):
    """Bots can report bugs."""
    pid = _make_project(client, human_headers, "BotBugCreate")
    r = client.post("/api/bugs", json={
        "title": "Bot found bug", "severity": "low", "project_id": pid
    }, headers=bot_headers)
    assert r.status_code == 200


def test_bot_can_create_blocker(client, human_headers, bot_headers):
    """Bots can create blockers."""
    pid, wsid, _ = _scaffold(client, human_headers, "BotBlocker")
    r = client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "Bot blocked"
    }, headers=bot_headers)
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 14. Templates
# ══════════════════════════════════════════════════════════════════════════

def test_template_create_list_delete(client, human_headers):
    r = client.post("/api/templates", json={
        "name": "Sprint Template",
        "structure": [
            {"title_en": "Design", "assignee": "alice"},
            {"title_en": "Implement", "assignee": "bob"},
            {"title_en": "Test", "assignee": "carol"}
        ]
    }, headers=human_headers)
    assert r.status_code == 200
    tmpl_id = r.json()["id"]

    # List
    templates = client.get("/api/templates").json()
    assert any(t["id"] == tmpl_id for t in templates)

    # Delete
    r = client.delete(f"/api/templates/{tmpl_id}", headers=human_headers)
    assert r.status_code == 200


def test_template_apply(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "TmplApply")
    tmpl_id = client.post("/api/templates", json={
        "name": "Apply Template",
        "project_id": pid,
        "structure": [
            {"title_en": "Step 1"},
            {"title_en": "Step 2", "subtasks": [
                {"title_en": "Sub 2a"},
                {"title_en": "Sub 2b"}
            ]}
        ]
    }, headers=human_headers).json()["id"]

    r = client.post(f"/api/templates/{tmpl_id}/apply", json={
        "workstream_id": wsid
    }, headers=human_headers)
    assert r.status_code == 200
    assert r.json()["created"] == 2
    assert len(r.json()["task_ids"]) == 2


def test_template_apply_nonexistent(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "TmplNone")
    r = client.post("/api/templates/nonexistent999/apply", json={
        "workstream_id": wsid
    }, headers=human_headers)
    assert r.status_code == 404


def test_template_delete_nonexistent(client, human_headers):
    r = client.delete("/api/templates/nonexistent999",
                      headers=human_headers)
    assert r.status_code == 404


def test_template_list_by_project(client, human_headers):
    pid = _make_project(client, human_headers, "TmplFilt")
    client.post("/api/templates", json={
        "name": "Proj Template", "project_id": pid,
        "structure": [{"title_en": "Task"}]
    }, headers=human_headers)
    templates = client.get(f"/api/templates?project_id={pid}").json()
    assert len(templates) >= 1


# ══════════════════════════════════════════════════════════════════════════
# 15. Sync conflicts
# ══════════════════════════════════════════════════════════════════════════

def test_sync_conflict_count(client):
    r = client.get("/api/sync-conflicts/count")
    assert r.status_code == 200
    assert "unresolved" in r.json()


def test_sync_conflict_list(client):
    r = client.get("/api/sync-conflicts")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_sync_conflict_list_resolved(client):
    r = client.get("/api/sync-conflicts?resolved=true")
    assert r.status_code == 200


def test_sync_conflict_create_and_resolve(client, human_headers):
    """Manually insert a conflict and resolve it."""
    from db import get_db
    from helpers import now_iso
    import uuid
    pid, wsid, tid = _scaffold(client, human_headers, "ConflictP")
    cid = str(uuid.uuid4())[:8]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sync_conflicts (id, entity_type, entity_id, field_name, "
            "local_value, remote_value, created_at) VALUES (?,?,?,?,?,?,?)",
            (cid, "task", tid, "title_en", "Local Title", "Remote Title",
             now_iso())
        )
    # Count
    count = client.get("/api/sync-conflicts/count").json()["unresolved"]
    assert count >= 1

    # Resolve with local
    r = client.put(f"/api/sync-conflicts/{cid}/resolve", json={
        "resolution": "local"
    }, headers=human_headers)
    assert r.status_code == 200

    # Count decreased
    new_count = client.get("/api/sync-conflicts/count").json()["unresolved"]
    assert new_count < count


def test_sync_conflict_resolve_nonexistent(client, human_headers):
    r = client.put("/api/sync-conflicts/nonexistent999/resolve", json={
        "resolution": "local"
    }, headers=human_headers)
    assert r.status_code == 404


def test_sync_conflict_resolve_all(client, human_headers):
    r = client.post("/api/sync-conflicts/resolve-all", json={
        "resolution": "local"
    }, headers=human_headers)
    assert r.status_code == 200
    assert "resolved" in r.json()


# ══════════════════════════════════════════════════════════════════════════
# 16. Alerts
# ══════════════════════════════════════════════════════════════════════════

def test_alerts_list(client):
    r = client.get("/api/alerts")
    assert r.status_code == 200
    data = r.json()
    assert "overdue" in data
    assert "stale" in data
    assert "aging_blockers" in data
    assert "total" in data


def test_alerts_summary(client):
    r = client.get("/api/alerts/summary")
    assert r.status_code == 200


def test_alerts_filter_by_assignee(client):
    r = client.get("/api/alerts?assignee=nobody-has-this")
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 17. Workstream CRUD extended
# ══════════════════════════════════════════════════════════════════════════

def test_workstream_list_by_project(client, human_headers):
    pid = _make_project(client, human_headers, "WSList")
    wsid = _make_ws(client, human_headers, pid, "WSListItem")
    ws_list = client.get(f"/api/workstreams?project_id={pid}").json()
    assert any(w["id"] == wsid for w in ws_list)


def test_workstream_update(client, human_headers):
    pid = _make_project(client, human_headers, "WSUpd")
    wsid = _make_ws(client, human_headers, pid)
    r = client.put(f"/api/workstreams/{wsid}",
                   json={"title_en": "Updated WS", "status": "in-progress"},
                   headers=human_headers)
    assert r.status_code == 200


def test_workstream_update_no_fields(client, human_headers):
    pid = _make_project(client, human_headers, "WSNoF")
    wsid = _make_ws(client, human_headers, pid)
    r = client.put(f"/api/workstreams/{wsid}", json={},
                   headers=human_headers)
    assert r.status_code == 400


def test_workstream_delete_cascade(client, human_headers):
    """Deleting workstream cascades to tasks and blockers."""
    pid = _make_project(client, human_headers, "WSDelCasc")
    wsid = _make_ws(client, human_headers, pid, "CascWS")
    tid = _make_task(client, human_headers, wsid, "CascTask")
    client.delete(f"/api/workstreams/{wsid}", headers=human_headers)
    # Task should be soft-deleted
    dash = client.get("/api/dashboard").json()
    proj = next(p for p in dash if p["id"] == pid)
    assert len(proj["workstreams"]) == 0


# ══════════════════════════════════════════════════════════════════════════
# 18. Task CRUD extended
# ══════════════════════════════════════════════════════════════════════════

def test_task_list_filter_by_assignee(client, human_headers):
    pid, wsid, _ = _scaffold(client, human_headers, "TaskFilt")
    _make_task(client, human_headers, wsid, "Assigned", assignee="alice-99")
    tasks = client.get("/api/tasks?assignee=alice-99").json()
    assert any(t["title_en"] == "Assigned" for t in tasks)


def test_task_list_filter_by_status(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "TaskStat")
    client.put(f"/api/tasks/{tid}", json={"status": "doing"},
               headers=human_headers)
    tasks = client.get("/api/tasks?status=doing").json()
    assert any(t["id"] == tid for t in tasks)


def test_task_subtasks(client, human_headers):
    pid, wsid, parent_tid = _scaffold(client, human_headers, "SubTask")
    sub_tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Sub Task",
        "parent_task_id": parent_tid
    }, headers=human_headers).json()["id"]
    subs = client.get(f"/api/tasks/{parent_tid}/subtasks").json()
    assert any(s["id"] == sub_tid for s in subs)


def test_task_bulk_update(client, human_headers):
    pid = _make_project(client, human_headers, "BulkUpd")
    wsid = _make_ws(client, human_headers, pid)
    t1 = _make_task(client, human_headers, wsid, "BU1")
    t2 = _make_task(client, human_headers, wsid, "BU2")
    r = client.post("/api/tasks/bulk", json={
        "task_ids": [t1, t2], "action": "update",
        "fields": {"status": "doing"}
    }, headers=human_headers)
    assert r.status_code == 200
    assert r.json()["affected"] == 2


def test_task_bulk_invalid_action(client, human_headers):
    r = client.post("/api/tasks/bulk", json={
        "task_ids": ["abc"], "action": "invalid"
    }, headers=human_headers)
    assert r.status_code == 422


def test_task_bulk_no_task_ids(client, human_headers):
    r = client.post("/api/tasks/bulk", json={
        "task_ids": [], "action": "update",
        "fields": {"status": "doing"}
    }, headers=human_headers)
    assert r.status_code == 422


def test_task_bulk_invalid_fields(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "BulkBadF")
    r = client.post("/api/tasks/bulk", json={
        "task_ids": [tid], "action": "update",
        "fields": {"invalid_field": "value"}
    }, headers=human_headers)
    assert r.status_code == 400


# ══════════════════════════════════════════════════════════════════════════
# 19. Attachments (metadata only — no actual file upload in tests)
# ══════════════════════════════════════════════════════════════════════════

def test_attachment_list_empty(client, human_headers):
    pid, wsid, tid = _scaffold(client, human_headers, "AttachList")
    r = client.get(f"/api/attachments/task/{tid}")
    assert r.status_code == 200
    assert r.json() == []


def test_attachment_upload_invalid_entity_type(client, human_headers):
    """Invalid entity type for upload returns 400."""
    from io import BytesIO
    r = client.post("/api/attachments/invalid_type/abc",
                    files={"file": ("test.txt", BytesIO(b"hello"), "text/plain")},
                    headers={"X-Kanban-User": "test-human"})
    assert r.status_code == 400


def test_attachment_upload_nonexistent_entity(client, human_headers):
    """Upload to nonexistent task returns 404."""
    from io import BytesIO
    r = client.post("/api/attachments/task/nonexistent999",
                    files={"file": ("test.txt", BytesIO(b"hello"), "text/plain")},
                    headers={"X-Kanban-User": "test-human"})
    assert r.status_code == 404


def test_attachment_download_nonexistent(client):
    r = client.get("/api/attachments/download/nonexistent999")
    assert r.status_code == 404


def test_attachment_delete_nonexistent(client, human_headers):
    r = client.delete("/api/attachments/nonexistent999",
                      headers=human_headers)
    assert r.status_code == 404


def test_attachment_upload_and_list(client, human_headers):
    """Upload a file and verify it appears in listing."""
    from io import BytesIO
    pid, wsid, tid = _scaffold(client, human_headers, "AttachUpload")
    r = client.post(f"/api/attachments/task/{tid}",
                    files={"file": ("test.txt", BytesIO(b"test content"), "text/plain")},
                    headers={"X-Kanban-User": "test-human"})
    assert r.status_code == 200
    aid = r.json()["id"]
    assert r.json()["size_bytes"] == len(b"test content")

    listing = client.get(f"/api/attachments/task/{tid}").json()
    assert any(a["id"] == aid for a in listing)

    # Delete
    r = client.delete(f"/api/attachments/{aid}", headers=human_headers)
    assert r.status_code == 200


# ══════════════════════════════════════════════════════════════════════════
# 20. Projects list endpoint
# ══════════════════════════════════════════════════════════════════════════

def test_projects_list(client, human_headers):
    _make_project(client, human_headers, "ListMe")
    r = client.get("/api/projects")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert any(p["name_en"] == "ListMe" for p in r.json())

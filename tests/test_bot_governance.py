"""Comprehensive bot governance tests."""


def test_bot_cannot_mark_done(client, bot_headers, human_headers):
    pid = client.post("/api/projects", json={"name_en": "GovP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "GovWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Bot Test"
    }, headers=human_headers).json()["id"]

    r = client.put(f"/api/tasks/{tid}", json={"status": "done"},
                   headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_delete_project(client, bot_headers, human_headers):
    pid = client.post("/api/projects", json={"name_en": "BotDelP"},
                      headers=human_headers).json()["id"]
    r = client.delete(f"/api/projects/{pid}", headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_create_project(client, bot_headers):
    r = client.post("/api/projects", json={"name_en": "BotProj"},
                    headers=bot_headers)
    assert r.status_code == 403


def test_bot_cannot_create_workstream(client, bot_headers, human_headers):
    pid = client.post("/api/projects", json={"name_en": "WSTestP"},
                      headers=human_headers).json()["id"]
    r = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "BotWS"
    }, headers=bot_headers)
    assert r.status_code == 403


def test_bot_can_change_task_priority(client, bot_headers, human_headers):
    """Bot CAN change task priority (only workstream priority is restricted)."""
    pid = client.post("/api/projects", json={"name_en": "PriP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "PriWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "PriTask"
    }, headers=human_headers).json()["id"]

    r = client.put(f"/api/tasks/{tid}", json={"priority": "critical"},
                   headers=bot_headers)
    assert r.status_code == 200


def test_bot_cannot_change_user_role(client, bot_headers, human_headers):
    users = client.get("/api/users").json()
    uid = next(u["id"] for u in users if u["name"] == "test-bot")
    r = client.put(f"/api/users/{uid}", json={"role": "human"},
                   headers=bot_headers)
    assert r.status_code == 403


def test_bot_can_submit_in_review(client, bot_headers, human_headers):
    pid = client.post("/api/projects", json={"name_en": "RevP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "RevWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "ReviewTask"
    }, headers=human_headers).json()["id"]

    # Bot CAN set to in_review
    r = client.put(f"/api/tasks/{tid}", json={"status": "in_review"},
                   headers=bot_headers)
    assert r.status_code == 200


def test_unknown_user_treated_as_bot(client):
    """Unknown actors are rejected by login middleware (401)."""
    r = client.post("/api/projects", json={"name_en": "UnknownP"},
                    headers={"X-Kanban-User": "totally-unknown-user"})
    assert r.status_code == 401


def test_bot_cannot_abandon_task(client, bot_headers, human_headers):
    """Bots cannot mark tasks as abandoned — humans only."""
    pid = client.post("/api/projects", json={"name_en": "AbP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "AbWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "AbTask"
    }, headers=human_headers).json()["id"]

    # Bot cannot abandon
    r = client.put(f"/api/tasks/{tid}", json={"status": "abandoned"},
                   headers=bot_headers)
    assert r.status_code == 403

    # Human can abandon (overrides bot's entry)
    r = client.put(f"/api/tasks/{tid}", json={"status": "abandoned"},
                   headers=human_headers)
    assert r.status_code == 200
    # Verify it stuck
    r = client.get(f"/api/dashboard", headers=human_headers)
    tasks = [t for p in r.json() for w in p["workstreams"] for t in w["tasks"] if t["id"] == tid]
    assert tasks and tasks[0]["status"] == "abandoned"


def test_abandoned_counts_as_complete_in_dashboard(client, human_headers):
    """Abandoned tasks should be counted in the workstream's done total."""
    pid = client.post("/api/projects", json={"name_en": "CompleteP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "CompleteWS"
    }, headers=human_headers).json()["id"]
    t1 = client.post("/api/tasks", json={"workstream_id": wsid, "title_en": "T1"},
                     headers=human_headers).json()["id"]
    t2 = client.post("/api/tasks", json={"workstream_id": wsid, "title_en": "T2"},
                     headers=human_headers).json()["id"]
    client.put(f"/api/tasks/{t1}", json={"status": "done"}, headers=human_headers)
    client.put(f"/api/tasks/{t2}", json={"status": "abandoned"}, headers=human_headers)
    r = client.get("/api/dashboard", headers=human_headers).json()
    ws = next(w for p in r if p["id"] == pid for w in p["workstreams"] if w["id"] == wsid)
    # Both done and abandoned roll up into 'done' for completion accounting
    assert ws["task_stats"]["done"] == 2
    assert ws["task_stats"]["abandoned"] == 1

"""Tests for alert detection engine and API."""


def _setup_data(client, headers):
    """Create test data with overdue/stale scenarios."""
    pid = client.post("/api/projects", json={"name_en": "Alert Test"},
                      headers=headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "Alert WS"
    }, headers=headers).json()["id"]

    # Overdue task (due yesterday)
    from datetime import datetime, timedelta, timezone
    TZ = timezone(timedelta(hours=8))
    yesterday = (datetime.now(TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
    t_overdue = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Overdue task",
        "due_date": yesterday, "assignee": "test-human"
    }, headers=headers).json()["id"]

    # Future task (not overdue)
    next_week = (datetime.now(TZ) + timedelta(days=7)).strftime("%Y-%m-%d")
    client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "Future task",
        "due_date": next_week, "assignee": "test-human"
    }, headers=headers)

    # Blocker (created now — should not be aging yet at 48h threshold)
    client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "Fresh blocker"
    }, headers=headers)

    return pid, wsid, t_overdue


def test_alerts_endpoint(client, human_headers):
    _setup_data(client, human_headers)
    r = client.get("/api/alerts")
    assert r.status_code == 200
    data = r.json()
    assert "overdue" in data
    assert "stale" in data
    assert "aging_blockers" in data
    assert "total" in data
    assert isinstance(data["overdue"], list)


def test_alerts_summary(client, human_headers):
    r = client.get("/api/alerts/summary")
    assert r.status_code == 200
    data = r.json()
    assert "overdue" in data
    assert "total" in data
    assert isinstance(data["total"], int)


def test_alerts_filter_by_assignee(client, human_headers):
    r = client.get("/api/alerts?assignee=test-human")
    assert r.status_code == 200
    data = r.json()
    for t in data["overdue"]:
        assert t["assignee"] == "test-human"


def test_overdue_detected(client, human_headers):
    _setup_data(client, human_headers)
    r = client.get("/api/alerts")
    overdue_titles = [t["title_en"] for t in r.json()["overdue"]]
    assert "Overdue task" in overdue_titles
    assert "Future task" not in overdue_titles


def test_notification_prefs_crud(client, human_headers):
    # Get users to find a user id
    users = client.get("/api/users").json()
    uid = next(u["id"] for u in users if u["name"] == "test-human")

    # Get defaults
    r = client.get(f"/api/users/{uid}/notifications")
    assert r.status_code == 200
    assert r.json()["overdue"] == 1  # default

    # Update
    r = client.put(f"/api/users/{uid}/notifications",
                   json={"overdue": 0, "stale_days": 5},
                   headers=human_headers)
    assert r.status_code == 200

    # Verify
    r = client.get(f"/api/users/{uid}/notifications")
    assert r.json()["overdue"] == 0
    assert r.json()["stale_days"] == 5

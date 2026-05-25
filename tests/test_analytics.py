"""Tests for analytics endpoints."""


def test_analytics_bugs(client, human_headers):
    # Create a project + workstream + bug
    pid = client.post("/api/projects", json={"name_en": "AnalP"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "AnalWS"
    }, headers=human_headers).json()["id"]
    client.post("/api/bugs", json={
        "title": "Test Bug", "severity": "high",
        "project_id": pid, "workstream_id": wsid
    }, headers=human_headers)

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


def test_analytics_blockers(client, human_headers):
    r = client.get("/api/analytics/blockers")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_analytics_activity(client, human_headers):
    r = client.get("/api/analytics/activity?limit=10")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_analytics_activity_filters(client, human_headers):
    r = client.get("/api/analytics/activity?entity_type=project&limit=5")
    assert r.status_code == 200
    data = r.json()
    for item in data:
        assert item["entity_type"] == "project"

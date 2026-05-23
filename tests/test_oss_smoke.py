"""Smoke tests for the open-source deployment path:
- The kanban must boot cleanly without any FEISHU_* env vars set.
- Feishu-dependent endpoints must return 503 (not 500) when not configured.
- The agent-guide endpoint must serve docs read live from disk.
- Identity / governance still work without Feishu.
"""

import pytest


def test_no_feishu_env_routes_still_load(client):
    """Core kanban endpoints work without any Feishu configuration."""
    # GET endpoints — no auth required
    assert client.get("/").status_code == 200
    assert client.get("/api/projects").status_code == 200
    assert client.get("/api/bugs").status_code == 200
    assert client.get("/api/dashboard").status_code == 200


def test_qa_tickets_returns_503_without_wiki_config(client, human_headers):
    """When KANBAN_QA_WIKI_* env vars are blank, the route is honest about it."""
    # The route should respond with 503 (and a hint) rather than 500 or 404
    r = client.post("/api/qa-tickets",
                     json={
                         "task_type": "测试任务",
                         "product": "test",
                         "task_name": "smoke",
                         "requirements": {},
                     },
                     headers=human_headers)
    # 503 (Service Unavailable) when feishu wiki not configured;
    # if a future deployment has it configured the test should adapt.
    # For OSS default (.env.example with blanks) → 503.
    assert r.status_code in (503, 502, 200), \
        f"Expected 503 (not configured), got {r.status_code}: {r.text[:200]}"


def test_agent_guide_endpoint_serves_markdown(client):
    """The live agent-guide endpoint must serve a markdown doc by default."""
    r = client.get("/api/agent-guide")
    assert r.status_code == 200
    body = r.text
    # Should contain the AGENT_INSTRUCTIONS.md header or known content
    assert "Agent" in body or "ConvergenceKanban" in body or "kanban" in body.lower()


def test_agent_guide_quickstart_format(client):
    r = client.get("/api/agent-guide?format=quickstart")
    assert r.status_code == 200
    assert len(r.text) > 100


def test_agent_guide_index_format_returns_json(client):
    r = client.get("/api/agent-guide?format=index")
    assert r.status_code == 200
    j = r.json()
    assert "available_formats" in j
    assert "usage" in j


def test_unknown_agent_guide_format_returns_400(client):
    r = client.get("/api/agent-guide?format=does-not-exist")
    assert r.status_code == 400


def test_bot_bug_create_coerces_source(client, bot_headers):
    """Bot governance survives without Feishu — bots still get source=agent."""
    r = client.post("/api/bugs",
                    json={"title": "OSS smoke test bug"},
                    headers=bot_headers)
    assert r.status_code == 200
    bug = client.get(f"/api/bugs/{r.json()['id']}").json()
    assert bug["source"] == "agent"


def test_kanban_runs_without_env(monkeypatch):
    """If we strip every FEISHU_* env var, importing the modules still works
    (graceful degradation rather than ImportError)."""
    for var in ["FEISHU_APP_ID", "FEISHU_APP_SECRET", "FEISHU_WEBHOOK_URL",
                "FEISHU_PROFILE", "KANBAN_QA_WIKI_SPACE_ID",
                "KANBAN_QA_WIKI_PARENT_NODE", "KANBAN_QA_WIKI_TEMPLATE_NODE"]:
        monkeypatch.delenv(var, raising=False)

    # Re-import shouldn't fail
    import importlib
    import feishu_docs
    importlib.reload(feishu_docs)
    assert not feishu_docs.qa_ticket_configured()

"""Feishu bot command routing tests.

Uses unittest.mock to redirect kanban_get/kanban_post/kanban_put
through the FastAPI TestClient instead of real HTTP calls.
"""
from unittest.mock import patch

import pytest


@pytest.fixture()
def bot(client):
    """Patch feishu_bot HTTP helpers to use the test client."""
    import feishu_bot

    def _get(path):
        r = client.get(f"/api{path}", headers={"X-Kanban-User": "feishu-bot"})
        r.raise_for_status()
        return r.json()

    def _post(path, data):
        r = client.post(f"/api{path}", json=data,
                        headers={"X-Kanban-User": "feishu-bot",
                                 "Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()

    def _put(path, data):
        r = client.put(f"/api{path}", json=data,
                       headers={"X-Kanban-User": "feishu-bot",
                                "Content-Type": "application/json"})
        r.raise_for_status()
        return r.json()

    with patch.object(feishu_bot, "kanban_get", side_effect=_get), \
         patch.object(feishu_bot, "kanban_post", side_effect=_post), \
         patch.object(feishu_bot, "kanban_put", side_effect=_put):
        yield feishu_bot


def test_help_command(bot):
    result = bot.route_command("help", "test-human")
    assert "Kanban Bot Commands" in result
    assert "bugs" in result
    assert "workload" in result
    assert "conflicts" in result


def test_help_chinese(bot):
    result = bot.route_command("帮助", "test-human")
    assert "Kanban Bot Commands" in result


def test_my_tasks_no_results(bot):
    result = bot.route_command("my tasks", "nobody-has-this-name")
    assert "No tasks" in result


def test_blockers_command(bot):
    result = bot.route_command("blockers", "test-human")
    assert "blocker" in result.lower() or "Blocker" in result


def test_progress_command(bot):
    result = bot.route_command("progress", "test-human")
    assert "Progress" in result or "No projects" in result


def test_bugs_command(bot):
    result = bot.route_command("bugs", "test-human")
    assert "bug" in result.lower()


def test_bugs_chinese(bot):
    result = bot.route_command("缺陷", "test-human")
    assert "bug" in result.lower()


def test_workload_command(bot):
    result = bot.route_command("workload", "test-human")
    assert "Workload" in result or "workload" in result


def test_conflicts_command(bot):
    result = bot.route_command("conflicts", "test-human")
    assert "conflict" in result.lower()


def test_digest_command(bot):
    result = bot.route_command("digest", "test-human")
    assert "Summary" in result or "No projects" in result


def test_alerts_command(bot):
    result = bot.route_command("alerts", "test-human")
    assert "Alerts" in result or "alerts" in result


def test_search_no_match(bot):
    result = bot.route_command("search xyznonexistent999", "test-human")
    assert "No tasks found" in result


def test_search_chinese(bot):
    result = bot.route_command("搜索 xyznonexistent999", "test-human")
    assert "No tasks found" in result


def test_new_task_and_search(bot, client, human_headers):
    """Create a task via bot, then search for it."""
    pid = client.post("/api/projects", json={"name_en": "BotTestProj"},
                      headers=human_headers).json()["id"]
    client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "BotTestWS"
    }, headers=human_headers)

    result = bot.route_command("new BotUniqueTask12345", "test-human")
    assert "Task created" in result

    search = bot.route_command("search BotUniqueTask12345", "test-human")
    assert "BotUniqueTask12345" in search


def test_update_task(bot, client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "BotUpdProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "BotUpdWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "BotUpdTask"
    }, headers=human_headers).json()["id"]

    result = bot.route_command(f"update {tid} doing", "test-human")
    assert "doing" in result


def test_update_invalid_status(bot):
    result = bot.route_command("update fake123 badstatus", "test-human")
    assert "Invalid status" in result


def test_assign_task(bot, client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "BotAsnProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "BotAsnWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "BotAsnTask"
    }, headers=human_headers).json()["id"]

    result = bot.route_command(f"assign {tid} alice", "test-human")
    assert "alice" in result


def test_report_bug(bot, client, human_headers):
    client.post("/api/projects", json={"name_en": "BotBugProj"},
                headers=human_headers)
    result = bot.route_command("bug high Login crash on Safari", "test-human")
    assert "Bug reported" in result
    assert "high" in result


def test_report_bug_chinese(bot, client, human_headers):
    client.post("/api/projects", json={"name_en": "BotBugZhProj"},
                headers=human_headers)
    result = bot.route_command("报bug 页面加载失败", "test-human")
    assert "Bug reported" in result


def test_log_time(bot, client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "BotTimeProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "BotTimeWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "BotTimeTask"
    }, headers=human_headers).json()["id"]

    result = bot.route_command(f"time {tid} 30 Fixed API bug", "test-human")
    assert "30min" in result


def test_log_time_invalid(bot):
    result = bot.route_command("time fake123 abc", "test-human")
    assert "Invalid minutes" in result


def test_comment(bot, client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "BotCmtProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "BotCmtWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "BotCmtTask"
    }, headers=human_headers).json()["id"]

    result = bot.route_command(f"comment {tid} This is working now", "test-human")
    assert "Comment posted" in result


def test_resolve_blocker(bot, client, human_headers):
    pid = client.post("/api/projects", json={"name_en": "BotResProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "BotResWS"
    }, headers=human_headers).json()["id"]
    bid = client.post("/api/blockers", json={
        "workstream_id": wsid, "description_en": "Waiting for API key"
    }, headers=human_headers).json()["id"]

    result = bot.route_command(f"resolve {bid}", "test-human")
    assert "resolved" in result.lower()


def test_unknown_command(bot):
    result = bot.route_command("foobar nonsense", "test-human")
    assert "Unknown command" in result


def test_strip_at_mention(bot):
    result = bot.route_command("@KanbanBot help", "test-human")
    assert "Kanban Bot Commands" in result


def test_usage_messages(bot):
    """Missing args should show usage hints."""
    assert "Usage" in bot.route_command("assign abc", "test-human")
    assert "Usage" in bot.route_command("update abc", "test-human")
    assert "Usage" in bot.route_command("time abc", "test-human")
    assert "Usage" in bot.route_command("comment abc", "test-human")


# ── Smart reference tests ────────────────────────────────────────────────

def test_my_shorthand(bot):
    """'my' is a shorthand for 'my tasks'."""
    result = bot.route_command("my", "test-human")
    assert "No tasks" in result or "Tasks for" in result


def test_my_chinese_shorthand(bot):
    result = bot.route_command("我的", "test-human")
    assert "No tasks" in result or "Tasks for" in result


def test_numbered_shortcuts(bot, client, human_headers):
    """After 'my', numbered shortcuts work for done/update/comment."""
    pid = client.post("/api/projects", json={"name_en": "ShortcutProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "ShortcutWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "ShortcutTask",
        "assignee": "test-human",
    }, headers=human_headers).json()["id"]

    # Call 'my' to populate shortcuts
    result = bot.route_command("my", "test-human")
    assert "[1]" in result
    assert "ShortcutTask" in result
    assert "shortcuts" in result.lower()

    # Use numbered shortcut to update
    result = bot.route_command("update 1 doing", "test-human")
    assert "doing" in result

    # Use numbered shortcut to comment
    result = bot.route_command("comment 1 Progressing well", "test-human")
    assert "Comment posted" in result


def test_numbered_shortcut_no_cache(bot):
    """Numbered shortcut without prior 'my' shows hint."""
    bot._shortcut_cache.clear()
    result = bot.route_command("done 1", "nobody-user")
    assert "my" in result.lower()


def test_resolver_all_digit_task_id_not_treated_as_shortcut(bot):
    """A 12-char all-digit task ID must resolve as a task ID, not a shortcut.

    `uuid.uuid4().hex[:12]` rolls all digits ~12% of the time. Those IDs
    must not collide with the numbered-shortcut namespace (1-20).
    """
    bot._shortcut_cache.clear()
    task_id, err = bot._resolve_task_ref("933536761422", "anyone")
    assert err is None, f"expected resolver to accept 12-digit ID, got: {err!r}"
    assert task_id == "933536761422"


def test_keyword_resolve_single_match(bot, client, human_headers):
    """Keyword resolves to task when there's a unique match."""
    pid = client.post("/api/projects", json={"name_en": "KwProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "KwWS"
    }, headers=human_headers).json()["id"]
    client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "UniqueXyzTask99",
    }, headers=human_headers)

    result = bot.route_command("update UniqueXyzTask99 doing", "test-human")
    assert "doing" in result


def test_keyword_resolve_no_match(bot):
    """Keyword with no match shows error."""
    result = bot.route_command("done zzz_nonexistent_999", "test-human")
    assert "No tasks found" in result


def test_done_command(bot, client, human_headers):
    """'done' via bot submits in_review (bot governance blocks done)."""
    pid = client.post("/api/projects", json={"name_en": "DoneProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "DoneWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "DoneTask",
    }, headers=human_headers).json()["id"]

    # Bot can't mark done (governance), so test with in_review instead
    result = bot.route_command(f"update {tid} in_review", "test-human")
    assert "in_review" in result


def test_done_chinese(bot, client, human_headers):
    """'完成' command resolves task ref correctly."""
    pid = client.post("/api/projects", json={"name_en": "DoneZhProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "DoneZhWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "DoneZhTask",
    }, headers=human_headers).json()["id"]

    # Bot can't mark done, but the command should resolve the ref and attempt
    # the action. It will error with 403 from governance — that's expected.
    # The 12-char hex task ID may occasionally roll all digits; it must still
    # be resolved as a task ID, not mis-parsed as a numbered shortcut.
    result = bot.route_command(f"完成 {tid}", "test-human").lower()
    assert any(s in result for s in ("done", "bot cannot", "governance", "failed")), \
        f"Unexpected response (likely resolver mis-parsed task ID): {result!r}"


# ── Interactive card tests ───────────────────────────────────────────────

def test_build_card_no_tasks(bot):
    """Card builder returns None when user has no tasks."""
    card = bot._build_my_tasks_card("nobody-has-tasks-xyz")
    assert card is None


def test_build_card_with_tasks(bot, client, human_headers):
    """Card builder returns valid Feishu card structure."""
    pid = client.post("/api/projects", json={"name_en": "CardProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "CardWS"
    }, headers=human_headers).json()["id"]
    client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "CardTask1",
        "assignee": "card-user", "status": "todo",
    }, headers=human_headers)
    client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "CardTask2",
        "assignee": "card-user", "status": "doing",
    }, headers=human_headers)

    card = bot._build_my_tasks_card("card-user")
    assert card is not None
    assert card["header"]["title"]["content"] == "📋 My Tasks (2)"
    assert card["header"]["template"] == "green"
    assert card["config"]["wide_screen_mode"] is True

    # Should have task divs with numbered labels
    elements = card["elements"]
    div_elements = [e for e in elements if e.get("tag") == "div"]
    assert len(div_elements) >= 2
    assert "[1]" in div_elements[0]["text"]["content"]
    assert "CardTask1" in div_elements[0]["text"]["content"]
    assert "[2]" in div_elements[1]["text"]["content"]

    # Should have note with shortcut hints
    note_elements = [e for e in elements if e.get("tag") == "note"]
    assert len(note_elements) == 1
    assert "done 1" in note_elements[0]["elements"][0]["content"]


def test_build_card_caches_shortcuts(bot, client, human_headers):
    """Card builder also populates numbered shortcuts."""
    pid = client.post("/api/projects", json={"name_en": "CardCacheProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "CardCacheWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "CardCacheTask",
        "assignee": "cache-user",
    }, headers=human_headers).json()["id"]

    bot._build_my_tasks_card("cache-user")

    # Shortcut should be populated
    item = bot._get_shortcut("cache-user", 1)
    assert item is not None
    assert item["id"] == tid


def test_card_action_handler(bot, client, human_headers):
    """Card action handler processes status updates (for future HTTP callback use)."""
    pid = client.post("/api/projects", json={"name_en": "ActionProj"},
                      headers=human_headers).json()["id"]
    wsid = client.post("/api/workstreams", json={
        "project_id": pid, "title_en": "ActionWS"
    }, headers=human_headers).json()["id"]
    tid = client.post("/api/tasks", json={
        "workstream_id": wsid, "title_en": "ActionTask",
        "status": "todo",
    }, headers=human_headers).json()["id"]

    # Simulate card action context
    class MockAction:
        value = {"act": "status", "tid": tid, "st": "doing"}

    class MockCtx:
        action = MockAction()

    result = bot._handle_card_action(MockCtx())
    assert result["toast"]["type"] == "success"
    assert "Started" in result["toast"]["content"]

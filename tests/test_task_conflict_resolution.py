"""Validated Feishu task and blocker sync conflict arbitration."""

import json
import uuid

import pytest

from db import get_db
from helpers import now_iso

_created_conflicts = set()


@pytest.fixture(autouse=True)
def _clean_conflicts(tmp_path, monkeypatch):
    import db as database
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'kanban.db')
    database.init_db()
    with get_db() as conn:
        for name, role in [('test-human','human'), ('test-bot','bot')]:
            conn.execute('INSERT OR IGNORE INTO users (id,name,display_name,role) VALUES (?,?,?,?)',
                         (uuid.uuid4().hex, name, name, role))
    _created_conflicts.clear()
    yield
    if _created_conflicts:
        with get_db() as conn:
            conn.executemany("DELETE FROM sync_conflicts WHERE id=?",
                             [(conflict_id,) for conflict_id in _created_conflicts])


def _workspace(client, human_headers):
    project = client.post("/api/projects", json={"name_en": "Conflict tests"},
                          headers=human_headers).json()["id"]
    return client.post("/api/workstreams", json={"project_id": project, "title_en": "Conflicts"},
                       headers=human_headers).json()["id"]


def _task(client, human_headers, workstream_id, title="Task", **fields):
    response = client.post("/api/tasks", json={
        "workstream_id": workstream_id, "title_en": title, **fields,
    }, headers=human_headers)
    assert response.status_code == 200
    return response.json()["id"]


def _blocker(client, human_headers, workstream_id):
    response = client.post("/api/blockers", json={
        "workstream_id": workstream_id, "description_en": "Existing blocker",
    }, headers=human_headers)
    assert response.status_code == 200
    return response.json()["id"]


def _conflict(entity_type, entity_id, field, local="", remote=""):
    conflict_id = uuid.uuid4().hex
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sync_conflicts (id, entity_type, entity_id, field_name, local_value, "
            "remote_value, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (conflict_id, entity_type, entity_id, field, local, remote, now_iso()),
        )
    _created_conflicts.add(conflict_id)
    return conflict_id


def _row(table, entity_id):
    with get_db() as conn:
        return dict(conn.execute(f"SELECT * FROM {table} WHERE id=?", (entity_id,)).fetchone())


def _conflict_row(conflict_id):
    with get_db() as conn:
        return dict(conn.execute("SELECT * FROM sync_conflicts WHERE id=?", (conflict_id,)).fetchone())


def test_task_conflicts_map_chinese_title_and_allow_bot_nonterminal_update(
    client, human_headers, bot_headers,
):
    workstream_id = _workspace(client, human_headers)
    task_id = _task(client, human_headers, workstream_id, title="English title", title_zh="旧标题")
    title_conflict = _conflict("task", task_id, "title_en", "English title", "新的标题")
    status_conflict = _conflict("task", task_id, "status", "todo", "doing")

    response = client.post("/api/sync-conflicts/resolve-all", json={"resolution": "remote"},
                           headers=bot_headers)

    assert response.status_code == 200
    task = _row("tasks", task_id)
    assert task["title_en"] == "English title"
    assert task["title_zh"] == "新的标题"
    assert task["status"] == "doing"
    assert _conflict_row(title_conflict)["resolved"] == 1
    assert _conflict_row(status_conflict)["resolved"] == 1

def test_bot_cannot_resolve_task_to_done(client, human_headers, bot_headers):
    workstream_id = _workspace(client, human_headers)
    task_id = _task(client, human_headers, workstream_id)
    conflict_id = _conflict("task", task_id, "status", "todo", "done")

    response = client.put(f"/api/sync-conflicts/{conflict_id}/resolve",
                          json={"resolution": "remote"}, headers=bot_headers)

    assert response.status_code == 403
    assert _row("tasks", task_id)["status"] == "todo"
    assert _conflict_row(conflict_id)["resolved"] == 0


def test_english_display_choice_clears_stale_chinese_override(client, human_headers):
    wid = _workspace(client, human_headers)
    tid = _task(client, human_headers, wid, title='Old English', title_zh='旧标题')
    cid = _conflict('task', tid, 'title_en', '旧标题', 'New English')
    response = client.put(f'/api/sync-conflicts/{cid}/resolve',
                          json={'resolution':'remote'}, headers=human_headers)
    assert response.status_code == 200
    assert _row('tasks', tid)['title_en'] == 'New English'
    assert _row('tasks', tid)['title_zh'] == ''


def test_invalid_bulk_task_choice_rolls_back_all_task_updates(client, human_headers):
    workstream_id = _workspace(client, human_headers)
    task_id = _task(client, human_headers, workstream_id)
    assignee_conflict = _conflict("task", task_id, "assignee", "", "Alice")
    date_conflict = _conflict("task", task_id, "due_date", "", "not-a-date")

    response = client.post("/api/sync-conflicts/resolve-all", json={"resolution": "remote"},
                           headers=human_headers)

    assert response.status_code == 400
    task = _row("tasks", task_id)
    assert task["assignee"] == ""
    assert task["due_date"] is None
    assert _conflict_row(assignee_conflict)["resolved"] == 0
    assert _conflict_row(date_conflict)["resolved"] == 0


def test_task_parent_cycle_and_deleted_task_conflicts_are_rejected(client, human_headers):
    workstream_id = _workspace(client, human_headers)
    parent_id = _task(client, human_headers, workstream_id, "Parent")
    child_id = _task(client, human_headers, workstream_id, "Child", parent_task_id=parent_id)
    cycle_conflict = _conflict("task", parent_id, "parent_task_id", "", child_id)

    cycle_response = client.put(f"/api/sync-conflicts/{cycle_conflict}/resolve",
                                json={"resolution": "remote"}, headers=human_headers)
    assert cycle_response.status_code == 400
    assert _conflict_row(cycle_conflict)["resolved"] == 0

    deleted_conflict = _conflict("task", child_id, "assignee", "", "Alice")
    with get_db() as conn:
        conn.execute("UPDATE tasks SET deleted_at=? WHERE id=?", (now_iso(), child_id))
    deleted_response = client.put(f"/api/sync-conflicts/{deleted_conflict}/resolve",
                                  json={"resolution": "remote"}, headers=human_headers)
    assert deleted_response.status_code == 404
    assert _conflict_row(deleted_conflict)["resolved"] == 0


def test_blocker_status_and_bilingual_description_mapping(client, human_headers):
    workstream_id = _workspace(client, human_headers)
    blocker_id = _blocker(client, human_headers, workstream_id)
    title_conflict = _conflict("blocker", blocker_id, "title_en", "", "网络连接中断")
    status_conflict = _conflict("blocker", blocker_id, "status", "blocked", "done")

    response = client.post("/api/sync-conflicts/resolve-all", json={"resolution": "remote"},
                           headers=human_headers)

    assert response.status_code == 200
    blocker = _row("blockers", blocker_id)
    assert blocker["description_en"] == "Existing blocker"
    assert blocker["description_zh"] == "网络连接中断"
    assert blocker["resolved"] == 1
    assert blocker["resolved_at"]
    assert blocker["updated_at"]
    assert _conflict_row(title_conflict)["resolved"] == 1
    assert _conflict_row(status_conflict)["resolved"] == 1

    reopen_id = _conflict("blocker", blocker_id, "status", "done", "blocked")
    reopened = client.put(f"/api/sync-conflicts/{reopen_id}/resolve",
                          json={"resolution": "remote"}, headers=human_headers)
    assert reopened.status_code == 200
    blocker = _row("blockers", blocker_id)
    assert blocker["resolved"] == 0
    assert blocker["resolved_at"] is None


def test_bug_task_ids_are_validated_linked_and_clearable(client, human_headers):
    workstream_id = _workspace(client, human_headers)
    task_id = _task(client, human_headers, workstream_id)
    bug_id = client.post("/api/bugs", json={"title": "Linked bug"},
                         headers=human_headers).json()["id"]
    invalid_id = _conflict("bug", bug_id, "task_ids", "[]", json.dumps([task_id, task_id]))

    rejected = client.put(f"/api/sync-conflicts/{invalid_id}/resolve",
                          json={"resolution": "remote"}, headers=human_headers)
    assert rejected.status_code == 400
    assert _conflict_row(invalid_id)["resolved"] == 0
    for invalid_value in ('{"id":"not-an-array"}', json.dumps(["missing-task"])):
        bad_conflict = _conflict("bug", bug_id, "task_ids", "[]", invalid_value)
        bad_response = client.put(f"/api/sync-conflicts/{bad_conflict}/resolve",
                                  json={"resolution": "remote"}, headers=human_headers)
        assert bad_response.status_code == 400
        assert _conflict_row(bad_conflict)["resolved"] == 0

    valid_id = _conflict("bug", bug_id, "task_ids", "[]", json.dumps([task_id]))
    accepted = client.put(f"/api/sync-conflicts/{valid_id}/resolve",
                          json={"resolution": "remote"}, headers=human_headers)
    assert accepted.status_code == 200
    assert _row("bugs", bug_id)["task_id"] == task_id
    with get_db() as conn:
        assert conn.execute("SELECT task_id FROM bug_task_links WHERE bug_id=?", (bug_id,)).fetchall()

    clear_id = _conflict("bug", bug_id, "task_ids", json.dumps([task_id]), "[]")
    cleared = client.put(f"/api/sync-conflicts/{clear_id}/resolve",
                         json={"resolution": "remote"}, headers=human_headers)
    assert cleared.status_code == 200
    assert _row("bugs", bug_id)["task_id"] is None
    with get_db() as conn:
        assert conn.execute("SELECT 1 FROM bug_task_links WHERE bug_id=?", (bug_id,)).fetchone() is None


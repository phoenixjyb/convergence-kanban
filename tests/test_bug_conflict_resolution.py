"""Validated human arbitration for Feishu bug sync conflicts."""

import json
import uuid

import pytest

from db import get_db
from helpers import now_iso


def _new_bug(client, human_headers):
    response = client.post("/api/bugs", json={"title": "Conflict test bug"}, headers=human_headers)
    assert response.status_code == 200
    return response.json()["id"]


def _conflict(bug_id, field, value, remote_value=""):
    conflict_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sync_conflicts (id, entity_type, entity_id, field_name, local_value, "
            "remote_value, created_at) VALUES (?, 'bug', ?, ?, ?, ?, ?)",
            (conflict_id, bug_id, field, value, remote_value, now_iso()),
        )
    return conflict_id


def _bug_row(bug_id):
    with get_db() as conn:
        return dict(conn.execute("SELECT * FROM bugs WHERE id=?", (bug_id,)).fetchone())


def _conflict_row(conflict_id):
    with get_db() as conn:
        return dict(conn.execute("SELECT * FROM sync_conflicts WHERE id=?", (conflict_id,)).fetchone())


def _remove_conflict(conflict_id):
    with get_db() as conn:
        conn.execute("DELETE FROM sync_conflicts WHERE id=?", (conflict_id,))


def test_single_bug_conflict_applies_reporter(client, human_headers):
    bug_id = _new_bug(client, human_headers)
    conflict_id = _conflict(bug_id, "reporter", "", "Feishu Reporter")

    response = client.put(
        f"/api/sync-conflicts/{conflict_id}/resolve",
        json={"resolution": "remote"}, headers=human_headers,
    )

    assert response.status_code == 200
    assert _bug_row(bug_id)["reporter"] == "Feishu Reporter"
    assert _conflict_row(conflict_id)["resolved"] == 1


def test_empty_remote_attachments_use_sync_canonical_blank(client, human_headers):
    bug_id = _new_bug(client, human_headers)
    conflict_id = _conflict(bug_id, 'issue_images', '[{"file_token":"old"}]', '')
    response = client.put(f'/api/sync-conflicts/{conflict_id}/resolve',
                          json={'resolution':'remote'}, headers=human_headers)
    assert response.status_code == 200
    assert _bug_row(bug_id)['issue_images'] == ''
    assert _conflict_row(conflict_id)['local_value'] == ''


def test_bulk_bug_conflicts_validate_and_apply_supported_fields(client, human_headers):
    bug_id = _new_bug(client, human_headers)
    values = {
        "fix_method": "Replace cable",
        "fix_version": "2.4.1",
        "fix_date": "2026-10-14",
        "reporter": "QA",
        "steps": "1. Reboot\n2. Retry",
        "issue_images": json.dumps([{"file_token": "tok-1", "name": "screen.png"}]),
    }
    conflict_ids = [_conflict(bug_id, field, "", value) for field, value in values.items()]

    response = client.post(
        "/api/sync-conflicts/resolve-all",
        json={"resolution": "remote"}, headers=human_headers,
    )

    assert response.status_code == 200
    row = _bug_row(bug_id)
    assert row["fix_method"] == "Replace cable"
    assert row["fix_version"] == "2.4.1"
    assert row["fix_date"] == "2026-10-14"
    assert row["reporter"] == "QA"
    assert row["steps_to_reproduce"] == "1. Reboot\n2. Retry"
    assert json.loads(row["issue_images"]) == [{"file_token": "tok-1", "name": "screen.png"}]
    assert all(_conflict_row(cid)["resolved"] == 1 for cid in conflict_ids)


@pytest.mark.parametrize("status", ["resolved", "closed"])
def test_resolved_bug_status_conflict_sets_resolved_at(client, human_headers, status):
    bug_id = _new_bug(client, human_headers)
    conflict_id = _conflict(bug_id, "status", "open", status)

    response = client.put(
        f"/api/sync-conflicts/{conflict_id}/resolve",
        json={"resolution": "remote"}, headers=human_headers,
    )

    assert response.status_code == 200
    assert _bug_row(bug_id)["status"] == status
    assert _bug_row(bug_id)["resolved_at"]
    assert _conflict_row(conflict_id)["resolved"] == 1


@pytest.mark.parametrize("resolution", ["local", "manual"])
def test_different_pull_only_image_choice_is_rejected(client, human_headers, resolution):
    bug_id = _new_bug(client, human_headers)
    local_images = [{"file_token": "local", "name": "local.png"}]
    remote_images = [{"file_token": "remote", "name": "remote.png"}]
    conflict_id = _conflict(
        bug_id, "issue_images", json.dumps(local_images), json.dumps(remote_images),
    )
    body = {"resolution": resolution}
    if resolution == "manual":
        body["manual_value"] = json.dumps(local_images)

    response = client.put(
        f"/api/sync-conflicts/{conflict_id}/resolve", json=body, headers=human_headers,
    )

    assert response.status_code == 400
    conflict = _conflict_row(conflict_id)
    assert conflict["resolved"] == 0
    assert conflict["remote_value"] == json.dumps(remote_images)
    assert json.loads(_bug_row(bug_id)["issue_images"] or "[]") == []
    _remove_conflict(conflict_id)


def test_equivalent_manual_image_choice_matches_remote_snapshot(client, human_headers):
    bug_id = _new_bug(client, human_headers)
    remote = [{"file_token": "remote", "name": "remote.png"}]
    conflict_id = _conflict(bug_id, "issue_images", "[]", json.dumps(remote))

    response = client.put(
        f"/api/sync-conflicts/{conflict_id}/resolve",
        json={"resolution": "manual", "manual_value": '[{"name":"remote.png","file_token":"remote"}]'},
        headers=human_headers,
    )

    assert response.status_code == 200
    conflict = _conflict_row(conflict_id)
    assert conflict["resolved"] == 1
    assert conflict["remote_value"] == json.dumps(remote)
    assert json.loads(_bug_row(bug_id)["issue_images"]) == remote


def test_invalid_bulk_bug_choice_leaves_all_choices_unresolved_and_unapplied(client, human_headers):
    bug_id = _new_bug(client, human_headers)
    reporter_conflict = _conflict(bug_id, "reporter", "test-human", "Changed reporter")
    status_conflict = _conflict(bug_id, "status", "open", "invalid-status")

    response = client.post(
        "/api/sync-conflicts/resolve-all",
        json={"resolution": "remote"}, headers=human_headers,
    )

    assert response.status_code == 400
    assert _bug_row(bug_id)["reporter"] == "test-human"
    assert _bug_row(bug_id)["status"] == "open"
    assert _conflict_row(reporter_conflict)["resolved"] == 0
    assert _conflict_row(status_conflict)["resolved"] == 0
    _remove_conflict(reporter_conflict)
    _remove_conflict(status_conflict)


@pytest.mark.parametrize(("field", "value"), [
    ("status", "not-a-bug-status"),
    ("issue_images", "not-json"),
    ("not_supported", "value"),
])
def test_invalid_bug_conflict_is_not_resolved(client, human_headers, field, value):
    bug_id = _new_bug(client, human_headers)
    conflict_id = _conflict(bug_id, field, "", value)

    response = client.put(
        f"/api/sync-conflicts/{conflict_id}/resolve",
        json={"resolution": "remote"}, headers=human_headers,
    )

    assert response.status_code == 400
    assert _conflict_row(conflict_id)["resolved"] == 0
    assert _bug_row(bug_id)["status"] == "open"
    _remove_conflict(conflict_id)


def test_deleted_bug_conflict_is_not_resolved(client, human_headers):
    bug_id = _new_bug(client, human_headers)
    conflict_id = _conflict(bug_id, "title", "", "Remote title")
    with get_db() as conn:
        conn.execute("UPDATE bugs SET deleted_at=? WHERE id=?", (now_iso(), bug_id))

    response = client.put(
        f"/api/sync-conflicts/{conflict_id}/resolve",
        json={"resolution": "remote"}, headers=human_headers,
    )

    assert response.status_code == 404
    assert _conflict_row(conflict_id)["resolved"] == 0
    _remove_conflict(conflict_id)


def test_bot_cannot_arbitrate_bug_conflict(client, human_headers, bot_headers):
    bug_id = _new_bug(client, human_headers)
    conflict_id = _conflict(bug_id, "reporter", "", "Bot choice")

    response = client.put(
        f"/api/sync-conflicts/{conflict_id}/resolve",
        json={"resolution": "remote"}, headers=bot_headers,
    )

    assert response.status_code == 403
    assert _conflict_row(conflict_id)["resolved"] == 0
    assert _bug_row(bug_id)["reporter"] == "test-human"
    _remove_conflict(conflict_id)

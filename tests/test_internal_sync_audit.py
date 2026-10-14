"""Read-only audit checks; internal tooling is absent in public releases."""

import json
import sqlite3
from types import SimpleNamespace

import pytest

audit_module = pytest.importorskip("scripts.internal.audit_feishu_parity")


def transport(records, complete=True):
    return SimpleNamespace(_state={"bugs_table": "test"},
                           list_records=lambda table: (records, complete),
                           _text=audit_module.sync._text,
                           _extract_person_field=audit_module.sync._extract_person_field)


def database():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE users (name TEXT, feishu_open_id TEXT)")
    db.execute("CREATE TABLE bugs (id TEXT, display_id TEXT, source TEXT, deleted_at TEXT, updated_at TEXT, "
               "title TEXT, status TEXT, environment TEXT, steps_to_reproduce TEXT, "
               "fix_method TEXT, fix_version TEXT, fix_date TEXT, assignee TEXT, reporter TEXT)")
    return db


def test_partial_remote_read_never_reports_missing_records():
    with database() as db:
        assert audit_module.audit(db, transport([], False))["qa_bugs"] == {"complete": False}


def test_blank_remote_template_is_distinguished_from_unlinked_issue():
    with database() as db:
        before = db.total_changes
        result = audit_module.audit(db, transport([{"fields": {}}, {"fields": {"Title": "example"}}]))
        assert result["qa_bugs"]["unlinked_remote"] == 2
        assert result["qa_bugs"]["blank_unlinked_rows"] == 1
        assert db.total_changes == before


def test_audit_reports_hold_gap_without_content_or_database_writes():
    with database() as db:
        db.execute("INSERT INTO bugs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   ("test", "BUG-261014-001", "manual", None, "2026-10-14 12:00:00", "private content", "open",
                    "", "", "", "", "", "", ""))
        before = db.total_changes
        fields = {"kanban_id": "test", "Bug ID": "BUG-261014-001", "Title": "private content", "Status": "Hold"}
        report = audit_module.audit(db, transport([{"fields": fields}]))
        assert report["qa_bugs"]["differences"][0]["fields"] == ["status"]
        assert "private content" not in json.dumps(report)
        assert db.total_changes == before

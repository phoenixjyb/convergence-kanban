"""Exercise real sync decisions against isolated SQLite and fake Feishu records."""

import copy
import sqlite3

import pytest

import db as database
import feishu_sync as sync


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'kanban.db')
    database.init_db()
    conn = sqlite3.connect(tmp_path / 'kanban.db')
    conn.row_factory = sqlite3.Row
    records, writes, creates = [], [], []
    monkeypatch.setattr(sync, '_state', {'bugs_table': 'qa', 'rd_bugs_table': 'rd'})
    monkeypatch.setattr(sync, 'save_state', lambda: None)
    monkeypatch.setattr(sync, 'list_records', lambda table: (copy.deepcopy(records), True))
    monkeypatch.setattr(sync, '_load_feature_to_project_map', lambda: {})
    monkeypatch.setattr(sync, 'update_record', lambda table, rid, fields: writes.append((table, rid, fields)))
    monkeypatch.setattr(sync, 'create_record', lambda table, fields: creates.append((table, fields)) or 'created')
    monkeypatch.setattr(sync, 'delete_record', lambda *args: pytest.fail('Unexpected Feishu delete'))
    monkeypatch.setattr(sync, 'now_iso', lambda: '2026-10-14 12:00:00')
    yield conn, records, writes, creates
    conn.close()


def existing(conn, source='manual', **changes):
    values = {'id': 'bug', 'title': 'Title', 'source': source, 'status': 'open',
              'display_id': 'BUG-261014-001' if source == 'manual' else 'RD-261014-001',
              'updated_at': '2026-10-01 12:00:00', **changes}
    conn.execute(f"INSERT INTO bugs ({','.join(values)}) VALUES ({','.join('?' for _ in values)})", list(values.values()))
    conn.commit()
    return {'record_id': 'rec', 'fields': {'kanban_id': 'bug', 'Title': 'Title',
            'Bug ID': values['display_id'], 'Status': 'To Do', '优先级': 'P2', 'updated_at': '2026-10-01 12:00:00'}}


def test_existing_qa_hold_is_pulled_and_local_hold_can_be_pushed(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn)
    record['fields']['Status'] = 'Hold'
    records.append(record)
    sync._state['last_sync_ts_bugs'] = {'bug': '2026-10-02 12:00:00'}
    sync.sync_bugs_v2(conn, {})
    assert conn.execute("SELECT status FROM bugs").fetchone()[0] == 'hold'
    assert all(w[2].get('Status', 'Hold') == 'Hold' for w in writes)
    records[0]['fields']['Status'] = 'To Do'
    writes.clear()
    conn.execute("UPDATE bugs SET updated_at='2026-10-15 12:00:00'")
    conn.commit()
    sync.sync_bugs_v2(conn, {})
    assert writes[-1][2]['Status'] == 'Hold'


def test_new_qa_hold_and_person_fields_are_imported(bridge):
    conn, records, writes, creates = bridge
    records.append({'record_id': 'rec', 'fields': {'Title': 'New QA', 'Status': 'Hold',
                    'Reporter (人员 )': [{'id': 'ou_test', 'name': 'QA user'}],
                    'Assignee (人员 )': [{'id': 'ou_owner', 'name': 'QA owner'}]}})
    sync.sync_bugs_v2(conn, {})
    row = conn.execute("SELECT * FROM bugs").fetchone()
    assert (row['status'], row['reporter'], row['assignee']) == ('hold', 'QA user', 'QA owner')
    assert conn.execute("SELECT feishu_open_id FROM users WHERE name='QA owner'").fetchone()[0] == 'ou_owner'


def test_new_rd_plain_text_and_rich_text_people_are_imported(bridge):
    conn, records, writes, creates = bridge
    records.append({'record_id': 'rec', 'fields': {'Title': 'New RD', 'Status': 'Hold',
                    'Reporter': [{'text': 'agent-reporter'}], 'Assignee': 'engineer'}})
    sync.sync_bugs_v2(conn, {}, 'rd_bugs_table', 'agent', '_rd')
    row = conn.execute("SELECT * FROM bugs").fetchone()
    assert (row['source'], row['status'], row['reporter'], row['assignee']) == ('agent', 'hold', 'agent-reporter', 'engineer')
    assert conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0


def test_existing_rd_people_pull_clear_and_push_use_text_fields(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn, 'agent')
    record['fields'].update(Reporter='agent-reporter', Assignee='engineer')
    records.append(record)
    sync._state['last_sync_ts_bugs_rd'] = {'bug': '2026-10-02 12:00:00'}
    sync.sync_bugs_v2(conn, {}, 'rd_bugs_table', 'agent', '_rd')
    row = conn.execute("SELECT reporter,assignee FROM bugs").fetchone()
    assert tuple(row) == ('agent-reporter', 'engineer')
    # Clearing the plain-text fields is an intentional remote edit, not a missing Person identity.
    records[0]['fields'].update(Reporter='', Assignee='')
    sync.sync_bugs_v2(conn, {}, 'rd_bugs_table', 'agent', '_rd')
    assert tuple(conn.execute("SELECT reporter,assignee FROM bugs").fetchone()) == ('', '')
    conn.execute("UPDATE bugs SET reporter='new-reporter',assignee='new-owner',updated_at='2026-10-15 12:00:00'")
    conn.commit()
    sync.sync_bugs_v2(conn, {}, 'rd_bugs_table', 'agent', '_rd')
    assert writes[-1][2]['Reporter'] == 'new-reporter'
    assert writes[-1][2]['Assignee'] == 'new-owner'
    assert 'Reporter (人员 )' not in writes[-1][2]
    records[0]['fields'].update(Reporter='new-reporter', Assignee='new-owner')
    conn.execute("UPDATE bugs SET reporter='',assignee='',updated_at='2026-10-16 12:00:00'")
    conn.commit()
    sync.sync_bugs_v2(conn, {}, 'rd_bugs_table', 'agent', '_rd')
    assert writes[-1][2]['Reporter'] == ''
    assert writes[-1][2]['Assignee'] == ''


def test_missing_rd_uses_its_own_synced_id_set(bridge):
    conn, records, writes, creates = bridge
    existing(conn, 'agent')
    sync._state['synced_kids_bugs_rd'] = ['bug']
    sync.sync_bugs_v2(conn, {}, 'rd_bugs_table', 'agent', '_rd')
    assert conn.execute("SELECT deleted_at FROM bugs").fetchone()[0]
    assert not creates

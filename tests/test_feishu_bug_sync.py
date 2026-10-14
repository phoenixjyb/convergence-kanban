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
    conn.execute('PRAGMA foreign_keys=ON')
    records, writes, creates = [], [], []
    monkeypatch.setattr(sync, '_state', {'bugs_table': 'qa', 'rd_bugs_table': 'rd'})
    monkeypatch.setattr(sync, 'save_state', lambda: None)
    monkeypatch.setattr(sync, 'list_records', lambda table: (copy.deepcopy(records), True))
    monkeypatch.setattr(sync, '_load_feature_to_project_map', lambda: {})
    monkeypatch.setattr(sync, 'update_record', lambda table, rid, fields: writes.append((table, rid, fields)) or {'code': 0})
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


@pytest.mark.parametrize('status,remote_status', [('investigating', 'In Progress'), ('resolved', 'Done'), ('wontfix', 'Done')])
def test_coarse_feishu_status_does_not_overwrite_precise_local_state(bridge, status, remote_status):
    conn, records, writes, creates = bridge
    record = existing(conn, status=status)
    record['fields'].update(Status=remote_status, Title='Remote title edit')
    records.append(record)
    sync.sync_bugs_v2(conn, {})
    row = conn.execute('SELECT title,status FROM bugs').fetchone()
    assert tuple(row) == ('Remote title edit', status)


def test_explicit_remote_status_change_still_pulls(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn, status='investigating')
    record['fields']['Status'] = 'Hold'
    records.append(record)
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT status FROM bugs').fetchone()[0] == 'hold'


@pytest.mark.parametrize('response', [{'code': 999}, None])
def test_failed_push_keeps_checkpoint_and_local_change_for_retry(bridge, monkeypatch, response):
    conn, records, writes, creates = bridge
    records.append(existing(conn, status='fix_complete', updated_at='2026-10-15 12:00:00'))
    sync._state['last_sync_ts_bugs'] = {'bug': '2026-10-02 12:00:00'}
    monkeypatch.setattr(sync, 'update_record', lambda *args: response)
    sync.sync_bugs_v2(conn, {})
    assert sync._state['last_sync_ts_bugs']['bug'] == '2026-10-02 12:00:00'
    assert conn.execute('SELECT status FROM bugs').fetchone()[0] == 'fix_complete'
    monkeypatch.setattr(sync, 'update_record', lambda table, rid, fields: writes.append(fields) or {'code': 0})
    sync.sync_bugs_v2(conn, {})
    assert writes[-1]['Status'] == 'Fix Complete'
    assert sync._state['last_sync_ts_bugs']['bug'] == '2026-10-14 12:00:00'


def test_failed_pull_ack_does_not_change_local_row(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    record = existing(conn)
    record['fields']['Status'] = 'Hold'
    records.append(record)
    sync._state['last_sync_ts_bugs'] = {'bug': '2026-10-02 12:00:00'}
    before = tuple(conn.execute('SELECT * FROM bugs').fetchone())
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code': 999})
    sync.sync_bugs_v2(conn, {})
    assert tuple(conn.execute('SELECT * FROM bugs').fetchone()) == before
    assert sync._state['last_sync_ts_bugs']['bug'] == '2026-10-02 12:00:00'


def test_failed_id_backfill_does_not_checkpoint(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    record = existing(conn)
    record['fields']['Bug ID'] = ''
    records.append(record)
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code': 999})
    sync.sync_bugs_v2(conn, {})
    assert 'bug' not in sync._state.get('last_sync_ts_bugs', {})


def test_unknown_remote_status_is_not_silently_imported_as_open(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn, status='hold')
    record['fields'].update(Status='Custom QA decision', Title='Remote edit')
    records.extend([record, {'record_id': 'new', 'fields': {'Title': 'New bug', 'Status': 'Custom QA decision'}}])
    sync.sync_bugs_v2(conn, {})
    assert tuple(conn.execute('SELECT title,status FROM bugs').fetchone()) == ('Title', 'hold')
    assert conn.execute('SELECT count(*) FROM bugs').fetchone()[0] == 1
    assert not writes


@pytest.mark.parametrize('source,table,suffix', [('manual','bugs_table',''), ('agent','rd_bugs_table','_rd')])
def test_import_retry_keeps_identity_across_restarts_and_lost_state(bridge, monkeypatch, source, table, suffix):
    conn, records, writes, creates = bridge
    records.append({'record_id': 'new', 'fields': {'Title': 'Real new bug', 'Status': 'Hold'}})
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code': 999})
    sync.sync_bugs_v2(conn, {}, table, source, suffix)
    first = dict(conn.execute('SELECT * FROM bugs').fetchone())
    assert first['display_id'].startswith('BUG-' if source == 'manual' else 'RD-')
    assert 'last_sync_ts_bugs' + suffix in sync._state
    assert first['id'] not in sync._state['last_sync_ts_bugs' + suffix]
    monkeypatch.setattr(sync, '_state', {'bugs_table':'qa','rd_bugs_table':'rd'})
    sync.sync_bugs_v2(conn, {}, table, source, suffix)
    assert conn.execute('SELECT count(*) FROM bugs').fetchone()[0] == 1
    assert not creates
    monkeypatch.setattr(sync, 'update_record', lambda table, rid, fields: writes.append(fields) or {'code': 0})
    sync.sync_bugs_v2(conn, {}, table, source, suffix)
    assert conn.execute('SELECT id,display_id FROM bugs').fetchone()[:] == (first['id'], first['display_id'])
    assert writes[0]['kanban_id'] == first['id']
    assert writes[0]['Bug ID'] == first['display_id']


def test_ambiguous_import_ack_recovers_by_reading_same_remote_identity(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    records.append({'record_id':'new','fields':{'Title':'New bug','Status':'To Do'}})
    def ambiguous(table, rid, fields):
        records[0]['fields'].update(fields)
        return {'code': -1}
    monkeypatch.setattr(sync, 'update_record', ambiguous)
    sync.sync_bugs_v2(conn, {})
    first_id = conn.execute('SELECT id FROM bugs').fetchone()[0]
    monkeypatch.setattr(sync, '_state', {'bugs_table':'qa','rd_bugs_table':'rd'})
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code': 0})
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT count(*) FROM bugs').fetchone()[0] == 1
    assert records[0]['fields']['kanban_id'] == first_id
    assert not creates


def test_import_identity_is_durable_before_transport_exception(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    records.append({'record_id':'new','fields':{'Title':'New bug'}})
    def crash(*args):
        raise OSError('simulated lost connection')
    monkeypatch.setattr(sync, 'update_record', crash)
    with pytest.raises(OSError):
        sync.sync_bugs_v2(conn, {})
    first_id = conn.execute('SELECT id FROM bugs').fetchone()[0]
    assert conn.execute('SELECT bug_id FROM feishu_bug_imports').fetchone()[0] == first_id
    conn.rollback()
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code':0})
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT count(*) FROM bugs').fetchone()[0] == 1


def test_partial_read_cannot_create_duplicate_or_advance_checkpoint(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    existing(conn)
    sync._state['last_sync_ts_bugs'] = {'bug':'2026-10-02 12:00:00'}
    monkeypatch.setattr(sync, 'list_records', lambda table: ([], False))
    sync.sync_bugs_v2(conn, {})
    assert not writes and not creates
    assert sync._state['last_sync_ts_bugs']['bug'] == '2026-10-02 12:00:00'


def test_pending_import_with_missing_source_does_not_create_remote_duplicate(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    records.append({'record_id':'new','fields':{'Title':'New bug'}})
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code':999})
    sync.sync_bugs_v2(conn, {})
    records.clear()
    sync.sync_bugs_v2(conn, {})
    assert not creates
    assert conn.execute('SELECT count(*) FROM bugs WHERE deleted_at IS NULL').fetchone()[0] == 1


def test_blank_rows_and_blank_status_cells_are_left_alone(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn, status='hold')
    record['fields']['Status'] = ''
    records.extend([record, {'record_id':'blank','fields':{}}, {'record_id':'whitespace','fields':{'Title':'   '}}])
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT count(*) FROM bugs').fetchone()[0] == 1
    assert conn.execute('SELECT status FROM bugs').fetchone()[0] == 'hold'
    assert not writes and not creates


def test_unresolved_conflict_is_not_duplicated_or_overwritten_on_next_poll(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn, title='Local edit', updated_at='2026-10-03 12:00:00')
    record['fields'].update(Title='Remote edit', updated_at='2026-10-04 12:00:00')
    records.append(record)
    sync._state['last_sync_ts_bugs'] = {'bug':'2026-10-02 12:00:00'}
    sync.sync_bugs_v2(conn, {})
    sync.sync_bugs_v2(conn, {})
    assert conn.execute("SELECT count(*) FROM sync_conflicts WHERE resolved=0").fetchone()[0] == 1
    assert conn.execute('SELECT title FROM bugs').fetchone()[0] == 'Local edit'
    assert sync._state['last_sync_ts_bugs']['bug'] == '2026-10-02 12:00:00'
    assert not writes


def test_resolved_local_choice_pushes_once_but_new_remote_edit_conflicts(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn, title='Local edit', updated_at='2026-10-03 12:00:00')
    record['fields'].update(Title='Remote edit', updated_at='2026-10-04 12:00:00')
    records.append(record)
    sync._state['last_sync_ts_bugs'] = {'bug':'2026-10-02 12:00:00'}
    sync.sync_bugs_v2(conn, {})
    conn.execute("UPDATE sync_conflicts SET resolved=1,resolution='local',resolved_at='2026-10-05 12:00:00'")
    conn.execute("UPDATE bugs SET updated_at='2026-10-05 12:00:00'")
    conn.commit()
    sync.sync_bugs_v2(conn, {})
    assert writes[-1][2]['Title'] == 'Local edit'
    # A genuinely newer remote decision must not be covered by that old choice.
    sync._state['last_sync_ts_bugs']['bug'] = '2026-10-02 12:00:00'
    records[0]['fields'].update(Title='New remote edit', updated_at='2026-10-06 12:00:00')
    writes.clear()
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT count(*) FROM sync_conflicts WHERE resolved=0').fetchone()[0] == 1
    assert not writes


def test_confirmed_import_keeps_existing_remote_deletion_behavior(bridge):
    conn, records, writes, creates = bridge
    records.append({'record_id':'new','fields':{'Title':'New bug'}})
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT linked FROM feishu_bug_imports').fetchone()[0] == 1
    records.clear()
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT deleted_at FROM bugs').fetchone()[0]
    assert not creates


def test_partial_human_resolution_remains_held_until_all_choices_are_made(bridge):
    conn, records, writes, creates = bridge
    record = existing(conn, title='Local title', fix_method='Local method', updated_at='2026-10-03 12:00:00')
    record['fields'].update(Title='Remote title', 修复方法='Remote method', updated_at='2026-10-04 12:00:00')
    records.append(record)
    sync._state['last_sync_ts_bugs'] = {'bug':'2026-10-02 12:00:00'}
    sync.sync_bugs_v2(conn, {})
    conn.execute("UPDATE sync_conflicts SET resolved=1,resolution='local',resolved_at='2026-10-05 12:00:00' WHERE field_name='title'")
    conn.execute("UPDATE bugs SET updated_at='2026-10-05 12:00:00'")
    conn.commit()
    sync.sync_bugs_v2(conn, {})
    assert not writes
    assert conn.execute('SELECT count(*) FROM sync_conflicts').fetchone()[0] == 2
    conn.execute("UPDATE sync_conflicts SET resolved=1,resolution='remote',resolved_at='2026-10-05 13:00:00' WHERE field_name='fix_method'")
    conn.execute("UPDATE bugs SET fix_method='Remote method',updated_at='2026-10-05 13:00:00'")
    conn.commit()
    sync.sync_bugs_v2(conn, {})
    assert writes[-1][2]['Title'] == 'Local title'
    assert writes[-1][2]['修复方法'] == 'Remote method'


def task_links(bridge, monkeypatch, baseline=True):
    conn, records, writes, creates = bridge
    conn.execute("INSERT INTO projects (id,name_en) VALUES ('p','P')")
    conn.execute("INSERT INTO workstreams (id,project_id,title_en) VALUES ('w','p','W')")
    conn.execute("INSERT INTO tasks (id,workstream_id,title_en) VALUES ('t','w','Task')")
    conn.commit()
    record = existing(conn, task_id='t')
    conn.execute("INSERT INTO bug_task_links (bug_id,task_id) VALUES ('bug','t')")
    conn.commit()
    record['fields']['Related Task'] = ['rt']
    records.append(record)
    sync._state['tasks_table'] = 'tasks'
    sync._state['last_sync_ts_bugs'] = {'bug':'2026-10-02 12:00:00'}
    if baseline:
        sync._state['bug_task_links_baselines'] = {'bug':['t']}
    monkeypatch.setattr(sync, 'list_records', lambda table: (
        ([{'record_id':'rt','fields':{'kanban_id':'t'}}] if table=='tasks' else copy.deepcopy(records)), True))
    return record


def test_local_unlink_pushes_explicit_empty_feishu_links(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    task_links(bridge, monkeypatch)
    conn.execute("DELETE FROM bug_task_links WHERE bug_id='bug'")
    conn.execute("UPDATE bugs SET task_id=NULL,updated_at='2026-10-03 12:00:00'")
    conn.commit()
    sync.sync_bugs_v2(conn, {})
    assert writes[-1][2]['Related Task'] == []
    assert sync._state['bug_task_links_baselines']['bug'] == []


def test_remote_unlink_clears_junction_and_legacy_and_stays_cleared(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    record = task_links(bridge, monkeypatch)
    record['fields']['Related Task'] = []
    sync.sync_bugs_v2(conn, {})
    assert not conn.execute('SELECT * FROM bug_task_links').fetchall()
    assert conn.execute('SELECT task_id FROM bugs').fetchone()[0] is None
    writes.clear()
    sync.sync_bugs_v2(conn, {})
    assert not writes


def test_unmapped_or_partial_task_mapping_cannot_clear_links(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    record = task_links(bridge, monkeypatch)
    record['fields']['Related Task'] = ['unmapped']
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT count(*) FROM bug_task_links').fetchone()[0] == 1
    assert not writes
    monkeypatch.setattr(sync, 'list_records', lambda table: ([], False))
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT count(*) FROM bug_task_links').fetchone()[0] == 1
    assert sync._state['last_sync_ts_bugs']['bug'] == '2026-10-02 12:00:00'


def test_first_link_disagreement_is_held_for_human_choice(bridge, monkeypatch):
    conn, records, writes, creates = bridge
    record = task_links(bridge, monkeypatch, baseline=False)
    record['fields']['Related Task'] = []
    sync.sync_bugs_v2(conn, {})
    sync.sync_bugs_v2(conn, {})
    assert conn.execute('SELECT count(*) FROM bug_task_links').fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM sync_conflicts WHERE field_name='task_ids' AND resolved=0").fetchone()[0] == 1
    assert not writes

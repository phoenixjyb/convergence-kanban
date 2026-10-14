"""Test both task sync surfaces against real SQLite and mocked transport."""
import copy
import sqlite3

import pytest

import db as database
import feishu_sync as sync


@pytest.fixture(params=['central', 'project'])
def task_bridge(request, tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'kanban.db')
    database.init_db()
    conn = sqlite3.connect(tmp_path / 'kanban.db')
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute("INSERT INTO projects (id,name_en) VALUES ('p','P')")
    conn.execute("INSERT INTO workstreams (id,project_id,title_en) VALUES ('w','p','W')")
    conn.commit()
    records, writes = [], []
    monkeypatch.setattr(sync, '_state', {'tasks_table':'central'})
    monkeypatch.setattr(sync, 'save_state', lambda: None)
    monkeypatch.setattr(sync, '_table_field_names', lambda table: {'Title','Status','Parent Task ID','Start Date','Due Date'})
    monkeypatch.setattr(sync, 'list_records', lambda table: (copy.deepcopy(records), True))
    monkeypatch.setattr(sync, 'update_record', lambda table, rid, fields: writes.append((rid, fields)) or {'code':0})
    monkeypatch.setattr(sync, 'create_record', lambda *args: pytest.fail('Unexpected create'))
    monkeypatch.setattr(sync, 'delete_record', lambda *args: pytest.fail('Unexpected delete'))
    monkeypatch.setattr(sync, 'now_iso', lambda: '2026-10-14 12:00:00')
    key = 'last_sync_ts_tasks' if request.param == 'central' else 'last_sync_ts_p'
    def run():
        if request.param == 'central':
            sync.sync_tasks_v2(conn, {})
        else:
            sync.sync_project_items(conn, 'p', 'project')
    yield conn, records, writes, key, run
    conn.close()


def entity(bridge, kind='task', updated='2026-10-01 12:00:00'):
    conn, records, writes, key, run = bridge
    table, title_field = ('tasks','title_en') if kind == 'task' else ('blockers','description_en')
    conn.execute(f"INSERT INTO {table} (id,workstream_id,{title_field},updated_at) VALUES ('item','w','Local title',?)", (updated,))
    conn.commit()
    record = {'record_id':'rec','fields':{'kanban_id':'item','Title':'Local title','Type':'Task' if kind=='task' else 'Blocker',
              'Status':'todo' if kind=='task' else 'blocked','Workstream':'W','updated_at':'2026-10-01 12:00:00'}}
    records.append(record)
    sync._state[key] = {'item':'2026-10-02 12:00:00'}
    return table, title_field, record


@pytest.mark.parametrize('kind',['task','blocker'])
def test_rejected_push_retains_checkpoint(task_bridge, monkeypatch, kind):
    conn, records, writes, key, run = task_bridge
    table, field, record = entity(task_bridge, kind, '2026-10-03 12:00:00')
    record['fields']['Title'] = 'Remote title'
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code':999})
    run()
    assert sync._state[key]['item'] == '2026-10-02 12:00:00'
    assert conn.execute(f'SELECT {field} FROM {table}').fetchone()[0] == 'Local title'


@pytest.mark.parametrize('kind',['task','blocker'])
def test_rejected_pull_does_not_apply_local_values(task_bridge, monkeypatch, kind):
    conn, records, writes, key, run = task_bridge
    table, field, record = entity(task_bridge, kind)
    record['fields']['Title'] = 'Remote title'
    monkeypatch.setattr(sync, 'update_record', lambda *args: {'code':999})
    run()
    assert conn.execute(f'SELECT {field} FROM {table}').fetchone()[0] == 'Local title'
    assert sync._state[key]['item'] == '2026-10-02 12:00:00'


@pytest.mark.parametrize('kind',['task','blocker'])
def test_conflicts_hold_across_polls_without_duplicates(task_bridge, kind):
    conn, records, writes, key, run = task_bridge
    table, field, record = entity(task_bridge, kind, '2026-10-03 12:00:00')
    record['fields'].update(Title='Remote title', updated_at='2026-10-04 12:00:00')
    run()
    run()
    assert conn.execute('SELECT count(*) FROM sync_conflicts WHERE resolved=0').fetchone()[0] == 1
    assert conn.execute(f'SELECT {field} FROM {table}').fetchone()[0] == 'Local title'
    assert sync._state[key]['item'] == '2026-10-02 12:00:00'
    assert not writes


def test_partial_read_skips_every_mutation(task_bridge, monkeypatch):
    conn, records, writes, key, run = task_bridge
    entity(task_bridge)
    monkeypatch.setattr(sync, 'list_records', lambda table: ([], False))
    run()
    assert not writes
    assert sync._state[key]['item'] == '2026-10-02 12:00:00'


@pytest.mark.parametrize('kind',['task','blocker'])
def test_resolved_choice_can_push_while_snapshot_is_current(task_bridge, kind):
    conn, records, writes, key, run = task_bridge
    table, field, record = entity(task_bridge, kind, '2026-10-03 12:00:00')
    record['fields'].update(Title='Remote title', updated_at='2026-10-04 12:00:00')
    run()
    conn.execute("UPDATE sync_conflicts SET resolved=1,resolution='local',resolved_at='2026-10-05 12:00:00'")
    conn.execute(f"UPDATE {table} SET updated_at='2026-10-05 12:00:00'")
    conn.commit()
    run()
    assert writes[-1][1]['Title'] == 'Local title'
    assert sync._state[key]['item'] == '2026-10-14 12:00:00'


def test_invalid_remote_state_is_not_acknowledged(task_bridge):
    conn, records, writes, key, run = task_bridge
    entity(task_bridge)
    records[0]['fields']['Status'] = 'invalid'
    run()
    assert not writes
    assert conn.execute('SELECT status FROM tasks').fetchone()[0] == 'todo'
    assert sync._state[key]['item'] == '2026-10-02 12:00:00'


@pytest.mark.parametrize('stamp',['2026-10-10 12:00:00','2026-10-01 12:00:00'])
def test_api_edit_during_ack_is_not_overwritten(task_bridge, monkeypatch, stamp):
    conn, records, writes, key, run = task_bridge
    entity(task_bridge)
    records[0]['fields']['Title'] = 'Remote title'
    def concurrent_edit(*args):
        conn.execute("UPDATE tasks SET title_en='Concurrent local edit',updated_at=?", (stamp,))
        conn.commit()
        return {'code':0}
    monkeypatch.setattr(sync, 'update_record', concurrent_edit)
    run()
    assert conn.execute('SELECT title_en FROM tasks').fetchone()[0] == 'Concurrent local edit'
    assert sync._state[key]['item'] == '2026-10-02 12:00:00'


def test_same_second_local_edit_is_detected_by_acknowledged_values(task_bridge):
    conn, records, writes, key, run = task_bridge
    entity(task_bridge)
    run()
    conn.execute("UPDATE tasks SET title_en='Same second edit',updated_at='2026-10-14 12:00:00'")
    conn.commit()
    run()
    assert writes[-1][1]['Title'] == 'Same second edit'
    assert conn.execute('SELECT title_en FROM tasks').fetchone()[0] == 'Same second edit'


def test_feishu_ui_edit_without_timestamp_and_local_edit_conflict(task_bridge):
    conn, records, writes, key, run = task_bridge
    entity(task_bridge)
    run()
    conn.execute("UPDATE tasks SET title_en='Local edit',updated_at='2026-10-14 12:00:00'")
    conn.commit()
    records[0]['fields']['Title'] = 'Remote UI edit'
    run()
    assert conn.execute('SELECT count(*) FROM sync_conflicts WHERE resolved=0').fetchone()[0] == 1
    assert not writes


def parent_entity(task_bridge):
    conn, records, writes, key, run = task_bridge
    conn.execute("INSERT INTO tasks (id,workstream_id,title_en,updated_at) VALUES ('parent','w','Parent','2026-10-01 12:00:00')")
    conn.commit()
    entity(task_bridge, updated='2026-10-03 12:00:00')
    conn.execute("UPDATE tasks SET parent_task_id='parent' WHERE id='item'")
    conn.commit()
    records[0]['fields']['Parent Task ID'] = 'parent'
    records.append({'record_id':'rp','fields':{'kanban_id':'parent','Title':'Parent','Status':'todo','Type':'Task','Workstream':'W','updated_at':'2026-10-01 12:00:00'}})


def test_parent_phase_cannot_bypass_unresolved_conflict(task_bridge):
    conn, records, writes, key, run = task_bridge
    parent_entity(task_bridge)
    records[0]['fields'].update(Title='Remote title', updated_at='2026-10-04 12:00:00')
    run()
    assert not writes
    assert conn.execute('SELECT count(*) FROM sync_conflicts WHERE resolved=0').fetchone()[0] == 1


def test_failed_native_parent_write_is_retried_without_cache_ack(task_bridge, monkeypatch):
    conn, records, writes, key, run = task_bridge
    parent_entity(task_bridge)
    def reject(table, rid, fields):
        writes.append((rid, fields))
        return {'code':999}
    monkeypatch.setattr(sync, 'update_record', reject)
    run()
    run()
    assert len(writes) == 2
    assert not any('item' in value for name, value in sync._state.items() if name.startswith('pushed_parents_'))


def test_missing_optional_parent_field_is_not_sent(task_bridge, monkeypatch):
    conn, records, writes, key, run = task_bridge
    entity(task_bridge, updated='2026-10-03 12:00:00')
    records[0]['fields']['Title'] = 'Remote title'
    monkeypatch.setattr(sync, '_table_field_names', lambda table: {'Title','Status'})
    run()
    assert 'Parent Task ID' not in writes[-1][1]


def test_intentional_local_date_clear_sends_null(task_bridge):
    conn, records, writes, key, run = task_bridge
    entity(task_bridge, updated='2026-10-03 12:00:00')
    records[0]['fields']['Due Date'] = sync._date_to_ms('2026-10-20')
    run()
    assert writes[-1][1]['Due Date'] is None


def test_field_discovery_paginates_and_caches_only_complete_reads(monkeypatch):
    monkeypatch.setattr(sync, '_field_names_cache', {})
    calls = []
    def fields(path):
        calls.append(path)
        if 'page_token=next' in path:
            return {'code':0,'data':{'items':[{'field_name':'Parent Task ID'}],'has_more':False}}
        return {'code':0,'data':{'items':[{'field_name':'Title'}],'has_more':True,'page_token':'next'}}
    monkeypatch.setattr(sync, 'feishu_api', fields)
    assert sync._table_field_names('table') == {'Title','Parent Task ID'}
    assert sync._table_field_names('table') == {'Title','Parent Task ID'}
    assert len(calls) == 2
    monkeypatch.setattr(sync, 'feishu_api', lambda path: {'code':999})
    assert sync._table_field_names('other') is None
    assert 'other' not in sync._field_names_cache


def test_native_parent_field_name_uses_table_capabilities(task_bridge, monkeypatch):
    conn, records, writes, key, run = task_bridge
    parent_entity(task_bridge)
    monkeypatch.setattr(sync, '_table_field_names', lambda table: {'Title','Status','Parent items'})
    run()
    assert writes[-1][1]['Parent items'] == {'record_ids':['rp']}

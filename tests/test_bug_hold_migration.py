import sqlite3

import pytest

from db import _migrate_bug_statuses


def legacy_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE bugs (id TEXT PRIMARY KEY, title TEXT NOT NULL,
          status TEXT CHECK(status IN ('open','closed')),
          feature TEXT, issue_time TEXT, repro_rate TEXT, fix_method TEXT, extra TEXT);
        CREATE INDEX custom_bug_feature ON bugs(feature);
        CREATE TABLE bug_task_links (bug_id TEXT REFERENCES bugs(id) ON DELETE CASCADE, task_id TEXT);
        CREATE TABLE events (bug_id TEXT);
        CREATE TRIGGER custom_bug_trigger AFTER UPDATE ON bugs
          BEGIN INSERT INTO events VALUES (NEW.id); END;
        INSERT INTO bugs VALUES ('b','title','open','camera','2026-10-14','always','method','future column');
        INSERT INTO bug_task_links VALUES ('b','task');
    """)
    return conn


def test_migration_preserves_all_values_links_indexes_triggers_and_foreign_keys():
    with legacy_db() as conn:
        original = conn.execute("SELECT * FROM bugs").fetchall()
        _migrate_bug_statuses(conn)
        assert conn.execute("SELECT * FROM bugs").fetchall() == original
        assert conn.execute("SELECT * FROM bug_task_links").fetchall() == [('b', 'task')]
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='custom_bug_feature'").fetchone()
        conn.execute("UPDATE bugs SET status='hold' WHERE id='b'")
        assert conn.execute("SELECT * FROM events").fetchall() == [('b',)]
        _migrate_bug_statuses(conn)
        assert conn.execute("SELECT count(*) FROM bugs").fetchone()[0] == 1


def test_failed_migration_rolls_back_schema_and_restores_foreign_keys():
    with legacy_db() as conn:
        conn.execute("PRAGMA ignore_check_constraints=ON")
        conn.execute("UPDATE bugs SET status='unexpected'")
        conn.execute("PRAGMA ignore_check_constraints=OFF")
        conn.commit()
        original = conn.execute("SELECT sql FROM sqlite_master WHERE name='bugs'").fetchone()[0]
        with pytest.raises(sqlite3.IntegrityError):
            _migrate_bug_statuses(conn)
        assert conn.execute("SELECT sql FROM sqlite_master WHERE name='bugs'").fetchone()[0] == original
        assert conn.execute("SELECT * FROM bug_task_links").fetchall() == [('b', 'task')]
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("SELECT name FROM sqlite_master WHERE name='bugs_hold_migration'").fetchone() is None


def test_hold_api_create_update_and_filter(client, human_headers):
    response = client.post('/api/bugs', json={'title': 'Paused QA issue', 'status': 'hold'}, headers=human_headers)
    assert response.status_code == 200
    bid = response.json()['id']
    assert any(row['id'] == bid for row in client.get('/api/bugs?status=hold').json())
    assert client.get(f'/api/bugs/{bid}').json()['resolved_at'] is None
    assert client.put(f'/api/bugs/{bid}', json={'status': 'open'}, headers=human_headers).status_code == 200
    assert client.put(f'/api/bugs/{bid}', json={'status': 'hold'}, headers=human_headers).status_code == 200
    assert client.get(f'/api/bugs/{bid}').json()['status'] == 'hold'


def test_csv_import_preserves_hold_status(client, human_headers):
    pid = client.post('/api/projects', json={'name_en': 'CSV Hold Project'}, headers=human_headers).json()['id']
    csv = f'title,severity,project_id,status\nPaused CSV issue,high,{pid},hold\n'
    response = client.post('/api/import/bugs', files={'file': ('bugs.csv', csv, 'text/csv')},
                           headers={'X-Kanban-User': 'test-human'})
    assert response.status_code == 200
    assert response.json()['imported'] == 1
    assert any(row['title'] == 'Paused CSV issue' for row in client.get('/api/bugs?status=hold').json())

"""Database initialization, migrations, and connection management."""

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("KANBAN_DATA_DIR", Path(__file__).parent / "data"))
DB_PATH = DATA_DIR / "kanban.db"
DATA_DIR.mkdir(parents=True, exist_ok=True)

UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20MB


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            display_name TEXT NOT NULL DEFAULT '',
            feishu_open_id TEXT DEFAULT '',
            role        TEXT NOT NULL DEFAULT 'human' CHECK(role IN ('human','bot')),
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS projects (
            id          TEXT PRIMARY KEY,
            name_en     TEXT NOT NULL,
            name_zh     TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            color       TEXT NOT NULL DEFAULT '#6366f1',
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS workstreams (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            title_en    TEXT NOT NULL,
            title_zh    TEXT NOT NULL DEFAULT '',
            owner       TEXT NOT NULL DEFAULT '',
            priority    TEXT NOT NULL DEFAULT 'medium' CHECK(priority IN ('critical','high','medium','low')),
            status      TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','in-progress','blocked','review','done','stable')),
            summary_en  TEXT NOT NULL DEFAULT '',
            summary_zh  TEXT NOT NULL DEFAULT '',
            sort_order  INTEGER NOT NULL DEFAULT 0,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS tasks (
            id              TEXT PRIMARY KEY,
            workstream_id   TEXT NOT NULL REFERENCES workstreams(id) ON DELETE CASCADE,
            parent_task_id  TEXT REFERENCES tasks(id),
            title_en        TEXT NOT NULL,
            title_zh        TEXT NOT NULL DEFAULT '',
            assignee        TEXT NOT NULL DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','in_review','done','blocked','abandoned')),
            start_date      TEXT,
            due_date        TEXT,
            notes           TEXT NOT NULL DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS blockers (
            id              TEXT PRIMARY KEY,
            workstream_id   TEXT NOT NULL REFERENCES workstreams(id) ON DELETE CASCADE,
            description_en  TEXT NOT NULL,
            description_zh  TEXT NOT NULL DEFAULT '',
            assignee        TEXT NOT NULL DEFAULT '',
            notes           TEXT NOT NULL DEFAULT '',
            resolved        INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at     TEXT,
            deleted_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS bugs (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            description     TEXT NOT NULL DEFAULT '',
            severity        TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('critical','high','medium','low')),
            status          TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','investigating','fixing','fix_complete','to_verify','resolved','closed','wontfix')),
            reporter        TEXT NOT NULL DEFAULT '',
            assignee        TEXT NOT NULL DEFAULT '',
            workstream_id   TEXT REFERENCES workstreams(id),
            task_id         TEXT REFERENCES tasks(id),
            project_id      TEXT REFERENCES projects(id),
            environment     TEXT NOT NULL DEFAULT '',
            steps_to_reproduce TEXT NOT NULL DEFAULT '',
            issue_version   TEXT NOT NULL DEFAULT '',
            device_id       TEXT NOT NULL DEFAULT '',
            issue_images    TEXT NOT NULL DEFAULT '',
            source          TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','agent')),
            display_id      TEXT NOT NULL DEFAULT '',
            fix_method      TEXT NOT NULL DEFAULT '',
            fix_version     TEXT NOT NULL DEFAULT '',
            fix_date        TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at     TEXT,
            deleted_at      TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_bugs_project ON bugs(project_id);
        CREATE INDEX IF NOT EXISTS idx_bugs_ws ON bugs(workstream_id);
        CREATE INDEX IF NOT EXISTS idx_bugs_task ON bugs(task_id);
        CREATE INDEX IF NOT EXISTS idx_bugs_status ON bugs(status);

        CREATE TABLE IF NOT EXISTS activity_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type TEXT NOT NULL,
            entity_id   TEXT NOT NULL,
            actor       TEXT NOT NULL DEFAULT 'system',
            action      TEXT NOT NULL,
            detail      TEXT NOT NULL DEFAULT '',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_ws_project ON workstreams(project_id);
        CREATE INDEX IF NOT EXISTS idx_tasks_ws ON tasks(workstream_id);
        CREATE INDEX IF NOT EXISTS idx_blockers_ws ON blockers(workstream_id);
        CREATE INDEX IF NOT EXISTS idx_activity_time ON activity_log(created_at DESC);
        """)
        # Migration: add deleted_at columns to existing tables
        for table in ("projects", "workstreams", "tasks", "blockers"):
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN deleted_at TEXT")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Migration: add start_date to tasks
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN start_date TEXT")
        except sqlite3.OperationalError:
            pass
        # Migration: add parent_task_id to tasks (subtasks support)
        try:
            conn.execute("ALTER TABLE tasks ADD COLUMN parent_task_id TEXT REFERENCES tasks(id)")
        except sqlite3.OperationalError:
            pass
        # Migration: add users table if upgrading
        try:
            conn.execute("SELECT 1 FROM users LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("""CREATE TABLE users (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now')))""")
        # Migration: add feishu_open_id to users
        try:
            conn.execute("ALTER TABLE users ADD COLUMN feishu_open_id TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass
        # Migration: add role to users
        try:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'human'")
        except sqlite3.OperationalError:
            pass
        # Migration: comments table
        conn.execute("""CREATE TABLE IF NOT EXISTS comments (
            id          TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            entity_id   TEXT NOT NULL,
            author      TEXT NOT NULL DEFAULT '',
            body        TEXT NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comments_entity ON comments(entity_type, entity_id)")
        # Migration: templates table (v0.4)
        conn.execute("""CREATE TABLE IF NOT EXISTS templates (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            project_id  TEXT REFERENCES projects(id),
            structure   TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at  TEXT
        )""")
        # Migration: snapshots table for analytics (v0.4)
        conn.execute("""CREATE TABLE IF NOT EXISTS snapshots (
            id          TEXT PRIMARY KEY,
            date        TEXT NOT NULL UNIQUE,
            data        TEXT NOT NULL DEFAULT '{}',
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        # Migration: task_dependencies table (v0.5)
        conn.execute("""CREATE TABLE IF NOT EXISTS task_dependencies (
            id            TEXT PRIMARY KEY,
            task_id       TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            depends_on_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            dep_type      TEXT NOT NULL DEFAULT 'blocked_by' CHECK(dep_type IN ('blocked_by','related')),
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(task_id, depends_on_id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dep_task ON task_dependencies(task_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_dep_depends ON task_dependencies(depends_on_id)")
        # Migration: time_entries table (v0.5)
        conn.execute("""CREATE TABLE IF NOT EXISTS time_entries (
            id          TEXT PRIMARY KEY,
            task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            user_name   TEXT NOT NULL DEFAULT '',
            minutes     INTEGER NOT NULL DEFAULT 0,
            description TEXT NOT NULL DEFAULT '',
            date        TEXT NOT NULL DEFAULT (date('now')),
            created_at  TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_time_task ON time_entries(task_id)")
        # Migration: attachments table (v0.5)
        conn.execute("""CREATE TABLE IF NOT EXISTS attachments (
            id            TEXT PRIMARY KEY,
            entity_type   TEXT NOT NULL CHECK(entity_type IN ('task','bug','workstream')),
            entity_id     TEXT NOT NULL,
            filename      TEXT NOT NULL,
            original_name TEXT NOT NULL,
            mime_type     TEXT NOT NULL DEFAULT 'application/octet-stream',
            size_bytes    INTEGER NOT NULL DEFAULT 0,
            uploader      TEXT NOT NULL DEFAULT '',
            created_at    TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at    TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_attach_entity ON attachments(entity_type, entity_id)")
        # Migration: recurring_tasks table (v0.5)
        conn.execute("""CREATE TABLE IF NOT EXISTS recurring_tasks (
            id              TEXT PRIMARY KEY,
            workstream_id   TEXT NOT NULL REFERENCES workstreams(id) ON DELETE CASCADE,
            title_en        TEXT NOT NULL,
            title_zh        TEXT NOT NULL DEFAULT '',
            assignee        TEXT NOT NULL DEFAULT '',
            notes           TEXT NOT NULL DEFAULT '',
            schedule        TEXT NOT NULL DEFAULT 'weekly' CHECK(schedule IN ('daily','weekly','biweekly','monthly')),
            day_of_week     INTEGER DEFAULT NULL,
            day_of_month    INTEGER DEFAULT NULL,
            last_created    TEXT,
            next_due        TEXT,
            active          INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            deleted_at      TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_recurring_ws ON recurring_tasks(workstream_id)")
        # Migration: sync_conflicts table (v0.5)
        conn.execute("""CREATE TABLE IF NOT EXISTS sync_conflicts (
            id              TEXT PRIMARY KEY,
            entity_type     TEXT NOT NULL CHECK(entity_type IN ('task','blocker','bug')),
            entity_id       TEXT NOT NULL,
            field_name      TEXT NOT NULL,
            local_value     TEXT NOT NULL DEFAULT '',
            remote_value    TEXT NOT NULL DEFAULT '',
            local_updated   TEXT NOT NULL DEFAULT '',
            remote_updated  TEXT NOT NULL DEFAULT '',
            resolved        INTEGER NOT NULL DEFAULT 0,
            resolution      TEXT CHECK(resolution IN ('local','remote','manual',NULL)),
            resolved_by     TEXT NOT NULL DEFAULT '',
            resolved_at     TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conflict_entity ON sync_conflicts(entity_type, entity_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conflict_unresolved ON sync_conflicts(resolved)")
        # Migration: keep tasks status CHECK constraint in sync with latest valid set.
        # SQLite can't ALTER CHECK constraints, so probe-and-recreate.
        # Probe with the most recently added status — this catches DBs missing any of: in_review, abandoned.
        _needs_task_migration = False
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("INSERT INTO tasks (id, workstream_id, title_en, status) VALUES ('__chk__', (SELECT id FROM workstreams LIMIT 1), '__chk__', 'abandoned')")
            conn.execute("DELETE FROM tasks WHERE id='__chk__'")
            conn.execute("PRAGMA foreign_keys=ON")
        except (sqlite3.IntegrityError, sqlite3.OperationalError):
            _needs_task_migration = True
            conn.execute("PRAGMA foreign_keys=ON")
        if _needs_task_migration:
            conn.execute("DROP TABLE IF EXISTS tasks_new")
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("""CREATE TABLE tasks_new (
                id TEXT PRIMARY KEY, workstream_id TEXT NOT NULL REFERENCES workstreams(id) ON DELETE CASCADE,
                parent_task_id TEXT, title_en TEXT NOT NULL, title_zh TEXT NOT NULL DEFAULT '',
                assignee TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'todo' CHECK(status IN ('todo','doing','in_review','done','blocked','abandoned')),
                start_date TEXT, due_date TEXT, notes TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')), updated_at TEXT NOT NULL DEFAULT (datetime('now')), deleted_at TEXT)""")
            conn.execute("""INSERT INTO tasks_new (id, workstream_id, parent_task_id, title_en, title_zh,
                assignee, status, start_date, due_date, notes, sort_order, created_at, updated_at, deleted_at)
                SELECT id, workstream_id, parent_task_id, title_en, COALESCE(title_zh,''),
                COALESCE(assignee,''), COALESCE(status,'todo'), start_date, due_date, COALESCE(notes,''),
                COALESCE(sort_order,0), created_at, updated_at, deleted_at FROM tasks""")
            conn.execute("DROP TABLE tasks")
            conn.execute("ALTER TABLE tasks_new RENAME TO tasks")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_ws ON tasks(workstream_id)")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.commit()

        # ── v0.9.1: add priority column to tasks ───────────────────────────
        task_cols = {c[1] for c in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "priority" not in task_cols:
            conn.execute("ALTER TABLE tasks ADD COLUMN priority TEXT NOT NULL DEFAULT 'medium'")
            conn.commit()

        # ── v0.9.4: new bug fields (issue_time, feature, repro_rate) ──────
        # ── v1.4.5: added issue_version, device_id, issue_images (team-added columns)
        # No updated_at bump on migration: new columns default to empty, and we
        # want Feishu's existing values to PULL into kanban (not the reverse).
        bug_cols = {c[1] for c in conn.execute("PRAGMA table_info(bugs)").fetchall()}
        for col, typedef in [
            ("issue_time", "TEXT"),
            ("feature", "TEXT NOT NULL DEFAULT ''"),
            ("repro_rate", "TEXT NOT NULL DEFAULT ''"),
            ("issue_version", "TEXT NOT NULL DEFAULT ''"),
            ("device_id", "TEXT NOT NULL DEFAULT ''"),
            # JSON array of {file_token, name, size, type} dicts (attachments from Feishu)
            ("issue_images", "TEXT NOT NULL DEFAULT ''"),
            # Source: 'manual' (QA team) or 'agent' (AI agent submitted)
            ("source", "TEXT NOT NULL DEFAULT 'manual'"),
            # Human-readable bug ID: BUG-MMDD-NNN or RD-MMDD-NNN
            ("display_id", "TEXT NOT NULL DEFAULT ''"),
            # Fix metadata — populated when bug is fixed/verified
            ("fix_method", "TEXT NOT NULL DEFAULT ''"),
            ("fix_version", "TEXT NOT NULL DEFAULT ''"),
            ("fix_date", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if col not in bug_cols:
                conn.execute(f"ALTER TABLE bugs ADD COLUMN {col} {typedef}")
        conn.commit()
        conn.execute("CREATE INDEX IF NOT EXISTS idx_bugs_source ON bugs(source)")

        # ── v1.4.5: promote blockers to first-class (assignee + notes + updated_at) ──
        blocker_cols = {c[1] for c in conn.execute("PRAGMA table_info(blockers)").fetchall()}
        for col, typedef in [
            ("assignee",   "TEXT NOT NULL DEFAULT ''"),
            ("notes",      "TEXT NOT NULL DEFAULT ''"),
            # SQLite ALTER TABLE cannot add a column with non-constant DEFAULT,
            # so we use '' as default and backfill existing rows below.
            ("updated_at", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if col not in blocker_cols:
                conn.execute(f"ALTER TABLE blockers ADD COLUMN {col} {typedef}")
        # Backfill: any blocker row whose updated_at is empty/NULL needs to be
        # bumped to NOW, so the first sync cycle after this migration PUSHes
        # its current state (with new assignee/notes) out to all Feishu tables
        # instead of PULLing stale values back. UTC+8 to match app TZ.
        conn.execute(
            "UPDATE blockers SET updated_at = "
            "strftime('%Y-%m-%d %H:%M:%S', datetime('now', '+8 hours')) "
            "WHERE updated_at = '' OR updated_at IS NULL"
        )
        conn.commit()

        # ── v0.9.4: bug_task_links junction table (many-to-many) ─────────
        conn.execute("""CREATE TABLE IF NOT EXISTS bug_task_links (
            bug_id   TEXT NOT NULL REFERENCES bugs(id) ON DELETE CASCADE,
            task_id  TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (bug_id, task_id)
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_btl_bug ON bug_task_links(bug_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_btl_task ON bug_task_links(task_id)")
        # Migrate existing bugs.task_id into bug_task_links
        conn.execute("""INSERT OR IGNORE INTO bug_task_links (bug_id, task_id)
            SELECT id, task_id FROM bugs
            WHERE task_id IS NOT NULL AND task_id != '' AND deleted_at IS NULL""")

        # ── v1.1: wip_limits column on projects ──────────────────────
        proj_cols = {c[1] for c in conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "wip_limits" not in proj_cols:
            conn.execute("ALTER TABLE projects ADD COLUMN wip_limits TEXT NOT NULL DEFAULT '{}'")
            conn.commit()

        # ── v1.1: notification_preferences table ─────────────────────
        conn.execute("""CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id    TEXT NOT NULL REFERENCES users(id),
            channel    TEXT NOT NULL DEFAULT 'feishu'
                       CHECK(channel IN ('feishu','webhook','none')),
            overdue    INTEGER NOT NULL DEFAULT 1,
            stale      INTEGER NOT NULL DEFAULT 1,
            blocker    INTEGER NOT NULL DEFAULT 1,
            digest     INTEGER NOT NULL DEFAULT 1,
            stale_days INTEGER NOT NULL DEFAULT 3,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (user_id, channel)
        )""")

        # ── v1.5/1.4.8: keep bugs status CHECK in sync (added: to_verify, fix_complete) ──
        # Probe with the most recently added status. If the constraint hasn't
        # been rebuilt to include it, do the rebuild now.
        _needs_bug_migration = False
        try:
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("INSERT INTO bugs (id, title, status) VALUES ('__chk_fc__', '__chk__', 'fix_complete')")
            conn.execute("DELETE FROM bugs WHERE id='__chk_fc__'")
            conn.execute("PRAGMA foreign_keys=ON")
        except (sqlite3.IntegrityError, sqlite3.OperationalError):
            _needs_bug_migration = True
            conn.execute("PRAGMA foreign_keys=ON")
        if _needs_bug_migration:
            conn.execute("DROP TABLE IF EXISTS bugs_new")
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("""CREATE TABLE bugs_new (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
                severity TEXT NOT NULL DEFAULT 'medium' CHECK(severity IN ('critical','high','medium','low')),
                status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','investigating','fixing','fix_complete','to_verify','resolved','closed','wontfix')),
                reporter TEXT NOT NULL DEFAULT '', assignee TEXT NOT NULL DEFAULT '',
                workstream_id TEXT REFERENCES workstreams(id), task_id TEXT REFERENCES tasks(id),
                project_id TEXT REFERENCES projects(id), environment TEXT NOT NULL DEFAULT '',
                steps_to_reproduce TEXT NOT NULL DEFAULT '',
                issue_version TEXT NOT NULL DEFAULT '', device_id TEXT NOT NULL DEFAULT '',
                issue_images TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT 'manual' CHECK(source IN ('manual','agent')),
                display_id TEXT NOT NULL DEFAULT '',
                fix_method TEXT NOT NULL DEFAULT '',
                fix_version TEXT NOT NULL DEFAULT '',
                fix_date TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                resolved_at TEXT, deleted_at TEXT)""")
            conn.execute("""INSERT INTO bugs_new (id, title, description, severity, status, reporter,
                assignee, workstream_id, task_id, project_id, environment, steps_to_reproduce,
                issue_version, device_id, issue_images, source, display_id,
                fix_method, fix_version, fix_date,
                created_at, updated_at, resolved_at, deleted_at)
                SELECT id, title, description, severity, status, reporter,
                assignee, workstream_id, task_id, project_id, environment, steps_to_reproduce,
                COALESCE(issue_version,''), COALESCE(device_id,''), COALESCE(issue_images,''),
                COALESCE(source,'manual'), COALESCE(display_id,''),
                COALESCE(fix_method,''), COALESCE(fix_version,''), COALESCE(fix_date,''),
                created_at, updated_at, resolved_at, deleted_at FROM bugs""")
            conn.execute("DROP TABLE bugs")
            conn.execute("ALTER TABLE bugs_new RENAME TO bugs")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bugs_project ON bugs(project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bugs_ws ON bugs(workstream_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bugs_task ON bugs(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bugs_status ON bugs(status)")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.commit()

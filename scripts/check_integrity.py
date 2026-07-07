#!/usr/bin/env python3
"""
Data integrity check for ConvergenceKanban.
Scans SQLite DB for orphaned records, broken references, and inconsistencies.

Usage:
    KANBAN_DATA_DIR=data python scripts/check_integrity.py
    KANBAN_DATA_DIR=data python scripts/check_integrity.py --fix
"""

import os
import sqlite3
import sys

DATA_DIR = os.getenv("KANBAN_DATA_DIR", "data")
DB_PATH = os.path.join(DATA_DIR, "kanban.db")
FIX_MODE = "--fix" in sys.argv


def check(conn):
    issues = []

    # 1. Orphaned workstreams (no parent project)
    rows = conn.execute("""
        SELECT w.id, w.title_en FROM workstreams w
        LEFT JOIN projects p ON w.project_id = p.id
        WHERE p.id IS NULL AND w.deleted_at IS NULL
    """).fetchall()
    for r in rows:
        issues.append(("ORPHAN", f"Workstream {r[0]} '{r[1]}' has no parent project"))

    # 2. Orphaned tasks (no parent workstream)
    rows = conn.execute("""
        SELECT t.id, t.title_en FROM tasks t
        LEFT JOIN workstreams w ON t.workstream_id = w.id
        WHERE w.id IS NULL AND t.deleted_at IS NULL
    """).fetchall()
    for r in rows:
        issues.append(("ORPHAN", f"Task {r[0]} '{r[1]}' has no parent workstream"))

    # 3. Orphaned blockers
    rows = conn.execute("""
        SELECT b.id, b.description_en FROM blockers b
        LEFT JOIN workstreams w ON b.workstream_id = w.id
        WHERE w.id IS NULL AND b.resolved_at IS NULL
    """).fetchall()
    for r in rows:
        issues.append(("ORPHAN", f"Blocker {r[0]} '{r[1]}' has no parent workstream"))

    # 4. Orphaned bug-task links
    rows = conn.execute("""
        SELECT btl.bug_id, btl.task_id FROM bug_task_links btl
        LEFT JOIN bugs bg ON btl.bug_id = bg.id
        LEFT JOIN tasks t ON btl.task_id = t.id
        WHERE bg.id IS NULL OR t.id IS NULL
    """).fetchall()
    for r in rows:
        issues.append(("BROKEN_LINK", f"Bug-task link {r[0]}→{r[1]} has missing bug or task"))

    # 5. Invalid task statuses
    valid_statuses = {"todo", "doing", "in_review", "done", "blocked"}
    rows = conn.execute("SELECT id, title_en, status FROM tasks WHERE deleted_at IS NULL").fetchall()
    for r in rows:
        if r[2] not in valid_statuses:
            issues.append(("INVALID", f"Task {r[0]} '{r[1]}' has invalid status '{r[2]}'"))

    # 6. Duplicate users (same name, different IDs)
    rows = conn.execute("""
        SELECT name, COUNT(*) as cnt FROM users GROUP BY LOWER(name) HAVING cnt > 1
    """).fetchall()
    for r in rows:
        issues.append(("DUPLICATE", f"User '{r[0]}' has {r[1]} duplicate entries"))

    # 7. Tasks assigned to non-existent users
    rows = conn.execute("""
        SELECT t.id, t.title_en, t.assignee FROM tasks t
        WHERE t.assignee IS NOT NULL AND t.assignee != ''
        AND t.deleted_at IS NULL
        AND NOT EXISTS (SELECT 1 FROM users u WHERE LOWER(u.name) = LOWER(t.assignee))
    """).fetchall()
    for r in rows:
        issues.append(("WARN", f"Task {r[0]} '{r[1]}' assigned to unknown user '{r[2]}'"))

    # 8. SQLite integrity check
    result = conn.execute("PRAGMA integrity_check").fetchone()
    if result[0] != "ok":
        issues.append(("CRITICAL", f"SQLite integrity check failed: {result[0]}"))

    # 9. Foreign key violations
    rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    for r in rows:
        issues.append(("FK_VIOLATION", f"Table {r[0]} row {r[1]} → {r[2]} (parent missing)"))

    return issues


def fix(conn, issues):
    fixed = 0
    for kind, desc in issues:
        if kind == "BROKEN_LINK":
            # Remove orphaned bug-task links
            conn.execute("""
                DELETE FROM bug_task_links WHERE
                bug_id NOT IN (SELECT id FROM bugs) OR
                task_id NOT IN (SELECT id FROM tasks)
            """)
            fixed += 1
    if fixed:
        conn.commit()
    return fixed


def main():
    if not os.path.exists(DB_PATH):
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    conn = sqlite3.connect(DB_PATH)
    issues = check(conn)

    if not issues:
        print("All checks passed. No issues found.")
        sys.exit(0)

    print(f"Found {len(issues)} issue(s):\n")
    for kind, desc in issues:
        icon = {"CRITICAL": "🔴", "ORPHAN": "🟠", "BROKEN_LINK": "🟡",
                "DUPLICATE": "🟡", "INVALID": "🟠", "FK_VIOLATION": "🔴",
                "WARN": "⚪"}.get(kind, "●")
        print(f"  {icon} [{kind}] {desc}")

    if FIX_MODE:
        fixed = fix(conn, issues)
        print(f"\nFixed {fixed} auto-fixable issue(s).")
    else:
        print("\nRun with --fix to auto-fix where possible.")

    conn.close()
    sys.exit(1 if any(k in ("CRITICAL", "FK_VIOLATION") for k, _ in issues) else 0)


if __name__ == "__main__":
    main()

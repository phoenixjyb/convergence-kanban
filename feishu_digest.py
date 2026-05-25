#!/usr/bin/env python3
"""
ConvergenceKanban — Weekly Digest.
Posts a summary card to Feishu group webhook.
Run via systemd timer or cron: Monday 9 AM.

Usage:
    python feishu_digest.py
    # Requires FEISHU_WEBHOOK_URL in .env or environment
"""

import json
import os
import sqlite3
import urllib.request
from datetime import datetime, timedelta, timezone

# Project-wide timezone: Asia/Shanghai (UTC+8)
TZ = timezone(timedelta(hours=8))
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DATA_DIR = Path(os.getenv("KANBAN_DATA_DIR", Path(__file__).parent / "data"))
DB_PATH = DATA_DIR / "kanban.db"
WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")


def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def post_webhook(card: dict):
    if not WEBHOOK_URL:
        print("FEISHU_WEBHOOK_URL not set, printing to stdout instead:")
        print(json.dumps(card, indent=2, ensure_ascii=False))
        return
    body = json.dumps({"msg_type": "interactive", "card": card}).encode()
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    resp = opener.open(req, timeout=10)
    print(f"Webhook response: {resp.status}")


def build_digest():
    conn = get_db()
    try:
        return _build_digest_inner(conn)
    finally:
        conn.close()


def _build_digest_inner(conn):
    one_week_ago = (datetime.now(TZ) - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

    # Tasks completed this week
    done_tasks = conn.execute(
        "SELECT t.title_en, t.assignee, w.title_en as ws_title, p.name_en as proj_name "
        "FROM tasks t JOIN workstreams w ON t.workstream_id=w.id "
        "JOIN projects p ON w.project_id=p.id "
        "WHERE t.status='done' AND t.updated_at>=? AND t.deleted_at IS NULL",
        (one_week_ago,)
    ).fetchall()

    # New blockers this week
    new_blockers = conn.execute(
        "SELECT b.description_en, w.title_en as ws_title, p.name_en as proj_name "
        "FROM blockers b JOIN workstreams w ON b.workstream_id=w.id "
        "JOIN projects p ON w.project_id=p.id "
        "WHERE b.created_at>=? AND b.deleted_at IS NULL",
        (one_week_ago,)
    ).fetchall()

    # Active blockers
    active_blockers = conn.execute(
        "SELECT b.description_en, w.title_en as ws_title, p.name_en as proj_name "
        "FROM blockers b JOIN workstreams w ON b.workstream_id=w.id "
        "JOIN projects p ON w.project_id=p.id "
        "WHERE b.resolved=0 AND b.deleted_at IS NULL"
    ).fetchall()

    # Per-project stats
    projects = conn.execute(
        "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY sort_order, name_en"
    ).fetchall()
    proj_stats = []
    for p in projects:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM tasks t JOIN workstreams w ON t.workstream_id=w.id "
            "WHERE w.project_id=? AND t.deleted_at IS NULL", (p["id"],)
        ).fetchone()["c"]
        done = conn.execute(
            "SELECT COUNT(*) as c FROM tasks t JOIN workstreams w ON t.workstream_id=w.id "
            "WHERE w.project_id=? AND t.status='done' AND t.deleted_at IS NULL", (p["id"],)
        ).fetchone()["c"]
        pct = round(done / total * 100) if total > 0 else 0
        proj_stats.append({"name": p["name_en"], "total": total, "done": done, "pct": pct})

    # Build card
    elements = []

    # Summary line
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md",
                 "content": f"**Completed this week:** {len(done_tasks)} tasks | "
                            f"**New blockers:** {len(new_blockers)} | "
                            f"**Active blockers:** {len(active_blockers)}"}
    })
    elements.append({"tag": "hr"})

    # Per-project progress
    proj_lines = []
    for ps in proj_stats:
        bar = "=" * (ps["pct"] // 10) + "-" * (10 - ps["pct"] // 10)
        proj_lines.append(f"**{ps['name']}**: {ps['done']}/{ps['total']} ({ps['pct']}%) [{bar}]")
    if proj_lines:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**Project Progress:**\n" + "\n".join(proj_lines)}
        })
        elements.append({"tag": "hr"})

    # Completed tasks
    if done_tasks:
        done_lines = [f"- {t['title_en']} ({t['proj_name']}/{t['ws_title']})"
                      + (f" @{t['assignee']}" if t["assignee"] else "")
                      for t in done_tasks[:15]]
        if len(done_tasks) > 15:
            done_lines.append(f"... and {len(done_tasks) - 15} more")
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**Completed Tasks:**\n" + "\n".join(done_lines)}
        })

    # Active blockers
    if active_blockers:
        blocker_lines = [f"- {b['description_en']} ({b['proj_name']}/{b['ws_title']})"
                         for b in active_blockers[:10]]
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**Active Blockers:**\n" + "\n".join(blocker_lines)}
        })

    now_str = datetime.now(TZ).strftime("%Y-%m-%d")
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": f"ConvergenceKanban Weekly Digest — {now_str}"}]
    })

    card = {
        "header": {
            "title": {"tag": "plain_text", "content": "Weekly Kanban Digest"},
            "template": "indigo",
        },
        "elements": elements,
    }
    return card


if __name__ == "__main__":
    card = build_digest()
    post_webhook(card)

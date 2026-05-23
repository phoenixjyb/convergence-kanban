#!/usr/bin/env python3
"""
Scheduled alert runner — detects overdue/stale/aging issues and sends Feishu notifications.

Usage:
    python alert_runner.py                  # run once, send alerts
    python alert_runner.py --dry-run        # preview without sending

Designed to run via cron every 4 hours:
    0 */4 * * * cd /opt/convergence-kanban && venv/bin/python alert_runner.py
"""

import json
import os
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env.team")
load_dotenv(Path(__file__).parent / ".env")

from alerts import find_overdue_tasks, find_stale_tasks, find_aging_blockers
from db import get_db

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
DRY_RUN = "--dry-run" in sys.argv


def post_feishu_card(title: str, content: str, color: str = "orange"):
    """Post an interactive card to Feishu webhook."""
    if not WEBHOOK_URL:
        print("[alert] No FEISHU_WEBHOOK_URL set, skipping webhook")
        return
    if DRY_RUN:
        print(f"[dry-run] Would post card: {title}")
        return

    card = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": content}}
            ],
        },
    }
    data = json.dumps(card).encode()
    req = urllib.request.Request(
        WEBHOOK_URL, data=data, method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.open(req, timeout=10)
    except Exception as e:
        print(f"[alert] Webhook failed: {e}")


def run():
    with get_db() as conn:
        overdue = find_overdue_tasks(conn)
        stale = find_stale_tasks(conn, days=3)
        aging = find_aging_blockers(conn, hours=48)

    total = len(overdue) + len(stale) + len(aging)
    if total == 0:
        print("[alert] No alerts — all clear")
        return

    print(f"[alert] Found {len(overdue)} overdue, {len(stale)} stale, {len(aging)} aging blockers")

    # Build card content
    sections = []

    if overdue:
        lines = []
        for t in overdue[:10]:
            assignee = t.get("assignee") or "unassigned"
            lines.append(
                f"• **{t['title_en']}** ({t['project']}/{t['workstream']}) "
                f"— {assignee}, {t['days_overdue']}d overdue"
            )
        sections.append(f"**Overdue Tasks ({len(overdue)})**\n" + "\n".join(lines))

    if stale:
        lines = []
        for t in stale[:10]:
            assignee = t.get("assignee") or "unassigned"
            lines.append(
                f"• **{t['title_en']}** ({t['project']}/{t['workstream']}) "
                f"— {assignee}, no update for {t['stale_days']}d"
            )
        sections.append(f"**Stale Tasks ({len(stale)})**\n" + "\n".join(lines))

    if aging:
        lines = []
        for b in aging[:10]:
            lines.append(
                f"• **{b['description_en']}** ({b['project']}/{b['workstream']}) "
                f"— {b['age_hours']}h unresolved"
            )
        sections.append(f"**Aging Blockers ({len(aging)})**\n" + "\n".join(lines))

    content = "\n\n---\n\n".join(sections)
    color = "red" if overdue or aging else "orange"
    post_feishu_card(f"Kanban Alerts: {total} issues need attention", content, color)
    print("[alert] Card posted to Feishu")


if __name__ == "__main__":
    run()

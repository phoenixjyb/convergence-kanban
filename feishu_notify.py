"""
Feishu Webhook Notifications for ConvergenceKanban.
Sends card messages to a Feishu group chat when tasks/blockers change.
No-op if FEISHU_WEBHOOK_URL is not set.
"""

import json
import os
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime, timedelta, timezone

# Project-wide timezone: Asia/Shanghai (UTC+8)
TZ = timezone(timedelta(hours=8))

WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
DEBOUNCE_SEC = 5  # buffer events for bulk operations

_buffer: deque = deque()
_lock = threading.Lock()
_timer: threading.Timer | None = None


def _now_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _post_webhook(card: dict):
    """POST a card message to Feishu webhook. Silently ignores errors."""
    if not WEBHOOK_URL:
        return
    body = json.dumps({"msg_type": "interactive", "card": card}).encode()
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    # Bypass proxy
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(req, timeout=10)
    except Exception as e:
        print(f"[notify] webhook error: {e}", flush=True)


def _status_color(status: str) -> str:
    return {"done": "green", "blocked": "red", "doing": "blue"}.get(status, "grey")


def _build_card(title: str, color: str, fields: list[tuple[str, str]]) -> dict:
    elements = []
    for label, value in fields:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**{label}:** {value}"}
        })
    elements.append({
        "tag": "note",
        "elements": [{"tag": "plain_text", "content": _now_str()}]
    })
    return {
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color,
        },
        "elements": elements,
    }


def _flush():
    """Flush buffered events as cards."""
    with _lock:
        events = list(_buffer)
        _buffer.clear()
    for card in events:
        _post_webhook(card)


def _schedule_flush():
    global _timer
    with _lock:
        if _timer is not None:
            _timer.cancel()
        _timer = threading.Timer(DEBOUNCE_SEC, _flush)
        _timer.daemon = True
        _timer.start()


def _enqueue(card: dict):
    if not WEBHOOK_URL:
        return
    with _lock:
        _buffer.append(card)
    _schedule_flush()


# ── Public API ────────────────────────────────────────────────────────────

def notify_task_created(title: str, project: str, workstream: str, assignee: str, actor: str):
    card = _build_card("New Task Created", "blue", [
        ("Task", title),
        ("Project", project),
        ("Workstream", workstream),
        ("Assignee", assignee or "-"),
        ("Created by", actor),
    ])
    _enqueue(card)


def notify_task_status_changed(title: str, project: str, workstream: str,
                                old_status: str, new_status: str, actor: str):
    color = _status_color(new_status)
    card = _build_card(f"Task Status: {old_status} -> {new_status}", color, [
        ("Task", title),
        ("Project", project),
        ("Workstream", workstream),
        ("Status", f"{old_status} -> **{new_status}**"),
        ("Updated by", actor),
    ])
    _enqueue(card)


def notify_blocker_created(description: str, project: str, workstream: str, actor: str):
    card = _build_card("Blocker Reported", "red", [
        ("Blocker", description),
        ("Project", project),
        ("Workstream", workstream),
        ("Reported by", actor),
    ])
    _enqueue(card)


def notify_blocker_resolved(description: str, project: str, workstream: str, actor: str):
    card = _build_card("Blocker Resolved", "green", [
        ("Blocker", description),
        ("Project", project),
        ("Workstream", workstream),
        ("Resolved by", actor),
    ])
    _enqueue(card)


def notify_bug_created(title: str, severity: str, reporter: str):
    card = _build_card("Bug Reported", "red", [
        ("Bug", title),
        ("Severity", severity),
        ("Reporter", reporter),
    ])
    _enqueue(card)

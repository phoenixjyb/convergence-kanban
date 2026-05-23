"""Slack webhook notifications for ConvergenceKanban.

Posts Block Kit messages to a Slack Incoming Webhook on bug/blocker/task
events. Mirrors the public API of feishu_notify so the same dispatcher
fans both out.

No-op if SLACK_WEBHOOK_URL is not set. Pure stdlib (urllib) — no SDK
required.

Setup:
    1. Create an Incoming Webhook in your Slack workspace:
       https://api.slack.com/messaging/webhooks
    2. Pick the channel you want notifications in.
    3. Paste the webhook URL into .env as SLACK_WEBHOOK_URL.

Format: Block Kit headers + section fields, colored by severity / status
via emoji prefix (Slack webhooks don't accept color attribute on Block Kit
posts directly; legacy `attachments` color is used as a sidebar fallback).
"""

import json
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# Project-wide TZ: UTC+8 (Asia/Shanghai). Change in helpers.py for other regions.
TZ = timezone(timedelta(hours=8))

WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

# Debounce: collapse rapid-fire events (e.g. bulk status updates) into one
# digest per ~5s window, same pattern as feishu_notify.
_buffer: list[dict] = []
_lock = threading.Lock()
_timer: threading.Timer | None = None
_DEBOUNCE_SECONDS = 5


def _now_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _post_webhook(payload: dict) -> None:
    """POST a payload to Slack. Silently ignores errors so a flaky Slack
    instance cannot break kanban writes."""
    if not WEBHOOK_URL:
        return
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        WEBHOOK_URL,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    # Bypass any local HTTP proxy that might intercept hooks.slack.com
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(req, timeout=10)
    except Exception as e:
        print(f"[slack-notify] webhook error: {e}", flush=True)


# Severity / status → emoji (Slack rendering is more idiomatic with emoji
# than with Block Kit colors).
_SEV_EMOJI = {
    "critical": ":rotating_light:",
    "high":     ":red_circle:",
    "medium":   ":large_yellow_circle:",
    "low":      ":large_blue_circle:",
}
_STATUS_EMOJI = {
    "done":     ":white_check_mark:",
    "blocked":  ":no_entry:",
    "doing":    ":construction:",
    "in_review": ":eyes:",
    "todo":     ":memo:",
    "abandoned": ":wastebasket:",
}
_KIND_EMOJI = {
    "bug":             ":bug:",
    "blocker_open":    ":no_entry:",
    "blocker_close":   ":white_check_mark:",
    "task_new":        ":new:",
    "task_status":     ":arrows_counterclockwise:",
}


def _build_blocks(title: str, fields: list[tuple[str, str]]) -> list[dict]:
    """Build Slack Block Kit blocks: header + 2-column field grid + timestamp."""
    blocks: list[dict] = [
        {"type": "header",
         "text": {"type": "plain_text", "text": title}},
    ]
    # Slack section.fields renders as 2-column. Cap at 10 (Slack limit).
    field_blocks = []
    for label, value in fields[:10]:
        field_blocks.append({"type": "mrkdwn",
                             "text": f"*{label}*\n{value or '-'}"})
    if field_blocks:
        blocks.append({"type": "section", "fields": field_blocks})
    blocks.append({"type": "context",
                   "elements": [{"type": "mrkdwn", "text": f"_{_now_str()}_"}]})
    return blocks


def _enqueue(payload: dict) -> None:
    """Buffer + debounce — same pattern as feishu_notify._enqueue."""
    global _timer
    with _lock:
        _buffer.append(payload)
        if _timer is None:
            _timer = threading.Timer(_DEBOUNCE_SECONDS, _flush)
            _timer.daemon = True
            _timer.start()


def _flush() -> None:
    global _timer
    with _lock:
        events = list(_buffer)
        _buffer.clear()
        _timer = None
    for payload in events:
        _post_webhook(payload)


# ── Public API — mirror feishu_notify.notify_* ──────────────────────────

def notify_task_created(title: str, project: str, workstream: str,
                         assignee: str, actor: str) -> None:
    emoji = _KIND_EMOJI["task_new"]
    _enqueue({
        "blocks": _build_blocks(f"{emoji}  New Task Created", [
            ("Task", title),
            ("Project", project),
            ("Workstream", workstream),
            ("Assignee", assignee),
            ("Created by", actor),
        ]),
    })


def notify_task_status_changed(title: str, project: str, workstream: str,
                                old_status: str, new_status: str,
                                actor: str) -> None:
    emoji = _STATUS_EMOJI.get(new_status, _KIND_EMOJI["task_status"])
    _enqueue({
        "blocks": _build_blocks(
            f"{emoji}  Task Status: {old_status} → {new_status}", [
                ("Task", title),
                ("Project", project),
                ("Workstream", workstream),
                ("Status", f"`{old_status}` → *{new_status}*"),
                ("Updated by", actor),
            ]),
    })


def notify_blocker_created(description: str, project: str,
                            workstream: str, actor: str) -> None:
    emoji = _KIND_EMOJI["blocker_open"]
    _enqueue({
        "blocks": _build_blocks(f"{emoji}  Blocker Reported", [
            ("Blocker", description),
            ("Project", project),
            ("Workstream", workstream),
            ("Reported by", actor),
        ]),
    })


def notify_blocker_resolved(description: str, project: str,
                             workstream: str, actor: str) -> None:
    emoji = _KIND_EMOJI["blocker_close"]
    _enqueue({
        "blocks": _build_blocks(f"{emoji}  Blocker Resolved", [
            ("Blocker", description),
            ("Project", project),
            ("Workstream", workstream),
            ("Resolved by", actor),
        ]),
    })


def notify_bug_created(title: str, severity: str, reporter: str) -> None:
    emoji = _SEV_EMOJI.get(severity, _KIND_EMOJI["bug"])
    _enqueue({
        "blocks": _build_blocks(f"{emoji}  Bug Reported", [
            ("Bug", title),
            ("Severity", severity),
            ("Reporter", reporter),
        ]),
    })

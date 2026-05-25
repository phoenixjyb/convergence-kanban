"""DingTalk / 钉钉 group-robot webhook notifications.

Posts Markdown messages to a DingTalk custom robot webhook on bug/blocker/
task events. Mirrors the public API of feishu_notify and slack_notify so
the same dispatcher fans all three out.

No-op if DINGTALK_WEBHOOK_URL is not set. Pure stdlib (urllib + hmac).

Setup:
    1. In the target DingTalk group → Group Assistant → Add Robot → Custom.
    2. Set a security option:
       - HMAC-SHA256 signature (recommended) → copy the secret.
       - OR IP whitelist
       - OR a keyword that must appear in every message (least secure;
         requires editing _build_md_text to include the keyword).
    3. Copy the webhook URL.
    4. Paste into .env:
         DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=...
         DINGTALK_WEBHOOK_SECRET=SECxxxxxxxxxxxxxxxxxxxxxx   (only for HMAC)

Format: Markdown messages with title + multi-line body. DingTalk renders
Markdown links, bold, lists, etc.; emoji prefix conveys severity/status.

Docs:
    https://open.dingtalk.com/document/orgapp/custom-robot-access
"""

import base64
import hashlib
import hmac
import json
import os
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

# Project-wide TZ — change in helpers.py for other regions.
TZ = timezone(timedelta(hours=8))

WEBHOOK_URL = os.getenv("DINGTALK_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("DINGTALK_WEBHOOK_SECRET", "")

# Debounce window — same as feishu_notify / slack_notify
_buffer: list[dict] = []
_lock = threading.Lock()
_timer: threading.Timer | None = None
_DEBOUNCE_SECONDS = 5


def _now_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _sign_url() -> str:
    """If a HMAC secret is configured, append timestamp+sign query params to
    the webhook URL. Otherwise return the URL as-is.

    Spec: https://open.dingtalk.com/document/orgapp/customize-robot-security-settings
    """
    if not WEBHOOK_SECRET:
        return WEBHOOK_URL
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{WEBHOOK_SECRET}"
    hmac_code = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
    sep = "&" if "?" in WEBHOOK_URL else "?"
    return f"{WEBHOOK_URL}{sep}timestamp={timestamp}&sign={sign}"


def _post_webhook(payload: dict) -> None:
    """POST a payload to DingTalk. Silently ignores errors."""
    if not WEBHOOK_URL:
        return
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        _sign_url(),
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(req, timeout=10) as r:
            resp = r.read().decode("utf-8", errors="replace")
            # DingTalk returns 200 even on errcode != 0 — parse to log failures
            try:
                j = json.loads(resp)
                if j.get("errcode") not in (0, None):
                    print(f"[dingtalk-notify] errcode={j.get('errcode')}: "
                          f"{j.get('errmsg', '')[:200]}", flush=True)
            except json.JSONDecodeError:
                pass
    except Exception as e:
        print(f"[dingtalk-notify] webhook error: {e}", flush=True)


# Severity / status / event-kind → emoji. Same palette as slack_notify.
_SEV_EMOJI = {
    "critical": "🚨", "high": "🔴", "medium": "🟡", "low": "🔵",
}
_STATUS_EMOJI = {
    "done": "✅", "blocked": "⛔", "doing": "🚧",
    "in_review": "👀", "todo": "📝", "abandoned": "🗑",
}


def _build_md_payload(title: str, lines: list[str]) -> dict:
    """Build a DingTalk markdown message payload."""
    body_md = "\n\n".join(lines) + f"\n\n> {_now_str()}"
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"### {title}\n\n{body_md}",
        },
    }


def _kv(label: str, value: str) -> str:
    return f"**{label}：** {value or '-'}"


def _enqueue(payload: dict) -> None:
    """Buffer + debounce — mirror of feishu_notify / slack_notify."""
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
    _enqueue(_build_md_payload(
        "🆕 New Task Created",
        [
            _kv("Task", title),
            _kv("Project", project),
            _kv("Workstream", workstream),
            _kv("Assignee", assignee),
            _kv("Created by", actor),
        ],
    ))


def notify_task_status_changed(title: str, project: str, workstream: str,
                                old_status: str, new_status: str,
                                actor: str) -> None:
    emoji = _STATUS_EMOJI.get(new_status, "🔄")
    _enqueue(_build_md_payload(
        f"{emoji} Task Status: {old_status} → {new_status}",
        [
            _kv("Task", title),
            _kv("Project", project),
            _kv("Workstream", workstream),
            _kv("Status", f"`{old_status}` → **{new_status}**"),
            _kv("Updated by", actor),
        ],
    ))


def notify_blocker_created(description: str, project: str,
                            workstream: str, actor: str) -> None:
    _enqueue(_build_md_payload(
        "⛔ Blocker Reported",
        [
            _kv("Blocker", description),
            _kv("Project", project),
            _kv("Workstream", workstream),
            _kv("Reported by", actor),
        ],
    ))


def notify_blocker_resolved(description: str, project: str,
                             workstream: str, actor: str) -> None:
    _enqueue(_build_md_payload(
        "✅ Blocker Resolved",
        [
            _kv("Blocker", description),
            _kv("Project", project),
            _kv("Workstream", workstream),
            _kv("Resolved by", actor),
        ],
    ))


def notify_bug_created(title: str, severity: str, reporter: str) -> None:
    emoji = _SEV_EMOJI.get(severity, "🐛")
    _enqueue(_build_md_payload(
        f"{emoji} Bug Reported",
        [
            _kv("Bug", title),
            _kv("Severity", severity),
            _kv("Reporter", reporter),
        ],
    ))

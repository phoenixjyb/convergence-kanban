#!/usr/bin/env python3
"""
ConvergenceKanban — Interactive Feishu Bot.
Subscribes to im.message.receive_v1 via Long Polling (WebSocket).
Routes commands to kanban REST API at http://127.0.0.1:8666/api.

Prerequisites:
1. Enable "Bot" capability on Feishu app in console
2. Set event subscription to Long Polling (WebSocket)
3. Subscribe to im.message.receive_v1
4. Add bot to target Feishu group
5. pip install lark-oapi>=1.3.0

Usage:
    python feishu_bot.py [--profile team]
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

# Profile support
_profile = "default"
for i, arg in enumerate(sys.argv):
    if arg == "--profile" and i + 1 < len(sys.argv):
        _profile = sys.argv[i + 1]
_base = Path(__file__).parent
if _profile != "default":
    load_dotenv(_base / f".env.{_profile}")
load_dotenv(_base / ".env")

try:
    import lark_oapi as lark
    from lark_oapi.api.im.v1 import (
        CreateMessageRequest,
        CreateMessageRequestBody,
        ReplyMessageRequest,
        ReplyMessageRequestBody,
    )
    _HAS_LARK = True
except ImportError:
    lark = None  # type: ignore[assignment]
    _HAS_LARK = False

APP_ID = os.getenv("FEISHU_APP_ID", "")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "")
ENCRYPT_KEY = os.getenv("FEISHU_ENCRYPT_KEY", "")
VERIFICATION_TOKEN = os.getenv("FEISHU_VERIFICATION_TOKEN", "")
KANBAN_API = os.getenv("KANBAN_API_URL", "http://127.0.0.1:8666/api")
KANBAN_WEB_URL = os.getenv("KANBAN_WEB_URL", "http://localhost:8666")
BOT_USER = "feishu-bot"

# ── Kanban API helpers ────────────────────────────────────────────────────

def kanban_get(path: str):
    url = f"{KANBAN_API}{path}"
    req = urllib.request.Request(url, headers={"X-Kanban-User": BOT_USER})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    resp = opener.open(req, timeout=10)
    return json.loads(resp.read())


def kanban_post(path: str, data: dict):
    url = f"{KANBAN_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Kanban-User": BOT_USER},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    resp = opener.open(req, timeout=10)
    return json.loads(resp.read())


def kanban_put(path: str, data: dict):
    url = f"{KANBAN_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method="PUT",
        headers={"Content-Type": "application/json", "X-Kanban-User": BOT_USER},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    resp = opener.open(req, timeout=10)
    return json.loads(resp.read())


# ── Command handlers ─────────────────────────────────────────────────────

def cmd_login(open_id: str) -> str:
    """Generate a one-time login link for the Feishu user."""
    if not open_id or open_id == "unknown":
        return "Cannot identify your Feishu account. Please try again."
    try:
        result = kanban_post("/auth/token", {"open_id": open_id})
        token = result["token"]
        login_url = f"{KANBAN_WEB_URL}?login_token={token}"
        return (
            f"🔑 **Login Link / 登录链接**\n\n"
            f"[Click to login / 点击登录]({login_url})\n\n"
            f"Logging in as: **{result['user_name']}**\n"
            f"⏰ Link expires in 5 minutes / 链接5分钟内有效"
        )
    except Exception as e:
        err = str(e)
        if "404" in err:
            return (
                "Your Feishu account is not linked to any kanban user.\n"
                "Ask an admin to add your Feishu account, or create a new user on the kanban board."
            )
        return f"Login failed: {e}"


def cmd_help() -> str:
    return """**Kanban Bot Commands / 看板机器人命令**

**Query / 查询:**
| Command | Description |
|---------|-------------|
| login / 登录 | Get a login link for the kanban board |
| help / 帮助 | Show this help |
| my / 我的 | List your tasks (numbered) |
| blockers / 阻塞项 | List active blockers |
| progress / 进度 | Per-project stats |
| alerts / 提醒 | Show overdue & stale tasks |
| digest / 摘要 | On-demand project summary |
| bugs / 缺陷 | List open bugs by severity |
| workload / 工作量 | Per-person task distribution |
| conflicts / 冲突 | Unresolved sync conflicts |
| search <keyword> / 搜索 | Find tasks by title |

**Action / 操作:**
| Command | Description |
|---------|-------------|
| done <ref> / 完成 | Mark task done |
| update <ref> <status> / 更新 | Change task status |
| assign <ref> <user> / 分配 | Assign task to user |
| new <title> / 新建 | Create a task |
| bug <title> / 报bug | Report a new bug |
| time <ref> <min> [desc] / 计时 | Log time |
| comment <ref> <text> / 评论 | Post a comment |
| resolve <blocker_id> / 解决 | Resolve a blocker |

**💡 Smart references (<ref>):**
• **Number** — `done 1` (use `my` first to get numbered list)
• **Keyword** — `done fix login` (matches task title)
• **ID** — `done a1b2c3d4` (exact task ID)

Status: todo, doing, in_review, done, blocked
Severity: critical, high, medium, low"""


def cmd_my_tasks(user_name: str) -> str:
    dashboard = kanban_get("/dashboard")
    tasks = []
    shortcut_items = []
    for p in dashboard:
        for ws in p.get("workstreams", []):
            for t in ws.get("tasks", []):
                if t.get("assignee", "").lower() == user_name.lower():
                    status = t["status"]
                    title = t.get("title_en") or t.get("title_zh", "")
                    tasks.append({"id": t["id"], "title": title, "status": status,
                                  "ctx": f"{p['name_en']}/{ws['title_en']}"})
    if not tasks:
        return f"No tasks assigned to **{user_name}**."
    # Cache numbered shortcuts
    shortcut_items = [{"id": t["id"], "title": t["title"], "kind": "task"} for t in tasks[:20]]
    _set_shortcuts(user_name, shortcut_items)
    lines = [f"**Tasks for {user_name}** ({len(tasks)}):\n"]
    for i, t in enumerate(tasks[:20], 1):
        lines.append(f"**[{i}]** [{t['status']}] {t['title']} ({t['ctx']})")
    lines.append(f"\n💡 Use number shortcuts: `done 1`, `update 2 doing`, `comment 3 text`")
    return "\n".join(lines)


def cmd_blockers() -> str:
    dashboard = kanban_get("/dashboard")
    blockers = []
    for p in dashboard:
        for ws in p.get("workstreams", []):
            for b in ws.get("blockers", []):
                desc = b.get("description_en") or b.get("description_zh", "")
                blockers.append(f"- {desc} ({p['name_en']}/{ws['title_en']})")
    if not blockers:
        return "No active blockers!"
    return f"**Active Blockers** ({len(blockers)}):\n" + "\n".join(blockers[:20])


def cmd_progress() -> str:
    dashboard = kanban_get("/dashboard")
    lines = []
    for p in dashboard:
        total = sum(ws.get("task_stats", {}).get("total", 0) for ws in p.get("workstreams", []))
        done = sum(ws.get("task_stats", {}).get("done", 0) for ws in p.get("workstreams", []))
        pct = round(done / total * 100) if total > 0 else 0
        bar = "=" * (pct // 10) + "-" * (10 - pct // 10)
        lines.append(f"**{p['name_en']}**: {done}/{total} ({pct}%) [{bar}]")
    if not lines:
        return "No projects found."
    return "**Project Progress:**\n" + "\n".join(lines)


def cmd_new_task(title: str, user_name: str) -> str:
    # Find the first workstream to place the task
    dashboard = kanban_get("/dashboard")
    if not dashboard:
        return "No projects found. Create a project first."
    ws_id = None
    for p in dashboard:
        wss = p.get("workstreams", [])
        if wss:
            ws_id = wss[0]["id"]
            break
    if not ws_id:
        return "No workstreams found. Create a workstream first."
    result = kanban_post("/tasks", {
        "workstream_id": ws_id,
        "title_en": title,
        "assignee": user_name,
        "status": "todo",
    })
    return f"Task created (id: {result.get('id', '?')}): **{title}**\nAssigned to: {user_name}"


def cmd_update_task(task_ref: str, new_status: str, sender_name: str) -> str:
    valid = ("todo", "doing", "in_review", "done", "blocked", "abandoned")
    if new_status not in valid:
        return f"Invalid status: {new_status}. Use one of: {', '.join(valid)}"
    task_id, err = _resolve_task_ref(task_ref, sender_name)
    if err:
        return err
    try:
        kanban_put(f"/tasks/{task_id}", {"status": new_status})
    except Exception as e:
        if "403" in str(e):
            return f"Bot cannot mark tasks as **{new_status}** (governance policy). Ask a human to approve."
        return f"Failed to update task: {e}"
    return f"Task `{task_id[:8]}` updated to **{new_status}**."


def cmd_alerts(sender_name: str) -> str:
    """Show overdue and stale tasks for the requesting user."""
    try:
        data = kanban_get("/alerts")
    except Exception as e:
        return f"Failed to fetch alerts: {e}"

    overdue = data.get("overdue", [])
    stale = data.get("stale", [])
    aging = data.get("aging_blockers", [])

    # Filter to sender if possible
    my_overdue = [t for t in overdue if t.get("assignee") == sender_name]
    my_stale = [t for t in stale if t.get("assignee") == sender_name]

    lines = [f"**Alerts for {sender_name}**\n"]

    if my_overdue:
        lines.append(f"🔴 **Overdue ({len(my_overdue)})**")
        for t in my_overdue[:5]:
            lines.append(f"  • {t['title_en']} — {t['days_overdue']}d overdue")
    if my_stale:
        lines.append(f"🟡 **Stale ({len(my_stale)})**")
        for t in my_stale[:5]:
            lines.append(f"  • {t['title_en']} — no update for {t['stale_days']}d")
    if aging:
        lines.append(f"⚠️ **Aging Blockers ({len(aging)})**")
        for b in aging[:5]:
            lines.append(f"  • {b['description_en']} — {b['age_hours']}h")

    if len(lines) == 1:
        lines.append("All clear — no alerts for you!")
    return "\n".join(lines)


def cmd_digest() -> str:
    """On-demand project summary."""
    try:
        dashboard = kanban_get("/dashboard")
    except Exception as e:
        return f"Failed to fetch dashboard: {e}"

    lines = ["**Project Summary / 项目概览**\n"]
    for proj in dashboard:
        stats = proj.get("stats", {})
        total = stats.get("total_tasks", 0)
        done = stats.get("done_tasks", 0)
        pct = round(done / total * 100) if total > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        lines.append(f"**{proj['name_en']}** {bar} {pct}% ({done}/{total})")
    return "\n".join(lines)


def cmd_assign_task(task_ref: str, assignee: str, sender_name: str) -> str:
    """Assign a task to a user."""
    task_id, err = _resolve_task_ref(task_ref, sender_name)
    if err:
        return err
    try:
        kanban_put(f"/tasks/{task_id}", {"assignee": assignee})
    except Exception as e:
        return f"Failed to assign: {e}"
    return f"Task `{task_id[:8]}` assigned to **{assignee}**."


def cmd_bugs() -> str:
    """List open bugs grouped by severity."""
    try:
        all_bugs = kanban_get("/bugs")
    except Exception as e:
        return f"Failed to fetch bugs: {e}"
    bugs = [b for b in all_bugs if b.get("status") in ("open", "investigating", "fixing", "fix_complete", "to_verify")]
    if not bugs:
        return "No open bugs! 🎉"
    by_sev = {"critical": [], "high": [], "medium": [], "low": []}
    for b in bugs:
        sev = b.get("severity", "medium")
        by_sev.setdefault(sev, []).append(b)
    icons = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "🟢"}
    lines = [f"**Open Bugs** ({len(bugs)}):\n"]
    for sev in ("critical", "high", "medium", "low"):
        items = by_sev.get(sev, [])
        if items:
            lines.append(f"{icons.get(sev, '●')} **{sev.upper()}** ({len(items)})")
            for b in items[:5]:
                status = b.get("status", "open")
                assignee = f" @{b['assignee']}" if b.get("assignee") else ""
                age = b.get("created_at", "")[:10]
                lines.append(f"  • [{status}] {b.get('title', '?')}{assignee} ({age})")
            if len(items) > 5:
                lines.append(f"  ... and {len(items) - 5} more")
    lines.append(f"\n💡 Report: `bug high Login crash` | View: web UI /bugs")
    return "\n".join(lines)


def cmd_report_bug(title: str, sender_name: str, severity: str = "medium") -> str:
    """Report a new bug from chat."""
    if severity not in ("critical", "high", "medium", "low"):
        severity = "medium"
    # Find the first project to associate
    try:
        dashboard = kanban_get("/dashboard")
    except Exception as e:
        return f"Failed to fetch dashboard: {e}"
    if not dashboard:
        return "No projects found."
    project_id = dashboard[0]["id"]
    try:
        result = kanban_post("/bugs", {
            "title": title,
            "severity": severity,
            "reporter": sender_name,
            "project_id": project_id,
        })
    except Exception as e:
        return f"Failed to create bug: {e}"
    return f"Bug reported (id: `{result.get('id', '?')}`): **{title}**\nSeverity: {severity} | Reporter: {sender_name}"


def cmd_search(keyword: str) -> str:
    """Search tasks by title keyword."""
    dashboard = kanban_get("/dashboard")
    kw = keyword.lower()
    results = []
    for p in dashboard:
        for ws in p.get("workstreams", []):
            for t in ws.get("tasks", []):
                title_en = (t.get("title_en") or "").lower()
                title_zh = (t.get("title_zh") or "").lower()
                if kw in title_en or kw in title_zh:
                    title = t.get("title_en") or t.get("title_zh", "")
                    results.append(
                        f"- [{t['status']}] {title} (`{t['id']}`)\n"
                        f"  {p['name_en']}/{ws['title_en']}"
                        + (f" @{t['assignee']}" if t.get("assignee") else "")
                    )
    if not results:
        return f"No tasks found matching **{keyword}**."
    return f"**Search: {keyword}** ({len(results)} results):\n" + "\n".join(results[:15])


def cmd_log_time(task_ref: str, minutes: str, description: str, sender_name: str) -> str:
    """Log time on a task."""
    try:
        mins = int(minutes)
    except ValueError:
        return f"Invalid minutes: `{minutes}`. Must be a number."
    task_id, err = _resolve_task_ref(task_ref, sender_name)
    if err:
        return err
    try:
        kanban_post(f"/tasks/{task_id}/time", {
            "minutes": mins,
            "description": description or f"Logged via Feishu bot by {sender_name}",
            "user_name": sender_name,
        })
    except Exception as e:
        return f"Failed to log time: {e}"
    return f"Logged **{mins}min** on task `{task_id[:8]}`."


def cmd_comment(task_ref: str, body: str, sender_name: str) -> str:
    """Post a comment on a task."""
    if not body:
        return "Please provide comment text."
    task_id, err = _resolve_task_ref(task_ref, sender_name)
    if err:
        return err
    try:
        kanban_post(f"/comments/task/{task_id}", {
            "body": f"[{sender_name}] {body}",
        })
    except Exception as e:
        return f"Failed to post comment: {e}"
    return f"Comment posted on task `{task_id[:8]}`."


def cmd_workload() -> str:
    """Per-person task distribution."""
    try:
        data = kanban_get("/analytics/workload")
    except Exception as e:
        return f"Failed to fetch workload: {e}"
    if not data:
        return "No workload data available."
    lines = ["**Workload Distribution / 工作量分布**\n"]
    for person in sorted(data, key=lambda x: x.get("total", 0), reverse=True):
        name = person.get("assignee", "unassigned")
        total = person.get("total", 0)
        doing = person.get("doing", 0)
        todo = person.get("todo", 0)
        review = person.get("in_review", 0)
        done = person.get("done", 0)
        lines.append(f"**{name}** ({total} total): "
                      f"📋{todo} 🔨{doing} 👀{review} ✅{done}")
    return "\n".join(lines)


def cmd_resolve_blocker(blocker_id: str) -> str:
    """Resolve a blocker."""
    try:
        kanban_put(f"/blockers/{blocker_id}/resolve", {})
    except Exception as e:
        return f"Failed to resolve blocker: {e}"
    return f"Blocker `{blocker_id}` resolved."


def cmd_conflicts() -> str:
    """Show unresolved sync conflict count."""
    try:
        data = kanban_get("/sync-conflicts/count")
    except Exception as e:
        return f"Failed to fetch conflicts: {e}"
    count = data.get("unresolved", 0)
    if count == 0:
        return "No unresolved sync conflicts."
    return (f"**{count} unresolved sync conflict(s)**\n"
            f"Open the web UI to review: Board → ⚡ button")


# ── Numbered shortcut cache ──────────────────────────────────────────────
# Per-user numbered list from last `my` / `my tasks` command.
# Key: username (lowercase), Value: {"tasks": [{id, title}, ...], "ts": float}
import time as _time
_shortcut_cache: dict[str, dict] = {}
_SHORTCUT_TTL = 600  # 10 minutes


def _set_shortcuts(user: str, items: list[dict]):
    """Cache a numbered list for a user. Each item: {id, title, kind}."""
    _shortcut_cache[user.lower()] = {"items": items, "ts": _time.time()}


def _get_shortcut(user: str, num: int) -> dict | None:
    """Look up shortcut #num for user. Returns {id, title, kind} or None."""
    entry = _shortcut_cache.get(user.lower())
    if not entry:
        return None
    if _time.time() - entry["ts"] > _SHORTCUT_TTL:
        del _shortcut_cache[user.lower()]
        return None
    items = entry["items"]
    if 1 <= num <= len(items):
        return items[num - 1]
    return None


def _resolve_task_ref(ref: str, sender_name: str) -> tuple[str | None, str | None]:
    """Resolve a task reference — ID, shortcut number, or keyword search.

    Returns (task_id, error_message). One will be None.
    """
    ref = ref.strip()

    # 1) Numbered shortcut: short plain integer.
    # Cap at 3 digits — shortcuts are 1-20, never more than ~100. A 12-char
    # task ID that happens to roll all digits would otherwise collide here.
    if ref.isdigit() and len(ref) <= 3:
        num = int(ref)
        item = _get_shortcut(sender_name, num)
        if item:
            return item["id"], None
        return None, f"No shortcut #{num}. Type **my** first to get a numbered list."

    # 2) Looks like a UUID/hex ID (8+ hex chars, including the all-digit case
    # that fell through #1 above).
    if re.match(r'^[0-9a-f-]{8,}$', ref, re.IGNORECASE):
        return ref, None

    # 3) Keyword search — find among sender's tasks
    dashboard = kanban_get("/dashboard")
    kw = ref.lower()
    matches = []
    for p in dashboard:
        for ws in p.get("workstreams", []):
            for t in ws.get("tasks", []):
                title_en = (t.get("title_en") or "").lower()
                title_zh = (t.get("title_zh") or "").lower()
                if kw in title_en or kw in title_zh:
                    title = t.get("title_en") or t.get("title_zh", "")
                    matches.append({"id": t["id"], "title": title,
                                    "assignee": t.get("assignee", ""),
                                    "status": t["status"]})
    if len(matches) == 1:
        return matches[0]["id"], None
    if len(matches) == 0:
        return None, f"No tasks found matching **{ref}**."
    # Multiple matches — show options
    lines = [f"Multiple tasks match **{ref}** — be more specific or use the ID:\n"]
    for m in matches[:8]:
        lines.append(f"  • [{m['status']}] {m['title']} (`{m['id'][:8]}`)"
                     + (f" @{m['assignee']}" if m['assignee'] else ""))
    return None, "\n".join(lines)


# ── Interactive Cards ────────────────────────────────────────────────────

_STATUS_EMOJI = {
    "todo": "📋", "doing": "🔨", "in_review": "👀",
    "done": "✅", "blocked": "🚫",
}


def _build_my_tasks_card(sender_name: str) -> dict | None:
    """Build a Feishu interactive card with action buttons for my tasks."""
    dashboard = kanban_get("/dashboard")
    tasks = []
    for p in dashboard:
        for ws in p.get("workstreams", []):
            for t in ws.get("tasks", []):
                if t.get("assignee", "").lower() == sender_name.lower():
                    title = t.get("title_en") or t.get("title_zh", "")
                    tasks.append({
                        "id": t["id"], "title": title, "status": t["status"],
                        "ctx": f"{p['name_en']}/{ws['title_en']}",
                    })
    if not tasks:
        return None  # fall back to text reply

    # Cache numbered shortcuts
    _set_shortcuts(sender_name, [
        {"id": t["id"], "title": t["title"], "kind": "task"} for t in tasks[:20]
    ])

    elements: list[dict] = []
    for i, t in enumerate(tasks[:10], 1):
        emoji = _STATUS_EMOJI.get(t["status"], "●")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": (
                    f"{emoji} **[{i}]** {t['title']}\n"
                    f"_{t['ctx']}_ · `{t['status']}`"
                ),
            },
        })
        if i < min(len(tasks), 10):
            elements.append({"tag": "hr"})

    if len(tasks) > 10:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"_...and {len(tasks) - 10} more_"},
        })

    elements.append({
        "tag": "note",
        "elements": [
            {"tag": "plain_text",
             "content": "💡 Reply: done 1 · update 2 doing · comment 3 text"},
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📋 My Tasks ({len(tasks)})"},
            "template": "green",
        },
        "elements": elements,
    }


def _handle_card_action(ctx) -> dict:
    """Handle button clicks from interactive cards."""
    try:
        action = ctx.action
        value = action.value if hasattr(action, "value") else {}
        if isinstance(value, str):
            value = json.loads(value)

        act = value.get("act")
        task_id = value.get("tid")

        if act == "status" and task_id:
            new_status = value.get("st", "doing")
            try:
                kanban_put(f"/tasks/{task_id}", {"status": new_status})
                label = {"doing": "Started", "in_review": "Submitted for review",
                         "blocked": "Marked blocked", "todo": "Moved to todo"}
                return {
                    "toast": {"type": "success",
                              "content": label.get(new_status, f"Updated to {new_status}")},
                }
            except Exception as e:
                if "403" in str(e):
                    return {
                        "toast": {"type": "warning",
                                  "content": "Governance: ask a human to approve this action"},
                    }
                return {"toast": {"type": "error", "content": f"Failed: {e}"}}
    except Exception as e:
        print(f"[bot] Card action error: {e}")
    return {"toast": {"type": "info", "content": "Action processed"}}


# ── Sender identity resolution ───────────────────────────────────────────

# Cache: feishu open_id -> kanban username
_openid_cache: dict[str, str] = {}


def _resolve_sender(client, open_id: str) -> str:
    """Resolve Feishu open_id to kanban username.

    Priority:
    1. Cache hit
    2. DB lookup by feishu_open_id
    3. Feishu API display name
    Caches the result for the session.
    """
    if open_id in _openid_cache:
        return _openid_cache[open_id]

    # Try DB lookup by feishu_open_id
    try:
        users = kanban_get("/users")
        for u in users:
            if u.get("feishu_open_id") == open_id:
                _openid_cache[open_id] = u["name"]
                return u["name"]
    except Exception:
        pass

    # Fallback: Feishu API display name
    name = _get_sender_name(client, open_id)
    _openid_cache[open_id] = name
    return name


# ── Message routing ──────────────────────────────────────────────────────

def _get_sender_name(client, user_id: str) -> str:
    """Try to get display name from Feishu user ID."""
    try:
        req = lark.RawRequest()
        req.uri = f"/open-apis/contact/v3/users/{user_id}"
        req.method = "GET"
        req.data_type = lark.JSON
        resp = client.request(req)
        if resp.success():
            data = json.loads(resp.raw.content)
            return data.get("data", {}).get("user", {}).get("name", user_id)
    except Exception:
        pass
    return user_id


def route_command(text: str, sender_name: str, open_id: str = "") -> str:
    """Parse text and route to the appropriate command handler."""
    text = text.strip()
    # Strip @bot mention prefix if present
    text = re.sub(r'^@\S+\s*', '', text).strip()
    lower = text.lower()

    if lower in ("login", "登录"):
        return cmd_login(open_id)
    elif lower in ("help", "帮助"):
        return cmd_help()
    elif lower in ("my tasks", "我的任务", "my", "我的"):
        return cmd_my_tasks(sender_name)
    elif lower in ("blockers", "阻塞项"):
        return cmd_blockers()
    elif lower in ("progress", "进度"):
        return cmd_progress()
    elif lower in ("alerts", "提醒"):
        return cmd_alerts(sender_name)
    elif lower in ("digest", "摘要"):
        return cmd_digest()
    elif lower in ("bugs", "缺陷"):
        return cmd_bugs()
    elif lower in ("workload", "工作量"):
        return cmd_workload()
    elif lower in ("conflicts", "冲突"):
        return cmd_conflicts()
    elif lower.startswith("done ") or lower.startswith("完成 "):
        ref = re.sub(r'^(done|完成)\s+', '', text, flags=re.IGNORECASE).strip()
        if not ref:
            return "Usage: `done <#|id|keyword>`\nExample: `done 1` or `done fix login`"
        return cmd_update_task(ref, "done", sender_name)
    elif lower.startswith("search ") or lower.startswith("搜索 "):
        keyword = re.sub(r'^(search|搜索)\s+', '', text, flags=re.IGNORECASE).strip()
        if not keyword:
            return "Usage: `search <keyword>`\nExample: `search login`"
        return cmd_search(keyword)
    elif lower.startswith("assign ") or lower.startswith("分配 "):
        parts = re.sub(r'^(assign|分配)\s+', '', text, flags=re.IGNORECASE).strip().split(None, 1)
        if len(parts) < 2:
            return "Usage: `assign <#|id|keyword> <user>`\nExample: `assign 1 alice`"
        return cmd_assign_task(parts[0], parts[1], sender_name)
    elif lower.startswith("new ") or lower.startswith("新建 "):
        title = re.sub(r'^(new|新建)\s+', '', text, flags=re.IGNORECASE).strip()
        if not title:
            return "Please provide a task title. Example: `new Fix button alignment`"
        return cmd_new_task(title, sender_name)
    elif lower.startswith("update ") or lower.startswith("更新 "):
        parts = re.sub(r'^(update|更新)\s+', '', text, flags=re.IGNORECASE).strip().split(None, 1)
        if len(parts) < 2:
            return "Usage: `update <#|id|keyword> <status>`\nExample: `update 1 doing`"
        return cmd_update_task(parts[0], parts[1].lower(), sender_name)
    elif lower.startswith("bug ") or lower.startswith("报bug "):
        # Parse: bug [severity] <title>
        rest = re.sub(r'^(bug|报bug)\s+', '', text, flags=re.IGNORECASE).strip()
        severity = "medium"
        for sev in ("critical", "high", "medium", "low"):
            if rest.lower().startswith(sev + " "):
                severity = sev
                rest = rest[len(sev):].strip()
                break
        if not rest:
            return "Usage: `bug [severity] <title>`\nExample: `bug high Login page crashes`"
        return cmd_report_bug(rest, sender_name, severity)
    elif lower.startswith("time ") or lower.startswith("计时 "):
        parts = re.sub(r'^(time|计时)\s+', '', text, flags=re.IGNORECASE).strip().split(None, 2)
        if len(parts) < 2:
            return "Usage: `time <#|id|keyword> <minutes> [desc]`\nExample: `time 1 30 Fixed API`"
        desc = parts[2] if len(parts) > 2 else ""
        return cmd_log_time(parts[0], parts[1], desc, sender_name)
    elif lower.startswith("comment ") or lower.startswith("评论 "):
        parts = re.sub(r'^(comment|评论)\s+', '', text, flags=re.IGNORECASE).strip().split(None, 1)
        if len(parts) < 2:
            return "Usage: `comment <#|id|keyword> <text>`\nExample: `comment 1 Fixed the issue`"
        return cmd_comment(parts[0], parts[1], sender_name)
    elif lower.startswith("resolve ") or lower.startswith("解决 "):
        bid = re.sub(r'^(resolve|解决)\s+', '', text, flags=re.IGNORECASE).strip().split()[0]
        if not bid:
            return "Usage: `resolve <blocker_id>`\nExample: `resolve b1c2d3e4`"
        return cmd_resolve_blocker(bid)
    else:
        # Try to suggest close matches
        suggestions = []
        for cmd in ("login", "my", "help", "bugs", "blockers", "progress", "search", "workload",
                    "alerts", "digest", "conflicts", "done", "update", "assign", "new",
                    "bug", "time", "comment", "resolve"):
            if lower.startswith(cmd[:3]) or cmd.startswith(lower[:3]):
                suggestions.append(cmd)
        hint = f"\nDid you mean: {', '.join(f'`{s}`' for s in suggestions[:3])}?" if suggestions else ""
        return f"Unknown command: **{text}**\nType **help** for available commands.{hint}"


# ── Event handler ────────────────────────────────────────────────────────

def handle_message(client, event_data):
    """Handle im.message.receive_v1 event."""
    # event_data is a typed P2ImMessageReceiveV1Data object
    msg = event_data.message
    if not msg:
        print("[bot] No message in event")
        return
    msg_id = msg.message_id or ""
    msg_type = msg.message_type or ""
    print(f"[bot] Event received: msg_id={msg_id}, type={msg_type}")

    # Only handle text messages
    if msg_type != "text":
        print(f"[bot] Skipping non-text message type: {msg_type}")
        return

    try:
        content = json.loads(msg.content or "{}")
        text = content.get("text", "")
    except (json.JSONDecodeError, TypeError):
        return

    if not text.strip():
        return

    # Get sender info — resolve Feishu open_id to kanban username
    sender = event_data.sender
    user_id = sender.sender_id.open_id if sender and sender.sender_id else "unknown"
    sender_name = _resolve_sender(client, user_id)

    # Route command — try interactive card first, fall back to text
    card_json = None
    cmd_clean = re.sub(r'^@\S+\s*', '', text.strip()).strip().lower()
    if cmd_clean in ("login", "登录"):
        try:
            result = kanban_post("/auth/token", {"open_id": user_id})
            login_url = f"{KANBAN_WEB_URL}?login_token={result['token']}"
            card_json = {
                "header": {"title": {"tag": "plain_text", "content": "Kanban Login / 看板登录"}, "template": "green"},
                "elements": [
                    {"tag": "div", "text": {"tag": "lark_md", "content": f"Logging in as: **{result['user_name']}**"}},
                    {"tag": "action", "actions": [
                        {"tag": "button", "text": {"tag": "plain_text", "content": "Open Kanban / 打开看板"},
                         "type": "primary", "url": login_url}
                    ]},
                    {"tag": "note", "elements": [{"tag": "plain_text", "content": "Link expires in 5 minutes / 链接5分钟内有效"}]},
                ],
            }
        except Exception as e:
            err = str(e)
            if "404" in err:
                card_json = {"elements": [{"tag": "div", "text": {"tag": "lark_md",
                    "content": "Your Feishu account is not linked to any kanban user.\nAsk an admin to add your Feishu account."}}]}
            else:
                print(f"[bot] Login card failed: {e}")

    elif cmd_clean in ("my tasks", "我的任务", "my", "我的"):
        try:
            card_json = _build_my_tasks_card(sender_name)
        except Exception as e:
            print(f"[bot] Card build failed, falling back to text: {e}")

    if card_json is None:
        try:
            reply_text = route_command(text, sender_name, open_id=user_id)
        except Exception as e:
            reply_text = f"Error: {e}"
        card_json = {
            "elements": [{
                "tag": "div",
                "text": {"tag": "lark_md", "content": reply_text},
            }]
        }

    # Reply
    try:
        reply_body = ReplyMessageRequestBody()
        reply_body.msg_type = "interactive"
        reply_body.content = json.dumps(card_json)
        req = ReplyMessageRequest.builder().message_id(msg_id).request_body(reply_body).build()
        client.im.v1.message.reply(req)
    except Exception as e:
        print(f"Failed to reply to {msg_id}: {e}")


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    if not _HAS_LARK:
        print("Error: lark-oapi not installed. Run: pip install lark-oapi>=1.3.0")
        sys.exit(1)
    if not APP_ID or not APP_SECRET:
        print("Error: FEISHU_APP_ID and FEISHU_APP_SECRET must be set")
        sys.exit(1)

    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

    handler = (
        lark.EventDispatcherHandler.builder(ENCRYPT_KEY, VERIFICATION_TOKEN)
        .register_p2_im_message_receive_v1(
            lambda event: handle_message(client, event.event)
        )
        .build()
    )

    log_level = lark.LogLevel.DEBUG if os.getenv("BOT_DEBUG") else lark.LogLevel.INFO
    cli = lark.ws.Client(APP_ID, APP_SECRET, event_handler=handler, log_level=log_level)
    print(f"Starting Feishu bot (profile: {_profile})...")
    cli.start()


if __name__ == "__main__":
    main()

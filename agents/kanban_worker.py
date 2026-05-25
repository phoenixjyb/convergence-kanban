#!/usr/bin/env python3
"""
Kanban Worker CLI — lets coding agents interact with the ConvergenceKanban.

Usage:
    python3 -m agents.kanban_worker <command> [options]

Commands:
    board-summary                          Show compact board state
    my-tasks                               List tasks assigned to this agent
    pick-task [--project P] [--priority P] Claim highest-priority unassigned task
    start-task <tid>                       Set task to doing
    update-task <tid> <message>            Post progress comment
    complete-task <tid> [--minutes M] [--follow-up "title"]  Submit for review
    report-blocker <wid> <description>     Create blocker on workstream
    report-bug <title> [--severity S] [--task-id T]

Options:
    --dry-run    Show what would happen without making changes
    --json       Output as JSON instead of human-readable text

Env:
    KANBAN_AGENT_NAME  Agent identity (REQUIRED: use {firstname}-{tool}, e.g. alice-claude)
    KANBAN_API_URL     API base URL (default: http://127.0.0.1:8666/api)
"""

import json
import sys
from datetime import datetime, timedelta, timezone

# Project-wide timezone: Asia/Shanghai (UTC+8)
TZ = timezone(timedelta(hours=8))

from agents.base import kanban_get, kanban_post, kanban_put, KANBAN_API

AGENT_NAME = __import__("os").environ.get("KANBAN_AGENT_NAME", "claude-code")
DRY_RUN = "--dry-run" in sys.argv
JSON_OUT = "--json" in sys.argv

PRIO_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "": 4}


def _today():
    return datetime.now(TZ).strftime("%Y-%m-%d")


def _out(data):
    if JSON_OUT:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif isinstance(data, str):
        print(data)
    elif isinstance(data, list):
        for item in data:
            print(item)
    elif isinstance(data, dict):
        for k, v in data.items():
            print(f"  {k}: {v}")


def _ensure_user():
    """Auto-register agent as a kanban user."""
    try:
        kanban_post("/users", {"name": AGENT_NAME, "display_name": f"[Bot] {AGENT_NAME}", "role": "bot"},
                    agent_name=AGENT_NAME)
    except Exception:
        pass  # already exists


def _comment(entity_type, entity_id, body):
    """Post a comment with agent prefix."""
    kanban_post(f"/comments/{entity_type}/{entity_id}",
                {"body": f"[{AGENT_NAME}] {body}"}, agent_name=AGENT_NAME)


# ── Commands ──────────────────────────────────────────────────────────────

def cmd_board_summary():
    """Compact board state: projects → workstreams → task counts."""
    dashboard = kanban_get("/dashboard", AGENT_NAME)
    lines = []
    total_tasks = 0
    total_done = 0
    for p in dashboard:
        stats = p.get("stats", {})
        t = stats.get("total", 0)
        d = stats.get("done", 0)
        total_tasks += t
        total_done += d
        pct = f"{d}/{t}" if t else "0/0"
        lines.append(f"\n📁 {p['name_en']} ({pct} done)")
        for ws in p.get("workstreams", []):
            ts = ws.get("task_stats", {})
            wt = ts.get("total", 0)
            wd = ts.get("done", 0)
            blockers = len([b for b in ws.get("blockers", []) if not b.get("resolved")])
            status_icon = "🔴" if blockers else ("✅" if wd == wt and wt > 0 else "🔵")
            lines.append(f"  {status_icon} {ws['title_en']}  [{ws.get('priority','?')}]  "
                         f"{wd}/{wt} tasks  {f'{blockers} blockers' if blockers else ''}")
    lines.insert(0, f"Board: {total_done}/{total_tasks} tasks done across {len(dashboard)} projects")
    if JSON_OUT:
        _out({"projects": len(dashboard), "total_tasks": total_tasks, "total_done": total_done,
              "details": [{"name": p["name_en"], "stats": p.get("stats", {})} for p in dashboard]})
    else:
        _out(lines)


def cmd_my_tasks():
    """List tasks assigned to this agent."""
    dashboard = kanban_get("/dashboard", AGENT_NAME)
    by_status = {"doing": [], "todo": [], "in_review": [], "blocked": [], "done": []}
    for p in dashboard:
        for ws in p.get("workstreams", []):
            for t in ws.get("tasks", []):
                if t.get("assignee", "").lower() == AGENT_NAME.lower():
                    t["_project"] = p["name_en"]
                    t["_workstream"] = ws["title_en"]
                    t["_ws_id"] = ws["id"]
                    bucket = t.get("status", "todo")
                    by_status.setdefault(bucket, []).append(t)
    if JSON_OUT:
        _out(by_status)
        return

    found = False
    for status in ["doing", "todo", "in_review", "blocked", "done"]:
        tasks = by_status.get(status, [])
        if not tasks:
            continue
        found = True
        print(f"\n{'─'*40}")
        print(f"  {status.upper()} ({len(tasks)})")
        print(f"{'─'*40}")
        for t in tasks:
            print(f"  [{t['id']}] {t.get('title_en','?')}")
            print(f"         {t['_project']} / {t['_workstream']}")
            if t.get("due_date"):
                print(f"         due: {t['due_date']}")
    if not found:
        print(f"No tasks assigned to {AGENT_NAME}.")


def cmd_pick_task():
    """Find and claim highest-priority unassigned todo task."""
    # Parse options
    project_filter = None
    priority_filter = None
    for i, arg in enumerate(sys.argv):
        if arg == "--project" and i + 1 < len(sys.argv):
            project_filter = sys.argv[i + 1].lower()
        if arg == "--priority" and i + 1 < len(sys.argv):
            priority_filter = set(sys.argv[i + 1].lower().split(","))

    dashboard = kanban_get("/dashboard", AGENT_NAME)
    candidates = []
    for p in dashboard:
        if project_filter and project_filter not in p["name_en"].lower():
            continue
        for ws in p.get("workstreams", []):
            ws_prio = ws.get("priority", "medium")
            if priority_filter and ws_prio not in priority_filter:
                continue
            for t in ws.get("tasks", []):
                if t.get("status") == "todo" and not t.get("assignee"):
                    t["_ws_priority"] = ws_prio
                    t["_project"] = p["name_en"]
                    t["_workstream"] = ws["title_en"]
                    t["_ws_id"] = ws["id"]
                    candidates.append(t)

    # Sort: ws priority (critical first), then sort_order, then oldest first
    candidates.sort(key=lambda t: (
        PRIO_ORDER.get(t["_ws_priority"], 3),
        t.get("sort_order", 0),
        t.get("created_at", ""),
    ))

    if not candidates:
        _out("No available tasks to pick up.")
        return

    pick = candidates[0]
    print(f"Best candidate: [{pick['id']}] {pick.get('title_en','?')}")
    print(f"  Project: {pick['_project']} / {pick['_workstream']} [{pick['_ws_priority']}]")

    if DRY_RUN:
        print("  (dry-run — no changes made)")
        return

    # Claim it
    kanban_put(f"/tasks/{pick['id']}", {
        "assignee": AGENT_NAME,
        "status": "doing",
        "start_date": _today(),
    }, agent_name=AGENT_NAME)
    _comment("task", pick["id"], f"Claimed task. Starting implementation.")

    # Verify we got it (race protection)
    tasks = kanban_get(f"/tasks?assignee={AGENT_NAME}&status=doing", AGENT_NAME)
    claimed = any(t["id"] == pick["id"] for t in tasks)
    if claimed:
        print(f"  ✅ Claimed successfully.")
    else:
        print(f"  ⚠ Claim may have been overridden by another agent.")


def cmd_start_task():
    """Set a task to doing status."""
    if len(sys.argv) < 3:
        print("Usage: kanban_worker.py start-task <task_id>")
        return
    tid = sys.argv[2]
    if DRY_RUN:
        print(f"Would start task {tid}")
        return
    kanban_put(f"/tasks/{tid}", {
        "status": "doing",
        "start_date": _today(),
    }, agent_name=AGENT_NAME)
    _comment("task", tid, "Started working on this task.")
    print(f"✅ Task {tid} set to doing.")


def cmd_update_task():
    """Post a progress comment on a task."""
    if len(sys.argv) < 4:
        print("Usage: kanban_worker.py update-task <task_id> <message>")
        return
    tid = sys.argv[2]
    message = " ".join(sys.argv[3:])
    # Strip flags from message
    for flag in ["--dry-run", "--json"]:
        message = message.replace(flag, "").strip()
    if DRY_RUN:
        print(f"Would post to task {tid}: {message}")
        return
    _comment("task", tid, message)
    print(f"✅ Comment posted on task {tid}.")


def cmd_complete_task():
    """Mark task as done, log time, optionally create follow-up."""
    if len(sys.argv) < 3:
        print("Usage: kanban_worker.py complete-task <task_id> [--minutes M] [--follow-up 'title']")
        return
    tid = sys.argv[2]

    # Parse --minutes and --follow-up
    minutes = 0
    follow_up = None
    for i, arg in enumerate(sys.argv):
        if arg == "--minutes" and i + 1 < len(sys.argv):
            minutes = int(sys.argv[i + 1])
        if arg == "--follow-up" and i + 1 < len(sys.argv):
            follow_up = sys.argv[i + 1]

    if DRY_RUN:
        print(f"Would submit task {tid} for review, log {minutes}min"
              + (f", create follow-up: {follow_up}" if follow_up else ""))
        return

    # Submit for review (bots cannot mark done directly)
    kanban_put(f"/tasks/{tid}", {"status": "in_review"}, agent_name=AGENT_NAME)
    _comment("task", tid, "Submitted for review.")

    # Log time
    if minutes > 0:
        kanban_post(f"/tasks/{tid}/time", {
            "minutes": minutes,
            "description": f"Work by {AGENT_NAME}",
        }, agent_name=AGENT_NAME)
        print(f"  ⏱ Logged {minutes}min.")

    # Create follow-up
    if follow_up:
        # Get task to find workstream_id
        tasks = kanban_get(f"/tasks?assignee={AGENT_NAME}", AGENT_NAME)
        task = next((t for t in tasks if t["id"] == tid), None)
        if task:
            result = kanban_post("/tasks", {
                "workstream_id": task["workstream_id"],
                "title_en": follow_up,
                "assignee": AGENT_NAME,
                "status": "todo",
            }, agent_name=AGENT_NAME)
            print(f"  📋 Follow-up created: {result.get('id', '?')}")

    print(f"✅ Task {tid} submitted for review.")


def cmd_report_blocker():
    """Create a blocker on a workstream."""
    if len(sys.argv) < 4:
        print("Usage: kanban_worker.py report-blocker <workstream_id> <description>")
        return
    wid = sys.argv[2]
    desc = " ".join(sys.argv[3:])
    for flag in ["--dry-run", "--json"]:
        desc = desc.replace(flag, "").strip()

    if DRY_RUN:
        print(f"Would create blocker on ws {wid}: {desc}")
        return

    kanban_post("/blockers", {
        "workstream_id": wid,
        "description_en": f"[{AGENT_NAME}] {desc}",
    }, agent_name=AGENT_NAME)
    print(f"⚠ Blocker created on workstream {wid}.")


def cmd_report_bug():
    """Create a bug report."""
    if len(sys.argv) < 3:
        print("Usage: kanban_worker.py report-bug <title> [--severity S] [--task-id T]")
        return
    title = sys.argv[2]

    severity = "medium"
    task_id = None
    for i, arg in enumerate(sys.argv):
        if arg == "--severity" and i + 1 < len(sys.argv):
            severity = sys.argv[i + 1]
        if arg == "--task-id" and i + 1 < len(sys.argv):
            task_id = sys.argv[i + 1]

    if DRY_RUN:
        print(f"Would create bug: {title} (severity={severity}, task={task_id})")
        return

    body = {
        "title": title,
        "severity": severity,
        "reporter": AGENT_NAME,
        "description": f"Reported by {AGENT_NAME} during automated work.",
        "source": "agent",
    }
    if task_id:
        body["task_id"] = task_id

    result = kanban_post("/bugs", body, agent_name=AGENT_NAME)
    print(f"🐛 Bug created: {result.get('id', '?')} — {title}")


# ── Main ──────────────────────────────────────────────────────────────────

COMMANDS = {
    "board-summary": cmd_board_summary,
    "my-tasks": cmd_my_tasks,
    "pick-task": cmd_pick_task,
    "start-task": cmd_start_task,
    "update-task": cmd_update_task,
    "complete-task": cmd_complete_task,
    "report-blocker": cmd_report_blocker,
    "report-bug": cmd_report_bug,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        print(f"Agent: {AGENT_NAME}  |  API: {KANBAN_API}")
        return

    cmd = sys.argv[1]
    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    _ensure_user()
    COMMANDS[cmd]()


if __name__ == "__main__":
    main()

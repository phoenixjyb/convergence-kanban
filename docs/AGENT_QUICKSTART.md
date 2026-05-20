# ConvergenceKanban — API Quick Start for Coding Agents

This is the short reference for AI agents (Claude Code, Codex, Cursor, Aider,
GitHub Copilot, etc.) that want to interact with an ConvergenceKanban deployment.

> **Pull this file live** — it's served by the kanban itself:
> `curl <KANBAN_HOST>/api/agent-guide?format=quickstart`
> Drop that one-liner in your project's `CLAUDE.md` / `AGENTS.md` and your
> agent has the latest version every session.

`<KANBAN_HOST>` below means the URL where ConvergenceKanban is reachable from your
machine — typically `http://localhost:8666` for a local install, or a private
hostname on your network.

## Prerequisite — register your agent (one time)

Unknown user names are rejected with HTTP 401. Ask an admin to create your
bot user once before your first run:

```bash
# Run by a human admin, not by you
curl -X POST <KANBAN_HOST>/api/users \
  -H 'Content-Type: application/json' \
  -H 'X-Kanban-User: <admin-name>' \
  -d '{"name":"yourname-yourtool","display_name":"[Bot] yourname-yourtool","role":"bot"}'
```

Use the `{firstname}-{tool}` naming pattern (e.g. `alice-claude`, `bob-codex`,
`carol-cursor`). This makes activity logs readable at a glance.

## Setup

```bash
export KANBAN=<KANBAN_HOST>/api
export KANBAN_USER="yourname-yourtool"
```

## Workflow

### 1. Read the board

```bash
curl -s $KANBAN/dashboard | python3 -c "
import json,sys
for p in json.load(sys.stdin):
    print(f\"\\nProject: {p['name_en']} ({p['id']})\")
    for ws in p['workstreams']:
        s = ws['task_stats']
        print(f\"  {ws['title_en']} ({ws['id']}) — {s['done']}/{s['total']} done\")
"
```

### 2. Create a task

```bash
curl -s -X POST $KANBAN/tasks \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{
    "workstream_id": "WORKSTREAM_ID",
    "title_en": "What needs to be done",
    "title_zh": "需要做的事情",
    "assignee": "who",
    "status": "todo"
  }'
```

### 3. Update task status

```bash
# Start working
curl -s -X PUT $KANBAN/tasks/TASK_ID \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{"status": "doing"}'

# Submit for review (bots cannot mark done directly)
curl -s -X PUT $KANBAN/tasks/TASK_ID \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{"status": "in_review"}'
```

### 4. Report a blocker

```bash
curl -s -X POST $KANBAN/blockers \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{
    "workstream_id": "WORKSTREAM_ID",
    "description_en": "What is blocked",
    "description_zh": "阻塞描述"
  }'
```

### 5. Report a bug

**IMPORTANT**: Always include `"source": "agent"` — this routes your bug to
the agent bug table (separate from the QA team's manual bugs).

```bash
curl -s -X POST $KANBAN/bugs \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{
    "title": "Short descriptive title",
    "description": "Detailed description — expected vs actual behavior",
    "severity": "medium",
    "source": "agent",
    "reporter": "'$KANBAN_USER'",
    "project_id": "PROJECT_ID",
    "environment": "OS / runtime / build identifier",
    "steps_to_reproduce": "1. Do X\n2. Do Y\n3. Observe Z",
    "device_id": "(optional, if hardware-specific)"
  }'
```

Response: `{"id": "abc123", "display_id": "RD-260509-001"}`

### 6. Move a bug to `fix_complete` / `to_verify` / `resolved` with fix details

When the fix is in, populate fix metadata in the same call.

```bash
curl -s -X PUT $KANBAN/bugs/BUG_ID \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{
    "status": "fix_complete",
    "fix_method": "Commit/MR + what changed (be specific)",
    "fix_version": "main @ <hash> + new build",
    "fix_date": "2026-05-09"
  }'
```

### 7. Link bug to tasks (many-to-many)

```bash
curl -s -X POST $KANBAN/bugs/BUG_ID/tasks \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{"task_ids": ["TASK_ID_1", "TASK_ID_2"]}'

# Check bugs linked to a task you're working on
curl -s $KANBAN/tasks/TASK_ID/bugs
```

### 8. Post comments

```bash
curl -s -X POST $KANBAN/comments/task/TASK_ID \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{"body": "['$KANBAN_USER'] Progress update here"}'
```

### 9. Log time

```bash
curl -s -X POST $KANBAN/tasks/TASK_ID/time \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{"minutes": 30, "description": "Work by '$KANBAN_USER'"}'
```

### 10. Submit a QA ticket (optional Feishu wiki feature)

If the deployment has the Feishu wiki integration configured (see
`docs/SETUP.md`), agents can create QA work-order tickets in a Feishu wiki
sub-page from the API:

```bash
curl -s -X POST $KANBAN/qa-tickets \
  -H 'Content-Type: application/json' \
  -H "X-Kanban-User: $KANBAN_USER" \
  -d '{
    "task_type": "测试任务",
    "product": "rev-A hardware",
    "task_name": "BUG-260509-001 short description",
    "bug_id": "BUG-260509-001",
    "version": "main @ <hash> + new build",
    "requirements": {
      "scenario": "scenario description",
      "expected_result": "expected outcome",
      "record_screen": false,
      "record_data": true,
      "record_performance": false,
      "duration": "30 min",
      "other": ""
    }
  }'
# response: {"wiki_url": "...", "node_token": "...", "title": "..."}
```

`task_type` ∈ `{采集任务, 测试任务, 其它任务}`. `owner` defaults to
`X-Kanban-User`. Tickets land under a configurable Feishu wiki sub-page.

```bash
# List your tickets
curl -s "$KANBAN/qa-tickets?owner=$KANBAN_USER"

# Delete (best-effort — may need Feishu UI if wiki space blocks bot)
curl -s -X DELETE -H "X-Kanban-User: $KANBAN_USER" \
  "$KANBAN/qa-tickets/<node_token>"
```

If the QA ticket feature isn't configured on this deployment, these
endpoints return 503 with a hint.

## Task statuses

| Status | Bot can set? | Meaning |
|--------|:---:|---------|
| `todo` | Yes | Not started |
| `doing` | Yes | Actively working |
| `in_review` | Yes | Done, awaiting human review |
| `blocked` | Yes | Blocked (also create a Blocker record) |
| `done` | No | Human approved completion |
| `abandoned` | No | Work stopped by human decision |

## Bug severity

| Severity | When to use |
|----------|-------------|
| `critical` | System down, data loss |
| `high` | Major feature broken |
| `medium` | Bug with workaround (default) |
| `low` | Cosmetic, minor |

## Bug statuses

`open → investigating → fixing → fix_complete → to_verify → resolved → closed`
(also `wontfix`).

- **`fix_complete`** — fix merged; spot-check via linked QA ticket. Use
  this for daily MR fixes.
- **`to_verify`** — fix bundled into a weekly/monthly release; reserved
  for formal release verification.

## Bug display IDs

- Agent bugs: `RD-YYMMDD-NNN` (e.g. `RD-260509-001`) — routes to the
  agent bug table
- Manual bugs: `BUG-YYMMDD-NNN` (e.g. `BUG-260509-001`) — manual entry

## Project IDs

Get them from your deployment's `/api/projects`:

```bash
curl -s $KANBAN/projects | python3 -c "import json,sys; [print(f\"{p['id']}  {p['name_en']}\") for p in json.load(sys.stdin)]"
```

## Rules

- **Get pre-registered first** — unknown users get 401
- **Always** set `X-Kanban-User` header matching your registered name
  exactly
- **Always** include `"source": "agent"` when reporting bugs (bots cannot
  create `source='manual'` bugs — silently coerced if missing, but set it
  explicitly). You **can** modify QA-reported bugs (e.g. mark `to_verify`
  after fixing).
- **Always** read the dashboard first to find the correct `workstream_id`
- **Prefer** updating existing tasks over creating duplicates
- **Submit for review** (`in_review`) when you finish — a human approves
  to `done`
- **Link bugs to tasks** when reporting — helps the team track impact
- Both `title_en` and `title_zh` are welcome (bilingual board)

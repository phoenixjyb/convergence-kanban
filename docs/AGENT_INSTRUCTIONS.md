# ConvergenceKanban — Integration Guide for AI Coding Agents

> **Audience:** AI coding agents (Claude Code, Codex, Cursor, Aider,
> Copilot, etc.) running in **someone else's repo** that want to interact
> with an ConvergenceKanban deployment.
>
> **Easier:** drop just this one-liner in your repo's `CLAUDE.md` or
> `AGENTS.md` so your agent fetches the live guide on session start:
> ```
> ConvergenceKanban API guide: <KANBAN_HOST>/api/agent-guide
> (or ?format=quickstart for short version)
> ```

`<KANBAN_HOST>` below means the URL where ConvergenceKanban is deployed — typically
`http://localhost:8666` for a local install, or a private hostname on your
network.

## Project Kanban

- Board: `<KANBAN_HOST>/`
- Bug Tracker: `<KANBAN_HOST>/bugs`
- Analytics: `<KANBAN_HOST>/analytics`
- API: `<KANBAN_HOST>/api`
- API Docs: `<KANBAN_HOST>/docs` (auto-generated OpenAPI UI)
- **Live agent guide** (this doc, served from disk — always current):
  `<KANBAN_HOST>/api/agent-guide`

All agent actions are logged in the kanban `activity_log` table for audit.
If the deployment has the optional Feishu integration enabled, the team also
sees these actions surfaced in their Feishu Bitable views.

## Agent Identity (MANDATORY)

**Every agent MUST use the `{firstname}-{tool}` naming pattern.**

| Example | Meaning |
|---------|---------|
| `alice-codex` | Alice using Codex |
| `bob-copilot` | Bob using Copilot |
| `carol-claude` | Carol using Claude Code |
| `dan-cursor` | Dan using Cursor |

Set it before starting your session:

```bash
# For kanban_worker CLI users:
export KANBAN_AGENT_NAME="yourname-yourtool"

# For direct API / curl users:
# Replace MY_AGENT with your {firstname}-{tool} name in all curl commands below
```

**There is no acceptable default** — every agent must identify as
`{firstname}-{tool}`. Generic names like `claude-code` make it impossible to
tell who did what.

### Pre-registration required

**Unknown user names are rejected with HTTP 401.** Agents are not
auto-created. Before your first run, ask an admin (or the human owning the
agent) to register you:

```bash
# Run once per agent — admin/human creates the bot user
curl -X POST <KANBAN_HOST>/api/users \
  -H "Content-Type: application/json" \
  -H "X-Kanban-User: <admin-name>" \
  -d '{"name": "yourname-yourtool", "display_name": "[Bot] yourname-yourtool", "role": "bot"}'
```

Then verify:
```bash
curl -s "<KANBAN_HOST>/api/users" | grep yourname-yourtool
```

### Bot governance

Bot agents have restricted permissions:
- Cannot mark tasks `done` — use `in_review` instead, a human approves the transition
- Cannot mark tasks `abandoned` — humans decide what's abandoned
- Cannot create/delete projects or workstreams
- Cannot change workstream priorities, delete tasks/bugs, or modify user roles
- **Bugs:** can only **create** bugs with `source='agent'` (separate agent bug table). The QA team's bugs page (`source='manual'`) is read+modify only. If you submit a bug without `source='agent'` it is silently coerced — but always set it explicitly so you know where your bug landed.
- **Can:** claim tasks, change status to `todo`/`doing`/`in_review`/`blocked`, post comments, report bugs/blockers, log time, link bugs to tasks, **modify any bug** including QA-reported ones (e.g. set `to_verify` + `fix_method` after fixing)

## Workflow

### Session Start — Check Your Tasks

```bash
# List tasks assigned to you
curl -s -H "X-Kanban-User: MY_AGENT" \
  "<KANBAN_HOST>/api/tasks?assignee=MY_AGENT&status=doing"
```

### Claim a Task

```bash
# Browse available tasks
curl -s <KANBAN_HOST>/api/dashboard | python3 -c "
import json,sys; d=json.load(sys.stdin)
for p in d:
  for ws in p.get('workstreams',[]):
    for t in ws.get('tasks',[]):
      if t['status']=='todo' and not t.get('assignee'):
        print(f\"{t['id']}  [{ws.get('priority','?')}]  {t.get('title_en','')}  ({ws['title_en']})\")"

# Claim it
curl -s -X PUT -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/tasks/TASK_ID \
  -d '{"assignee":"MY_AGENT","status":"doing","start_date":"YYYY-MM-DD"}'
```

### Post Progress

```bash
curl -s -X POST -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/comments/task/TASK_ID \
  -d '{"body":"[MY_AGENT] Progress update here"}'
```

### Submit for Review

Bot agents cannot set status to `done`. Submit for human review instead:

```bash
curl -s -X PUT -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/tasks/TASK_ID \
  -d '{"status":"in_review"}'
```

### Report a Bug (IMPORTANT — read carefully)

Agent bugs go to a **separate table** from manual QA bugs. You MUST include
`"source": "agent"` in every bug submission.

```bash
curl -s -X POST -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/bugs \
  -d '{
    "title": "Short descriptive title",
    "description": "Detailed description — what broke, expected vs actual",
    "severity": "medium",
    "source": "agent",
    "reporter": "MY_AGENT",
    "project_id": "PROJECT_ID",
    "environment": "e.g. Ubuntu 24.04, Python 3.12",
    "steps_to_reproduce": "1. Do X\n2. Do Y\n3. Observe Z",
    "device_id": "(optional, if hardware-specific)"
  }'
```

The API returns `{"id": "...", "display_id": "RD-YYMMDD-NNN"}`.

**Required fields**: `title`, `source: "agent"`, `reporter`
**Recommended fields**: `severity`, `project_id`, `description`, `environment`, `steps_to_reproduce`, `device_id`

**Display ID format**:
- Agent bugs: `RD-YYMMDD-NNN` (e.g. `RD-260509-001`)
- Manual bugs: `BUG-YYMMDD-NNN` (e.g. `BUG-260509-001`)

**Bug severity**:

| Severity | When to use |
|----------|-------------|
| `critical` | System down, data loss, no workaround |
| `high` | Major feature broken |
| `medium` | Bug with workaround (default) |
| `low` | Cosmetic, minor inconvenience |

**Bug status flow**: `open → investigating → fixing → fix_complete → to_verify → resolved → closed` (also: `wontfix`)

#### `fix_complete` vs `to_verify`

- **`fix_complete`** — agent committed/merged the fix; QA team monitors this bucket and runs day-to-day MR-level spot-check via the linked QA ticket. **Use this for daily MR fixes.**
- **`to_verify`** — fix bundled into a weekly/monthly release; QA does formal end-to-end verification before sign-off.

When you fix a bug, the typical move is `fixing → fix_complete` (with QA
ticket + `bug_id` populated, if the wiki feature is enabled). A human/QA
promotes to `to_verify` later when the fix is rolled into a release;
`resolved` after QA passes.

### When you fix a bug — populate fix metadata

When moving a bug to `fix_complete`, `to_verify`, or `resolved`, include the
fix details in the same call. If the deployment has Feishu sync configured,
these sync to the team's Feishu Bitable columns 修复方法 / 修复版本 / 修复日期 so QA
can verify without re-digging.

```bash
curl -s -X PUT -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/bugs/BUG_ID \
  -d '{
    "status": "fix_complete",
    "fix_method": "What changed (commits, MRs, files, root cause). Be specific.",
    "fix_version": "main @ <commit-hash> or MR !<num> + new build",
    "fix_date": "YYYY-MM-DD"
  }'
```

| Field | Use it for |
|-------|------------|
| `fix_method` | The actual fix — commits, files, what changed and why |
| `fix_version` | Where the fix is delivered — branch, commit, MR, build, tarball location |
| `fix_date` | Date the fix landed (YYYY-MM-DD) |

### Submitting a QA ticket (optional Feishu wiki feature)

If the deployment has the optional Feishu wiki integration configured, you
can ask QA to run a manual test/data-collection by creating a wiki ticket
directly from the API. The endpoint creates a new page under a configurable
parent wiki node, populates an embedded sheet, and names it following a
convention.

```bash
curl -s -X POST -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/qa-tickets \
  -d '{
    "task_type": "测试任务",
    "product": "rev-A hardware",
    "task_name": "BUG-260509-001 short description",
    "version": "main @ <hash> + new build",
    "requirements": {
      "scenario": "scenario description — what test to run",
      "expected_result": "expected outcome",
      "record_screen": false,
      "record_data": true,
      "record_performance": false,
      "duration": "30 min",
      "other": "any extra notes"
    }
  }'
```

Response: `{"wiki_url": "...", "node_token": "...", "title": "..."}`

| Input | Required | Notes |
|-------|----------|-------|
| `task_type` | yes | One of `采集任务`, `测试任务`, `其它任务` (deployment-specific labels) |
| `product` | yes | e.g. hardware revision, build target |
| `task_name` | yes | Short fragment used in title — **prefix with the full bug_id** when verifying a bug (e.g. `"BUG-260509-001 short description"`) so QA sees the bug context in the title |
| `requirements` | yes | At least `scenario` should be set |
| `version` | no | Build/commit/identifier |
| `schedule_time` | no | `HH:MM`, defaults to current time |
| `owner` | no | Defaults to `X-Kanban-User` — must be `{firstname}-{tool}` for agents |
| `bug_id` | no | Kanban bug `display_id` this ticket verifies (e.g. `BUG-260509-001`). Written to a structured field for QA filtering. |

Title format auto-generated: `{YYYYMMDD}-{HH:MM}-{task_name}-{owner}`.

If the QA ticket feature isn't configured on this deployment, the endpoint
returns HTTP 503 with a hint. That's fine — just file the bug and let a
human follow up.

#### List your tickets

```bash
curl -s "<KANBAN_HOST>/api/qa-tickets?owner=MY_AGENT"
```

Returns `[{node_token, title, status, wiki_url}, ...]`. `status` is one of
`active`, `completed`, `cancelled` (derived from title prefix).

#### Delete a ticket (best-effort)

```bash
curl -s -X DELETE -H "X-Kanban-User: MY_AGENT" \
  "<KANBAN_HOST>/api/qa-tickets/<node_token>"
```

Returns `{"deleted": true}` on success. Feishu wiki space permissions may
block the bot from deleting nodes (returns `{"deleted": false, "hint": "...",
"wiki_url": "..."}`). If blocked, open the wiki URL and delete from the UI.

### Link a Bug to Tasks

Bugs support many-to-many task linking. After creating a bug, link related
tasks:

```bash
# Link one or more tasks to a bug
curl -s -X POST -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/bugs/BUG_ID/tasks \
  -d '{"task_ids":["TASK_ID_1","TASK_ID_2"]}'

# Check which bugs are linked to a task you're working on
curl -s <KANBAN_HOST>/api/tasks/TASK_ID/bugs
```

### Report a Blocker

```bash
curl -s -X POST -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/blockers \
  -d '{"workstream_id":"WS_ID","description_en":"[MY_AGENT] Blocker description"}'
```

### Log Time

```bash
curl -s -X POST -H "Content-Type: application/json" -H "X-Kanban-User: MY_AGENT" \
  <KANBAN_HOST>/api/tasks/TASK_ID/time \
  -d '{"minutes":30,"description":"Work by MY_AGENT"}'
```

## Task Status Flow

```
todo  -->  doing  -->  in_review  -->  done       (human approves)
                  \--> blocked
                  \--> abandoned   (humans only — work explicitly stopped)
```

| Status | Meaning | Bot can set? |
|--------|---------|--------------|
| `todo` | Not started | Yes |
| `doing` | Agent is actively working on it | Yes |
| `in_review` | Agent finished, awaiting human review | Yes |
| `blocked` | Blocked by an external dependency (also create a Blocker record) | Yes |
| `done` | Human approved completion | No — humans only |
| `abandoned` | Work explicitly stopped — counts as complete for progress | No — humans only |

If a human decides to abandon work you started, they will set the task to
`abandoned` directly. Don't fight it — just stop and pick up another task.

## Project IDs

Get them from your deployment's `/api/projects`:

```bash
curl -s <KANBAN_HOST>/api/projects | python3 -c "
import json,sys
for p in json.load(sys.stdin):
    print(f\"  {p['id']}  {p['name_en']}\")
"
```

Use the returned `id` value as `project_id` when creating bugs.

## Rules Summary

- **Get pre-registered first** — unknown users get 401
- **Always** set `X-Kanban-User` header matching your registered name exactly
- **Always** include `"source": "agent"` when reporting bugs
- **Always** read the dashboard first to find the correct `workstream_id`
- **Prefer** updating existing tasks over creating duplicates
- **Submit for review** (`in_review`) when you finish — a human approves to `done`
- **Link bugs to tasks** when reporting — helps the team track impact
- Both `title_en` and `title_zh` are welcome (bilingual board)

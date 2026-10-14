# ConvergenceKanban — API Quick Start for Coding Agents

This is the short reference for AI agents (Claude Code, Codex, Cursor, Aider,
GitHub Copilot, etc.) that want to interact with an ConvergenceKanban deployment.

本文件是给编码 Agent 使用的简版 API 工作流说明。命令示例保持英文和 shell
格式不变，中文说明用于帮助团队成员快速审阅规则意图。

> **Pull this file live** — it's served by the kanban itself:
> `curl <KANBAN_HOST>/api/agent-guide?format=quickstart`
> Drop that one-liner in your project's `CLAUDE.md` / `AGENTS.md` and your
> agent has the latest version every session.
>
> **建议实时拉取**：把上面的一行命令放进项目的 `CLAUDE.md` / `AGENTS.md`，
> Agent 每次会话都能拿到当前部署的最新规则。

`<KANBAN_HOST>` below means the URL where ConvergenceKanban is reachable from your
machine — typically `http://localhost:8666` for a local install, or a private
hostname on your network.

Human team workflow guide:
`curl <KANBAN_HOST>/api/agent-guide?format=team`

## Prerequisite — register your agent (one time)

Unknown user names are rejected with HTTP 401. Ask an admin to create your
bot user once before your first run:

未知用户名会被 401 拒绝。首次使用前，请管理员先创建 bot 用户。

```bash
# Run by a human admin, not by you
curl -X POST <KANBAN_HOST>/api/users \
  -H 'Content-Type: application/json' \
  -H 'X-Kanban-User: <admin-name>' \
  -d '{"name":"yourname-yourtool","display_name":"[Bot] yourname-yourtool","role":"bot"}'
```

Use the `{firstname}-{tool}` naming pattern (e.g. `alice-claude`, `bob-codex`,
`carol-cursor`). This makes activity logs readable at a glance.

命名统一使用 `{firstname}-{tool}`，这样活动日志可以直接看出是谁用哪个工具操作。

## Setup

```bash
export KANBAN=<KANBAN_HOST>/api
export KANBAN_USER="yourname-yourtool"
```

## Workflow

Cross-team concerns belong in `/api/issues`, separately from software bugs.
See [Issues workflow](ISSUES_WORKFLOW.md), also served through
`/api/agent-guide?format=issues`. Agents can submit/update and use
`pending_review`; only humans close/archive/restore. 跨团队重点问题使用 issues
接口，Agent 完成后提交 `pending_review`，人类确认关闭。

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

Workstream status and progress update automatically from all tasks and
subtasks. Agents must update task status only; the workstream status API is
read-only derived state.

Workstream 状态和进度会根据全部任务及子任务自动更新。Agent 只更新任务状态，
不要尝试手工修改 workstream 状态。

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

**重要**：Agent 新建缺陷时必须带 `"source": "agent"`，这样会进入 RD/Agent
缺陷表，不会混入 QA 手工缺陷表。

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

修复落地后，状态和修复元数据要在同一次请求里更新。MR 级修复默认使用
`fix_complete`；`to_verify` 留给进入正式验证构建后的 QA/发布流程。

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

Do not use personal Feishu bot tokens. Use the kanban API with your
`X-Kanban-User`; the kanban backend owns the configured Feishu app/bot and
creates the wiki page centrally. The returned `wiki_url` still depends on
the Feishu wiki space or parent-page permissions.

不要使用个人飞书机器人 token。Agent 只调用 Kanban API，并带上自己的
`X-Kanban-User`；Kanban 后端统一使用部署配置里的飞书应用/机器人创建 wiki
页面。`wiki_url` 能否打开，取决于飞书 wiki 空间或父页面权限。

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
`X-Kanban-User`. `version` should identify the MR, commit, branch, build,
APK, or tarball QA should verify. Tickets land under a configurable Feishu
wiki sub-page.

```bash
# List your tickets
curl -s "$KANBAN/qa-tickets?owner=$KANBAN_USER"

# Delete (best-effort — may need Feishu UI if wiki space blocks bot)
curl -s -X DELETE -H "X-Kanban-User: $KANBAN_USER" \
  "$KANBAN/qa-tickets/<node_token>"
```

If the QA ticket feature isn't configured on this deployment, these
endpoints return 503 with a hint. HTTP 401 means the agent user has not
been registered yet. If ticket creation succeeds but people cannot open the
wiki URL, fix Feishu wiki parent/space sharing rather than changing agent
credentials. For private-network kanban hosts, add `--noproxy '*'` if your
shell proxy catches local addresses.

常见问题：401 表示用户未注册；503 表示该部署未配置飞书 wiki ticket 功能；
ticket 创建成功但打不开页面，通常是飞书父页面或空间分享权限问题，不是 Agent
凭据问题。

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

Agents should stop at `fix_complete` for normal MR-level work. A human
release owner or QA promotes the bug to `to_verify` once the fix is in a
verification build.

普通 MR 级修复由 Agent 停在 `fix_complete`。进入周版/月版等验证构建后，再由
发布负责人或 QA 推进到 `to_verify`。

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
- **Link fixed bugs to tasks** before changing bug status — helps QA recover
  the implementation context
- Both `title_en` and `title_zh` are welcome (bilingual board)

中文摘要：

- 先注册 Agent 用户；未注册会返回 401。
- 每次写操作都带 `X-Kanban-User`。
- 新建缺陷时显式设置 `"source": "agent"`。
- 先读 dashboard，优先接已有任务，不要制造重复任务。
- Agent 完成任务后进入 `in_review`，由人类确认到 `done`。
- 修复缺陷时必须关联任务，并填写 `fix_method`、`fix_version`、`fix_date`。

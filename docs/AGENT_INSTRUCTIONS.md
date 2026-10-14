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

中文说明：本文件面向在其他项目 repo 中工作的编码 Agent。命令和 API payload
保持单一英文版本，中文段落用于解释团队规则和审核意图。

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

Human team workflow guide: `<KANBAN_HOST>/api/agent-guide?format=team`
when available in your deployment, or `docs/TEAM_WORKFLOW.md` in the repo.

## Agent Identity (MANDATORY)

**Every agent MUST use the `{firstname}-{tool}` naming pattern.**

**每个 Agent 必须使用 `{firstname}-{tool}` 命名。** 这样活动日志、bug
修复记录和 QA ticket 都能追溯到具体的人和工具。

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

不要使用 `claude-code`、`codex`、`agent` 这类泛化名字。

### Pre-registration required

**Unknown user names are rejected with HTTP 401.** Agents are not
auto-created. Before your first run, ask an admin (or the human owning the
agent) to register you:

未知用户名会被 HTTP 401 拒绝。首次使用前，请管理员或该 Agent 的负责人先注册
bot 用户。

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

中文规则：Bot 可以认领任务、更新到 `doing` / `in_review` / `blocked`、评论、
报 bug、记录时间和关联任务；但不能直接把任务设为 `done` / `abandoned`，也不能
删除项目、workstream、任务或 bug。Agent 新建 bug 进入 `source='agent'` 表；
QA 手工 bug 可以被 Agent 修改修复信息，但不应由 Agent 跳过 QA 流程直接关闭。

Workstream status and progress are derived automatically from all active tasks,
including subtasks. Update task status only; manual workstream status updates
are rejected. Workstream 状态和进度由全部有效任务（含子任务）自动计算；Agent
只更新任务状态，不能手工修改 workstream 状态。

## Workflow

For cross-team hardware, software, product experience, process, and delivery
concerns use `/api/issues`; this register is independent of `/api/bugs`.
See [Issues workflow](ISSUES_WORKFLOW.md) or fetch
`/api/agent-guide?format=issues` for fields and examples. Agents may raise and
update issues and submit `pending_review`, but closure/archive/restore requires
a human. 跨团队问题使用独立 issues 接口；Agent 只能提交评审，由人类确认关闭。

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

Do not use `to_verify` just because code was committed. Use it only when a
human release owner says the fix is in a verification build.

中文规则：日常 MR/commit 级修复默认进入 `fix_complete`，并填写修复信息和 QA
ticket。`to_verify` 只表示修复已经进入正式验证构建，不是“代码已经提交”的同义词。

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

Link the bug to the task(s) or workstream task that carried the fix. This is
how QA, humans, and future agents can recover why a bug changed state.

中文规则：进入 `fix_complete`、`to_verify` 或 `resolved` 时，必须同步填写
`fix_method`、`fix_version`、`fix_date`，并关联承载修复的任务。否则 QA 无法
判断在哪个 MR、commit、构建包或发布版本里验证。

### Submitting a QA ticket (optional Feishu wiki feature)

If the deployment has the optional Feishu wiki integration configured, you
can ask QA to run a manual test/data-collection by creating a wiki ticket
directly from the API. The endpoint creates a new page under a configurable
parent wiki node, populates an embedded sheet, and names it following a
convention.

Do not use personal Feishu bot tokens or call Feishu write APIs directly
from project repos. Agents create QA tickets through the kanban API with
their own `X-Kanban-User`; the kanban backend owns the configured Feishu
app/bot credentials and centralizes page creation. The returned `wiki_url`
is visible only to users who have access to the configured Feishu wiki space
or parent page.

中文规则：不要在项目 repo 里使用个人飞书机器人 token，也不要让 Agent 直接调用
飞书写接口。QA ticket 统一通过 Kanban API 创建；Kanban 后端使用部署配置里的
飞书应用/机器人创建 wiki 页面。页面能否打开取决于飞书 wiki 空间或父页面权限。

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

Recommended payload shape for bug verification:

```json
{
  "task_type": "测试任务",
  "product": "<product / hardware / platform>",
  "task_name": "BUG-YYMMDD-NNN short human-readable title",
  "bug_id": "BUG-YYMMDD-NNN",
  "version": "<MR / commit / branch / build / APK / tarball>",
  "requirements": {
    "scenario": "<exact flow QA should run>",
    "expected_result": "<observable pass condition>",
    "record_screen": false,
    "record_data": true,
    "record_performance": false,
    "duration": "30 min",
    "other": "<logs, devices, datasets, or caveats>"
  }
}
```

Title format auto-generated: `{YYYYMMDD}-{HH:MM}-{task_name}-{owner}`.

If the QA ticket feature isn't configured on this deployment, the endpoint
returns HTTP 503 with a hint. That's fine — just file the bug and let a
human follow up.

Common failure modes:

| Symptom | Meaning / action |
|---------|------------------|
| HTTP 401 `Unknown user` | Register the agent as a bot user, then retry with the same `X-Kanban-User`. |
| HTTP 503 `QA ticket feature not configured` | Deployment is missing the Feishu wiki env vars; continue with the kanban bug/task and ask an admin to configure the integration. |
| Ticket created but `wiki_url` cannot be opened | Feishu wiki sharing is too narrow. Ask the wiki owner/admin to share the parent page or space with QA/dev and allow child-page visibility. |

If the kanban is on a private network, add `--noproxy '*'` to `curl` when
your shell proxy would otherwise intercept local addresses.

中文排障：401 表示 Agent/用户未注册；503 表示该部署还没有配置飞书 wiki ticket
功能；ticket 已创建但打不开 `wiki_url`，通常是飞书父页面或空间分享权限问题。
私网地址被代理拦截时，`curl` 加 `--noproxy '*'`。

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

中文摘要：

- Agent 先注册，所有写操作都带匹配的 `X-Kanban-User`。
- 新建 bug 时显式设置 `"source": "agent"`。
- 先读 dashboard，优先更新已有任务，不要重复建任务。
- 完成任务后提交 `in_review`，由人类确认到 `done`。
- 修复 bug 时关联任务，并填写 `fix_method`、`fix_version`、`fix_date`。

# ConvergenceKanban Team Workflow

This guide is for humans using a ConvergenceKanban deployment for day-to-day
task and bug tracking. AI agents should fetch the live agent guide from
`/api/agent-guide`.

本指南面向日常使用 ConvergenceKanban 做任务、缺陷和 QA 协作的人类团队成员。
AI Agent 应从 `/api/agent-guide` 拉取实时集成指南。

## Main Surfaces

| Surface | Use it for |
|---------|------------|
| `/` | Project, workstream, task, blocker, review, and activity tracking / 项目、工作流、任务、阻塞、评审和动态 |
| `/bugs` | QA and agent bug triage, fix metadata, and verification status / QA 与 Agent 缺陷分诊、修复信息和验证状态 |
| `/analytics` | Burndown, bug trend, workload, blocker aging, and Gantt views / 燃尽图、缺陷趋势、工作量、阻塞时长和甘特图 |
| `/api/agent-guide` | Live REST workflow guide for coding agents / 给编码 Agent 使用的实时 API 工作流指南 |
| Feishu Bitable | Optional human-friendly mirror for teams already working in Feishu / 面向飞书团队的人类友好镜像 |

## Daily Task Flow

Use `/issues` for cross-team hardware, software, product experience, delivery,
and process concerns. Any team member may raise an issue without a project or
task. See [Top Issues workflow](ISSUES_WORKFLOW.md) for ownership, resolution,
and Feishu sync. `/issues` 用于跨团队重点问题，任何成员都可以提交；软件具体缺陷
仍在 `/bugs`，执行工作仍在任务看板。详见重点问题流程。

The Issues page adds an **Attention** filter alongside category, status, owner,
and priority: **All**, **Unassigned**, **Overdue**, and **Stale (14+ days)**.
Attention selections omit closed and archived issues, even when archived items
are otherwise shown. Overdue means the due date is strictly before today's date
in Asia/Shanghai. Stale means the latest `updated_at` (or `created_at` when no
update timestamp is present) is at least 14 elapsed days old; zone-less issue
timestamps are interpreted in Asia/Shanghai, and future timestamps are not
stale. This is a view filter only; it does not send reminders or modify issues.

问题页面在类别、状态、负责人和优先级筛选旁新增“关注项”筛选：全部、未分配、已逾期、
停滞（14 天及以上）。选择具体关注项时会排除已关闭和已归档的问题，即使页面同时显示
归档项也不例外。已逾期表示截止日期严格早于 Asia/Shanghai 时区的今天。停滞表示最近
更新时间（缺少 `updated_at` 时使用 `created_at`）距今至少 14 个完整日；不带时区的
问题时间戳按 Asia/Shanghai 解释，未来时间戳不算停滞。此筛选仅影响视图，不发送提醒，
也不会修改问题。

1. Create work under the right project and workstream.
2. Use task statuses consistently:
   - `todo` — not started
   - `doing` — actively owned
   - `in_review` — agent or teammate says the work is ready for human review
   - `done` — human-approved completion
   - `blocked` — cannot progress; add a blocker or comment
   - `abandoned` — intentionally stopped
3. Prefer comments on tasks for progress and handoff notes.
4. Use subtasks for concrete child work that should stay attached to a parent
   task instead of creating sibling tasks with ambiguous names.

中文规则：

1. 任务应放在正确的项目和 workstream 下，不要随手建到临时位置。
2. 状态含义要稳定：`todo` 未开始，`doing` 正在做，`in_review` 等人类评审，
   `done` 人类确认完成，`blocked` 需要明确阻塞原因，`abandoned` 表示明确放弃。
3. 进度、交接和风险优先写在任务评论里。
4. 子任务用于同一个父任务下的具体拆分，不要为了表达子工作而创建一堆名字含糊的平级任务。

Workstream status and progress are automatic and include subtasks. The roll-up
rules are: no started work is `planned`; any blocked task makes it `blocked`;
all remaining unfinished tasks in `in_review` makes it `review`; partially
completed or active work is `in-progress`; and all tasks in `done` or
`abandoned` makes it `done`. Team members should update tasks, not workstream
status directly.

Workstream 的状态和进度由全部有效任务（包括子任务）自动汇总：尚未开始为
`planned`；任一任务阻塞时为 `blocked`；所有剩余未完成任务都在 `in_review`
时为 `review`；已有部分进展时为 `in-progress`；全部任务为 `done` 或
`abandoned` 时为 `done`。团队只需维护任务状态，不再手工修改 workstream 状态。

## Bug Flow

The bug pipeline is:

`open -> investigating -> fixing -> fix_complete -> to_verify -> resolved -> closed`

- `fix_complete` means the fix landed in an MR/commit and is ready for
  daily QA spot-check.
- `to_verify` means the fix is included in a weekly/monthly release build and
  is ready for formal release verification.
- `resolved` means QA verified the fix.
- `closed` means the item is finished and no longer needs tracking.

When moving a bug to `fix_complete`, `to_verify`, or `resolved`, always fill:

| Field | Purpose |
|-------|---------|
| `fix_method` | What changed and why: MR, commits, files, root cause |
| `fix_version` | Where QA can verify it: branch, commit, build, release |
| `fix_date` | Date the fix landed or entered the release build |

Link bugs to the tasks or workstreams that own the fix. This keeps QA status,
agent work, and team planning connected.

中文规则：

- `fix_complete` 表示 MR/commit 级修复已经落地，适合 QA 日常抽查。
- `to_verify` 表示修复已经进入周版/月版等验证构建，进入正式发布验证。
- `resolved` 表示 QA 已验证通过。
- `closed` 表示该问题不再需要继续跟踪。
- 进入 `fix_complete`、`to_verify` 或 `resolved` 时，必须同时填写
  `fix_method`、`fix_version`、`fix_date`。否则 QA 不知道去哪一个版本、
  哪一个 MR 或哪一个构建里验证。
- 缺陷应关联到承载修复的任务或 workstream，便于后续追溯。

## QA Ticket Workflow

Optional Feishu QA tickets are created through the kanban API, not through
personal Feishu bot tokens. Agents and teammates submit tickets with their
own kanban identity (`X-Kanban-User`); the kanban backend uses the deployment's
configured Feishu app/bot to create the wiki page under the shared QA parent.

Use QA tickets when a bug fix needs manual verification, data collection, or
a clear QA handoff page. A good ticket includes:

| Field | What QA needs |
|-------|---------------|
| `task_type` | `测试任务`, `采集任务`, or `其它任务` |
| `product` | Product, hardware revision, platform, or target environment |
| `task_name` | Start with the full bug ID, then a short title |
| `bug_id` | The kanban bug display ID, for filtering and traceability |
| `version` | MR, commit, branch, release, APK, tarball, or other build marker |
| `requirements.scenario` | Exact flow QA should run |
| `requirements.expected_result` | Observable pass condition |

Example:

```bash
curl -s -X POST <KANBAN_HOST>/api/qa-tickets \
  -H 'Content-Type: application/json' \
  -H 'X-Kanban-User: alice-codex' \
  -d '{
    "task_type": "测试任务",
    "product": "rev-A hardware",
    "task_name": "BUG-260509-001 short description",
    "bug_id": "BUG-260509-001",
    "version": "MR !123 + main @ <hash>",
    "requirements": {
      "scenario": "exact flow to run",
      "expected_result": "expected pass condition",
      "record_screen": false,
      "record_data": true,
      "record_performance": false,
      "duration": "30 min",
      "other": ""
    }
  }'
```

If the API returns 401, register the agent/user in kanban first. If it
returns 503, the deployment is missing the Feishu wiki configuration. If a
ticket is created but the `wiki_url` cannot be opened, fix Feishu parent-page
or space sharing so QA/dev members can see child pages.

中文规则：

- QA ticket 统一通过 Kanban API 创建，不使用个人飞书机器人 token，也不让各项目
  repo 直接调用飞书写接口。
- Agent 或团队成员用自己的 `X-Kanban-User` 提交；Kanban 后端使用部署时配置的
  飞书应用/机器人统一创建 wiki 页面。
- `task_name` 建议以完整 bug ID 开头，`version` 必须能指向 QA 可验证的 MR、
  commit、分支、构建包、APK 或 tarball。
- 如果返回 401，先注册这个 Agent/用户；如果返回 503，说明部署还没配置飞书
  wiki ticket 功能；如果 ticket 创建成功但打不开 `wiki_url`，应修复飞书 wiki
  父页面或空间权限，而不是更换 Agent 凭据。

## Feishu Sync Expectations

Feishu Bitable is a mirror, not a replacement for the kanban API. The kanban
database remains the source of truth.

- Normal sync is periodic, so changes can lag briefly.
- If Feishu and kanban edit the same field at the same time, the conflict
  appears in Sync Conflicts.
- Open Sync Conflicts from the header button to review unresolved conflicts
  and the current sync health summary.
- The sync health panel shows the state file update time, unresolved conflict
  count, and synced record coverage for projects, tasks, QA bugs, and RD bugs.

中文规则：

- Kanban 数据库是源头；飞书 Bitable 是镜像，不是替代品。
- 同步是周期性的，短时间延迟是正常现象。
- 如果同一字段在飞书和 Kanban 两边同时编辑，冲突会出现在 Sync Conflicts。
- Sync Conflicts 面板也会显示当前同步健康度、冲突数量和各表覆盖情况。

## Working With AI Agents

In group chats, explicitly mention the Kanban bot first and then send a known
command, for example `@bot help` or `@bot progress`. Ordinary conversation,
`@all`, mentions of other people, and unrecognized requests receive no reply.
In a private chat with the bot, recognized commands work without a mention.

群聊中请先明确 @看板机器人，再输入它支持的命令，例如 `@机器人 帮助`、
`@机器人 进度`。普通聊天、@所有人、@其他成员及无法识别的请求不会触发回复。
私聊机器人时，可直接输入支持的命令。

Register each agent as a bot user before it works on the board. Use the
`{firstname}-{tool}` naming pattern, for example `alice-codex` or
`bob-claude`.

Agents should:

- fetch `/api/agent-guide?format=quickstart` at session start;
- use `X-Kanban-User` on every mutation;
- claim existing tasks before creating new ones;
- move finished task work to `in_review`, not `done`;
- create bugs with `source: "agent"`;
- move fixed bugs to `fix_complete` with fix metadata;
- create QA tickets through `/api/qa-tickets`, never with personal Feishu
  tokens or direct Feishu write calls;
- let humans or QA promote release-build fixes to `to_verify` and then
  `resolved`.

中文规则：

- 每个 Agent 先注册成 bot 用户，命名使用 `{firstname}-{tool}`，例如
  `alice-codex`、`bob-claude`。
- Agent 每次会话开始先拉取 `/api/agent-guide?format=quickstart`。
- Agent 不能把任务直接置为 `done`，完成后应进入 `in_review` 等人类确认。
- Agent 提交的新缺陷使用 `source: "agent"`；修复 QA 缺陷时可以修改对应 bug，
  但 MR 级修复默认停在 `fix_complete`。
- `to_verify` 和 `resolved` 由 QA 或发布负责人根据验证构建推进。

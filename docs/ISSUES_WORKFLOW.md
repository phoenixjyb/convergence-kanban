# Top Issues / 重点问题

Top Issues is a cross-team register for hardware, software, product experience,
process, delivery, and operational concerns. An issue can be raised before a
project or implementation task exists. Use `/issues`; keep specific reproducible
software defects in `/bugs`, and link the relevant work to the broader issue.

重点问题用于跨团队跟踪硬件、软件、产品体验、流程、交付和运营问题。
不要求先建立项目或任务。入口为 `/issues`；具体软件缺陷仍放在 `/bugs`，
再关联到重点问题。任何团队成员都可以提出问题。

## Fields / 字段

| Kanban field | Feishu column | Meaning / 含义 |
|---|---|---|
| `display_id` | Issue ID | Automatic `ISS-YYMMDD-NNN` / 自动问题编号 |
| `title` | Title | Short title / 简短标题 |
| `introduction` | Introduction | Background / 简介和背景 |
| `content` | Issue Content | Problem, evidence, impact / 内容、证据和影响 |
| `raised_by`, `raised_date` | Raised By, Raised Date | Raiser and date / 提出人和日期 |
| `category` | Category | hardware, software, product_experience, process, delivery, operations, other |
| `priority`, `rank` | Priority, Rank | critical/high/medium/low; smaller positive rank comes first, 0 is unranked / 正排名越小越靠前，0 表示未排名 |
| `owner`, `due_date` | Owner, Target Date | Accountable person and target date / 负责人和目标日期 |
| `status` | Status | open, triaged, in_progress, blocked, pending_review, closed |
| `resolution_criteria` | Resolution Criteria | Observable acceptance condition / 解决标准 |
| `resolution` | Outcome | Outcome and evidence / 结果和证据 |
| `project_id`, `workstream_id` | Project ID, Workstream ID | Optional links / 可选关联 |
| `task_ids`, `bug_ids` | Task IDs, Bug IDs | JSON arrays of internal IDs / 内部 ID 的 JSON 数组 |
| `deleted_at` | Archived | Reversible archival / 可恢复归档 |

Raiser/owner columns are text so people without a linked Feishu account can
participate. In Kanban, related work is selected by its readable label; the
API and Feishu reference columns store internal IDs, not display IDs.

提出人和负责人使用文本，未绑定飞书账号的成员也可以参与。Kanban 中通过可读名称
选择关联工作；API 和飞书关联列保存内部 ID，不是 BUG/ISS 展示编号。

## Workflow / 流程

`open -> triaged -> in_progress -> pending_review -> closed`; use `blocked`
when progress needs an external action. Human review is required to close an
issue. Closure requires both criteria and an outcome. Agents may submit and
update issues, post comments, and request review; they cannot close, archive,
or restore issues. Completing linked tasks does not automatically close an issue.

新问题进入 `open`，分诊后指定负责人、优先级和解决标准。执行后进入
`pending_review`，人类确认结果后才能 `closed`；阻塞时使用 `blocked`。
关闭必须填写解决标准和结果。Agent 可以提出问题、更新进度、评论并提交评审，
不能关闭、归档或恢复问题。关联任务完成不会自动关闭重点问题。

## API / 接口

Use a registered identity through `X-Kanban-User`. Read endpoints need no login.

```bash
curl -X POST '<KANBAN_HOST>/api/issues' \
  -H 'Content-Type: application/json' \
  -H 'X-Kanban-User: alice-codex' \
  -d '{"title":"Controls unreadable outdoors","content":"Users cannot identify controls in sunlight.","category":"product_experience","priority":"high","resolution_criteria":"A teammate completes the outdoor flow without guessing controls."}'
```

- `GET /api/issues` supports category/status/owner/priority filters and
  `include_deleted=true`; closed issues sort after active issues.
- `GET /api/issues/{id}`, `PUT /api/issues/{id}` read/update a record.
- `DELETE /api/issues/{id}`, `POST /api/issues/{id}/restore` archive/restore.
- `GET/POST /api/comments/issue/{id}` read/post local comments and activity.
- Clear optional project/workstream/date fields with `null`; clear links with `[]`.

## Feishu Setup / 飞书配置

Run on the deployment checkout after installing the new code. Preview is local:

```bash
python3 scripts/setup_issues_bitable.py --profile team
```

An operator authorized to modify the deployment's Bitable can provision it:

```bash
python3 scripts/setup_issues_bitable.py --profile team --apply
```

This reuses or creates `Top Issues` inside the configured Bitable, adds missing
columns/options, and stores `issues_table` in that profile's sync state. It does
not convert incompatible existing column types. Restart the sync process after
provisioning so it loads the new profile state. Check `/api/sync/status` for the
issues cycle timestamp, errors, conflicts, and acknowledged record count.

预览命令不会加载飞书凭据或访问飞书。获授权的管理员使用 `--apply` 后，脚本
在当前 Bitable 内复用或创建 Top Issues 表，补齐字段和选项，并保存配置。
已有不兼容的字段类型需要人工处理。配置完成后重启同步进程加载状态，检查
`/api/sync/status` 中重点问题的同步时间、错误、冲突和记录数量。

Sync uses the last acknowledged field values. Edits to different fields merge;
conflicting edits go to the existing conflicts panel. Failed writes do not
advance the baseline. If existing records disagree on first connection, review
the conflicts instead of automatically choosing a winner.

Use **Archived**, not physical row deletion, for reversible removal in Feishu.
Missing or duplicate remote records are reported for operator attention;
incomplete reads never trigger creation or deletion. Invalid remote values
remain untouched and count as sync errors. Feishu editors are trusted to perform
human actions such as closure; manage table editing permissions accordingly.
Comments/activity are local to Kanban in this first version.

New Feishu submissions need both **Title** and **Issue Content** before import.
The Top Issues page shows incomplete submissions under **awaiting details**,
with their titles and missing fields (up to 10 samples). Fill the missing fields
in Feishu; the next sync imports the issue and assigns its ID automatically.
Blank unlinked template rows are ignored. No content is invented and no draft is
written back. Invalid changes to already-linked issues still count as errors.

同步比较上次确认成功的字段值：不同字段的修改自动合并，同字段冲突进入现有
冲突面板，写入失败不推进同步基线。首次接入时不一致的数据需要人工选择。
飞书删除使用 Archived 复选框，不物理删除记录；丢失、重复或非法记录会报告
错误，不盲目覆盖。飞书表编辑者被视为可信的人类操作员，应配置相应权限。
当前版本评论和动态只保存在 Kanban。

飞书新问题必须填写 **Title** 和 **Issue Content** 后才会导入。重点问题页面会显示
“待补全”的数量、标题及缺失字段（最多 10 条示例）。在飞书补全后，下次同步会自动
导入并分配编号。未关联的空白模板行直接忽略；系统不会编造内容或回写草稿。
已关联问题的非法修改仍计为同步错误。

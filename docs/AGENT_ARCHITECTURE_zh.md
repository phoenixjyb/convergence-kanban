# ConvergenceKanban — AI 代理交互架构

> **目标读者：** 部署 ConvergenceKanban 的团队成员（带 AI 代理的开发者，以及 QA / PM）
> **要点：** 团队成员的 AI 代理（Claude Code / Codex / Cursor 等）如何与看板服务和 Feishu / Lark 协作

> 英文版本请见 [`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md)。

---

## 1. 一句话概括

团队成员的 AI 代理跑在**自己的电脑**上，只通过 HTTP 调用看板服务（`<KANBAN_HOST>`）。
看板服务可选地用一个 **Feishu / Lark 自建应用的凭证**与 Feishu Bitable / Wiki / 群聊交互。
代理**不直接接触 Feishu**。

---

## 2. 全景图

```
┌────────────────────────────────────────────────────────────┐
│ 团队成员的笔记本                                            │
│                                                            │
│  AI 代理 (Claude Code / Codex / Cursor 等)                  │
│  ↓ 自动读取项目仓库根目录的 CLAUDE.md / AGENTS.md            │
│  ↓ 看到指引: curl <KANBAN_HOST>/api/agent-guide             │
│  ↓ 身份: X-Kanban-User: alice-claude (firstname-tool)       │
└──────────────────────────────┬─────────────────────────────┘
                               │ HTTP
                               ▼
┌────────────────────────────────────────────────────────────┐
│ ConvergenceKanban 服务器  (<KANBAN_HOST>, 例如 :8666)              │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ convergence-kanban (FastAPI 主服务)                        │  │
│  │  - 接收代理的 HTTP 调用                               │  │
│  │  - 执行身份校验 / Bot 治理规则                        │  │
│  │  - 读写本地 SQLite (data/kanban.db)                   │  │
│  │  - 需要写 Feishu 时: 用 .env 里的                     │  │
│  │    FEISHU_APP_ID / FEISHU_APP_SECRET                  │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ feishu_sync.py (可选 — 双向同步)                     │  │
│  │  - 每 30 秒轮询 Feishu Bitable                       │  │
│  │  - 推送本地变更 → Feishu                              │  │
│  │  - 拉取 Feishu 变更 → 本地                            │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ feishu_bot.py (可选 — 聊天 + 通知)                   │  │
│  │  - 用 WebSocket 长连飞书                             │  │
│  │  - 处理 @bot help / @bot my tasks 等聊天指令          │  │
│  │  - 在群里发缺陷 / 阻塞 / 周报通知卡片                  │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────────────────┬─────────────────────────────┘
                               │ 三个服务都用同一个 Feishu 应用凭证
                               │ (cli_xxxxxxxxxxxx — 来自 .env)
                               ▼
┌────────────────────────────────────────────────────────────┐
│ Feishu / Lark 开放平台 (可选)                               │
│  - Bitable (缺陷 / 项目 / 任务 表)                          │
│  - Wiki (QA 工单页面)                                       │
│  - Docs / Sheets (工单内嵌的电子表格)                       │
│  - IM (群聊通知 + 机器人交互)                                │
└────────────────────────────────────────────────────────────┘
```

> 若不启用 Feishu 集成（`.env` 中 `FEISHU_APP_ID` 留空），整套架构退化为左上+右上两层：
> 代理 → 看板 API → SQLite。看板照常运行，只是没有飞书同步/聊天通知/工单创建功能。

---

## 3. 核心要点

### 3.1 看板 API ≠ Feishu Bot

部署 ConvergenceKanban 后，`.97` 风格的服务器上会有三个 Python 进程（具体怎么跑见 `docs/SETUP.md`）：

| 服务 | 干什么 | 谁会调用它 |
|------|--------|-----------|
| **FastAPI 主服务** (`app.py`) | 看板的对外 HTTP API | **AI 代理** + Web UI |
| **feishu_sync.py** (可选) | 后台双向同步 SQLite ↔ Feishu Bitable | 自动跑，无人调用 |
| **feishu_bot.py** (可选) | 接 Feishu 群聊 + 推送通知 | 团队成员（在群里 @ 它） |

**AI 代理只调第一个 (FastAPI)**，不直接接触 bot 服务、不直接接触飞书。

### 3.2 为什么代理必须经过看板 API 而不能直接调 Feishu？

1. **SQLite 是单一事实源** — 缺陷状态、修复元数据、活动日志都在看板的 DB 里。
2. **Bot 治理在服务端强制执行** — 例如 bot 不能标 `done`、bot 报缺陷必须 `source=agent`、bot 不能改优先级。这些规则只能由看板服务校验。
3. **活动日志审计** — 每个写操作都按 `X-Kanban-User`（例如 `alice-claude`）记到 `activity_log` 表，便于回溯。
4. **双向同步保持一致性** — Feishu 那边的人工修改要回流到 DB；如果代理直接写 Feishu，看板就看不见。
5. **凭证安全** — Feishu 自建应用的 `app_secret` 只放在服务器 `.env` 里，绝不下发到代理或开发者笔记本。

### 3.3 一个凭证 → 多个服务身份

所有看板侧服务共享同一个 Feishu 自建应用的 `tenant_access_token`。所以**在 Feishu 里看到的"操作者"统一是这个应用**。但看板的 `activity_log` 表保留了真实的 `X-Kanban-User`，所以追溯到具体人/代理仍然可行：

| 在哪里看 | 能看到什么 |
|---------|-----------|
| Feishu Bitable 记录历史 | "应用名 修改了" |
| 看板 activity log (`/api/activity`) | `bob-codex 在 X 时间创建了 bug Y` |

---

## 4. 端到端举例：bob-codex 报一个缺陷

```
1. bob 在自己电脑上跑 Codex，让它报个缺陷。
   Codex 拿出 curl:

   curl -X POST <KANBAN_HOST>/api/bugs \
     -H 'X-Kanban-User: bob-codex' \
     -d '{
       "title": "...",
       "severity": "medium",
       "source": "agent",          ← 必须，否则进了 QA 表会变孤儿
       "reporter": "bob-codex",
       "project_id": "<project-id-here>"
     }'

2. 看板服务接到请求:
   - 校验 bob-codex 是已注册用户 (X-Kanban-User middleware)
   - 强制 source=agent (bot 治理规则: bot 不能创建 manual 缺陷)
   - 生成 display_id: RD-260509-NNN
   - 写入 SQLite (bugs 表) + activity_log (actor=bob-codex)
   - HTTP 返回 {id, display_id} 给 Codex

3. (~30 秒后, 仅当启用 Feishu 同步) feishu_sync.py 跑下一轮:
   - 发现本地有新缺陷 source=agent，updated_at > last_sync
   - 用 Feishu 应用的 tenant_access_token 调 Feishu Bitable API
   - 在对应表插入一条新记录 (Reporter=bob-codex 是文本)
   - 把 Feishu 给的 record_id 记到 SQLite

4. (可选) feishu_notify 在 5 秒去抖之后:
   - 通过 webhook 在团队群里推一张缺陷卡片
```

整个过程 bob 的代理只调用了**一次** HTTP 接口 (`/api/bugs`)，剩下的全是服务端自动完成。

---

## 5. 端到端举例：carol-claude 修完缺陷后开 QA 工单

```
1. carol-claude 把 bug BUG-260509-001 状态改为 fix_complete:

   curl -X PUT <KANBAN_HOST>/api/bugs/<id> \
     -H 'X-Kanban-User: carol-claude' \
     -d '{
       "status": "fix_complete",
       "fix_method": "在 commit abc123 修复了…",
       "fix_version": "main @ abc123 + 新构建",
       "fix_date": "2026-05-09"
     }'

2. carol-claude 在同一会话里发起 QA 工单（前提：部署已启用 Feishu wiki 集成）:

   curl -X POST <KANBAN_HOST>/api/qa-tickets \
     -H 'X-Kanban-User: carol-claude' \
     -d '{
       "task_type": "测试任务",
       "product": "rev-A 硬件",
       "task_name": "BUG-260509-001 短描述",
       "bug_id": "BUG-260509-001",       ← 写到工单 Bug ID 字段
       "version": "main @ abc123 + 新构建",
       "requirements": { ... }
     }'

3. 看板的 routes/qa_tickets.py 处理:
   - 用 Feishu 应用的凭证调 Feishu Wiki API
   - 复制 QA 团队的工单模板（KANBAN_QA_WIKI_TEMPLATE_NODE）
   - 把新节点放到配置的父页面（KANBAN_QA_WIKI_PARENT_NODE）
   - 拿到内嵌 sheet token，写入要求字段和 Bug ID
   - 重命名节点为 {YYYYMMDD}-{HH:MM}-{task_name}-{owner}
   - 返回 { wiki_url, node_token, title } 给 Codex

4. QA 团队在 Feishu wiki 看到新工单:
   - 标题直接显示 bug_id 关联
   - 等 QA 验证完，把缺陷状态从 fix_complete 推到 to_verify (周/月版本验证) 或直接 resolved
```

> 如果 `KANBAN_QA_WIKI_*` 这些环境变量没配置，`POST /api/qa-tickets` 会直接返回 503 + 提示信息。
> 这种部署下，代理就直接报缺陷，让人工去开工单。

---

## 6. 给团队成员的设置清单

如果你是带 AI 代理的开发者，把代理接到看板只需要三步：

1. **找管理员注册**你的代理身份（一次性）：
   ```bash
   # 由管理员执行，agent_name 用 {firstname}-{tool} 格式
   curl -X POST <KANBAN_HOST>/api/users \
     -H 'X-Kanban-User: <admin-name>' \
     -d '{"name": "yourname-yourtool", "display_name": "[Bot] yourname-yourtool", "role": "bot"}'
   ```

2. **在你项目的 `CLAUDE.md` 或 `AGENTS.md` 里加一行**指向实时指南：
   ```markdown
   ConvergenceKanban API guide:
   curl <KANBAN_HOST>/api/agent-guide?format=quickstart
   ```
   你的 AI 代理每次启动会自动读这个文件，看到指引后会按需拉取最新的接口说明。

3. **代理调用接口时设置环境变量**：
   ```bash
   export KANBAN_AGENT_NAME="yourname-yourtool"   # 必须 firstname-tool 格式
   ```

剩下的全交给代理。它会：
- 报缺陷自动带 `source: "agent"` (路由到 agent 缺陷表)
- 修完 bug 把状态改为 `fix_complete` 并填 `fix_method/version/date`
- (若启用) 需要 QA 测试时调 `POST /api/qa-tickets` 自动开工单到 Feishu wiki

---

## 7. 给 QA / PM 的视角

QA 和 PM 主要在 Feishu 那一侧操作（前提是启用了 Feishu 集成），看到的画面：

- **manual 缺陷表**：QA 自己手填的缺陷，编号 `BUG-YYMMDD-NNN`。
- **agent 缺陷表**：AI 代理自动报的缺陷，编号 `RD-YYMMDD-NNN`。
  - 两表 Status 字段选项一致：`To Do` / `In Progress` / `Fix Complete` / `To Verify` / `Done`。
  - QA 重点关注 `Fix Complete` 桶 — 代理已合入 MR，等 QA 用对应工单跑测。
- **工单 wiki**：QA 团队的工单总入口（可选功能）。
  - 子页面：AI 代理自动创建的工单都挂在这里，与 QA 手填工单分开。
  - 每个工单的内嵌 sheet 有结构化的 Bug ID，方便筛选关联缺陷。

操作角色分工：

| 状态 | 谁来推 | 含义 |
|------|--------|------|
| open / investigating / fixing | 开发者或代理 | 还在修 |
| **fix_complete** | 代理 / 开发者 | MR 已合入；QA 用工单做日常 spot-check |
| **to_verify** | QA 或 PM | 修复并入周/月版本，QA 做正式回归 |
| resolved | QA | 验证通过 |
| closed | QA / PM | 关闭 |
| wontfix | QA / PM | 不修 |

---

## 8. 故障定位速查

| 症状 | 大概率原因 |
|------|------------|
| `401 Unknown user 'X'` | `X-Kanban-User` 名字与 users 表不一致；找管理员注册 |
| `Connection refused` 或超时 | 看板服务没起来或网络不通 |
| 报了缺陷但 Feishu 没出现 | (若启用同步) 等 30 秒下一轮 sync；或看 sync 日志有没有报错；若没启用同步则属预期 |
| 报了缺陷但进了错的表 | 没带 `"source": "agent"`；服务端会强制改成 agent，但建议显式带上 |
| QA 工单创建后返回 503 | `KANBAN_QA_WIKI_*` 环境变量没配；这是可选功能，详见 `docs/SETUP.md` |
| QA 工单创建后 wiki 看不到 | Feishu wiki 空间没把应用加为成员；管理员需要去 Feishu 后台分享 |

---

**最后一段话**

整个架构的关键不是 bot 多聪明，而是 **"代理 → 看板 API → SQLite → Feishu" 这条链路的单向性**。代理不直接碰 Feishu，所以治理规则、审计日志、双向同步都能靠服务端兜住。团队成员只要给自己的代理放一行指引就行，剩下的服务端会处理。

Feishu 集成完全是可选的 — 单机或团队内部使用时，留空 `FEISHU_*` 环境变量即可，看板仍然能完整工作。

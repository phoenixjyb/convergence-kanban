# ConvergenceKanban — 系统架构

> 🇬🇧 English version: [`ARCHITECTURE.md`](ARCHITECTURE.md)

**目标读者：** 考虑贡献代码或自托管这个项目的开发者。
**阅读时间：** 约 10 分钟。
**范围：** 各部分如何组合在一起 —— 不是 API 参考。接口细节请看
[`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md)；部署见
[`SETUP.md`](SETUP.md)。

ConvergenceKanban 是一个不大的 FastAPI 应用（Python 代码总共约
9k 行），后端是单个 SQLite 文件，附带几个**可选**的 Feishu / Slack /
DingTalk 集成，这些集成通过 duck-type 的平行模块挂进来。代码里
真正有意思的地方集中在 bot 治理和双向同步层；其它都刻意写得朴素。

---

## 1. 全景图

```
                ┌───────────────────────────────────────────────────┐
                │ 浏览器 · curl · AI 代理 (Claude / Codex 等)        │
                └────────────────────────┬──────────────────────────┘
                                         │  HTTP  +  X-Kanban-User
                                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI 进程  (app.py，单 uvicorn worker)                            │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ 中间件                                                          │  │
│  │   CORS  →  RequireLoginMiddleware (helpers.py:155)             │  │
│  │           拒绝 X-Kanban-User 未知的写请求                       │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│  ┌───────────────────────────▼────────────────────────────────────┐  │
│  │ 22 个 route 模块 (routes/*.py)                                  │  │
│  │   projects · workstreams · tasks · bugs · blockers ·           │  │
│  │   comments · attachments · time_tracking · dependencies ·      │  │
│  │   recurring · templates · analytics · dashboard · bin ·        │  │
│  │   users · activity · alerts · export · auth · qa_tickets ·     │  │
│  │   agent_guide · sync_conflicts                                 │  │
│  │   — 只导入 db / models / helpers / notify                       │  │
│  └───────────────────────────┬────────────────────────────────────┘  │
│                              │                                       │
│  ┌───────────────────────────▼─────────────┐  ┌────────────────────┐ │
│  │ helpers.py  (TZ, get_actor, _is_bot,    │  │ models.py          │ │
│  │   _require_human, log_activity,         │  │ 仅 Pydantic 请求体  │ │
│  │   generate_bug_display_id,              │  │                    │ │
│  │   build_person_map, ...)                │  └────────────────────┘ │
│  └───────────────────────────┬─────────────┘                         │
│                              │                                       │
│  ┌───────────────────────────▼────────────────────────────────────┐  │
│  │ db.py — SQLite WAL，幂等 init_db()，17 张表                     │  │
│  │         data/kanban.db 是单一事实源                             │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ notify.py — 分发器：把事件并行扇出到 N 个聊天后端                │  │
│  │   ├─ feishu_notify.py    (FEISHU_WEBHOOK_URL)                  │  │
│  │   ├─ slack_notify.py     (SLACK_WEBHOOK_URL)                   │  │
│  │   └─ dingtalk_notify.py  (DINGTALK_WEBHOOK_URL)                │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘

       ── 可选 sidecar 进程 (独立的 uvicorn / 脚本) ──

┌─────────────────────────────┐   ┌──────────────────────────────────┐
│ feishu_sync.py              │   │ feishu_bot.py                    │
│   30 s 轮询                  │   │   WebSocket 长连接                │
│   SQLite ⇄ Bitable          │   │   @bot 指令                       │
│   per-field 冲突检测         │   │   双语应答                        │
└─────────────────────────────┘   └──────────────────────────────────┘
```

虚线以下整片都关掉时，看板照样能用 —— `.env` 留空 `FEISHU_APP_ID`，
你就有了一个纯 SQLite + REST + Web UI 的本地看板。

---

## 2. 分层结构

### 2.1 入口 —— `app.py`

`app.py:28-46` 就是全部的接线代码。它干四件事：

1. 创建 `FastAPI` 实例，挂 `CORSMiddleware` 和 `RequireLoginMiddleware`。
2. 把 `/static` 挂成原生 HTML/JS/CSS 前端。
3. 遍历 22 个 route 模块，对每个调用 `app.include_router(...)`。
4. 注册 `init_db()` 为启动钩子。

明显没有的：依赖注入容器、插件加载器、服务定位器。每个 route 模块
都在 `app.py` 顶部按名字 import 进来。新增一个功能模块的流程：

1. 写 `routes/myfeature.py`，里面有 `router = APIRouter(prefix="/api", tags=["myfeature"])`。
2. 在 `app.py:19-24` 的 import 元组里加上 `myfeature`。
3. 在 `app.py:40-45` 的 `include_router` 元组里再加一次。

### 2.2 Routes —— `routes/*.py`

一个模块对应一个功能域，**模块之间不互相 import**。这条规则是社会规范
而不是机制 —— 但约定是 "routes 只能 import `db` / `models` / `helpers`
/ `notify`"。如果你发现想从另一个 route 里取东西，那个共享逻辑应该搬到
`helpers.py`。

每个 route 文件长得都差不多（典型例子见 `routes/tasks.py:14-80`）：

```python
router = APIRouter(prefix="/api", tags=["tasks"])

@router.post("/tasks")
def create_task(t: TaskCreate, request: Request):
    actor = get_actor(request)                      # X-Kanban-User
    with get_db() as conn:
        _require_human(conn, actor, "...")          # bot 治理
        conn.execute("INSERT ...", (...))
        log_activity(conn, "task", tid, "created",  # 审计日志
                     actor=actor, detail=...)
        notify.notify_task_created(...)             # 通知扇出
        return {"id": tid}
```

注册顺序在一处比较敏感：**字面路径必须在带参路径之前注册**。
例如 `/api/projects/reorder`（字面）必须在 `/api/projects/{pid}` 之前
（`routes/projects.py:52` 在后面的 handler 之前），否则 FastAPI 会把
`reorder` 当成 `{pid}` 的值。

### 2.3 共享工具 —— `helpers.py` 和 `db.py`

`helpers.py`（180 行）是唯一被所有 route 共享的模块。它管：

- **时区** —— `helpers.py:13` 的 `TZ = timezone(timedelta(hours=8))`。
  DB 里所有时间戳都是经 `now_iso()` 写入的 UTC+8 字符串。
  Slack 和 Feishu 通知器都各自维护了同一个常量的副本；如果你要 fork
  到非上海时区的部署，全局搜索 `TZ = timezone(timedelta(hours=8))`
  改掉即可。
- **Bot 治理** —— `_is_bot()` / `_require_human()`（见 §4）。
- **Display ID** —— `generate_bug_display_id()`（见 §7）。
- **审计日志** —— `log_activity()` 往 `activity_log` 写一条记录。
- **登录中间件** —— `RequireLoginMiddleware`（`helpers.py:155-180`）
  在 `X-Kanban-User` 缺失或未知时拒绝 POST/PUT/DELETE。

`db.py` 提供一个上下文管理的 SQLite 连接，以及一个**幂等的
`init_db()`**，把项目历史上所有 migration 一次性兜底处理。没有 Alembic，
也没有 migration 版本表 —— 这个函数会：

1. 对每张表跑 `CREATE TABLE IF NOT EXISTS`。
2. 对每张表探测新加的列，逐个 `ALTER TABLE ADD COLUMN`（参见
   `db.py:154-185, 318-348`）。
3. 对于 CHECK 约束的变化（SQLite 不能 `ALTER`），方法是用一个已知的
   新枚举值 INSERT 探测；如果失败就走"建新表、复制数据、删旧表、
   重命名"那一套。tasks 表见 `db.py:288-315`，bugs 表见
   `db.py:407-458`。

取舍：只有改 schema 那次冷启动会慢一点，但你**永远不会**卡在 migration
中间某一版。新加的列下次 `init_db()` 跑完自动就有了。

### 2.4 可选集成 —— `feishu_*.py`、`slack_notify.py`、`dingtalk_notify.py`

这些都在仓库根目录，与 `app.py` 平级。没有任何 route 模块 import 它们；
通知后端由 `notify.py` 懒加载，`feishu_sync.py` / `feishu_bot.py`
则是独立进程（通常用 Docker Compose 的 profile 启动 —— 见
`docker-compose.yml`）。

不变量：**任何可选集成都不在 API 调用的关键路径上。** Slack 挂了不会
拖垮 `POST /api/bugs`。具体怎么实现这一点见 §5。

---

## 3. 软删除 + 审计日志

每张面向用户的实体表都有 `deleted_at TEXT` 列。route 层从不真正 DELETE
行，模式是：

- `DELETE /api/tasks/{tid}` 把 `deleted_at = now_iso()` 写进去。
- 所有列表查询都带 `WHERE deleted_at IS NULL`。
- **回收站** route（`routes/bin.py`）按时间戳列出已删除项并支持还原。
- 真正的级联删除靠 SQL 层的 `FOREIGN KEY ... ON DELETE CASCADE`，
  仅在永久清空回收站这种少数场景下触发。

软删除跟 `activity_log` 表（`db.py:138-146`）配合：

```sql
CREATE TABLE activity_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id   TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT 'system',
    action      TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

每个有写动作的 route，都会在**同一个事务里**调一次
`log_activity(conn, entity_type, entity_id, action, actor=actor,
detail=...)`。`get_db()` 是退出时 commit、异常时 rollback 的上下文
管理器（`db.py:18-32`），所以审计记录永远不会跟它对应的写动作走散。
`routes/activity.py` 把这张表暴露成分页的活动流。

这正是为什么"代理在时间 T 做了 X"能从一张表里直接答出来 —— 哪怕之后
Feishu 同步已经把那条 bug 的 `updated_at` 改了无数次。

---

## 4. Bot 治理

系统在 `users.role` 列（`db.py:43`）区分**人类**和**机器人**。
机器人权限更小，由 `helpers.py` 里的两个函数在写入时强制：

### 4.1 身份识别

每个请求都带 `X-Kanban-User: <name>`。`RequireLoginMiddleware`
（`helpers.py:155-180`）对未知 actor 的写请求直接 401。GET 请求不强制带
header —— 读流量不鉴权。

`helpers.get_actor()`（`helpers.py:49`）从 header 取出 actor 名。
route 内部用 `helpers._is_bot(conn, actor)`（`helpers.py:54-64`）
做用户查询：

- `actor == "system"` → 信任（Web UI 未登录时的默认，以及内部后台任务）。
- users 表里 `role='human'` → 人类。
- users 表里 `role='bot'` → 机器人。
- users 表里**没有** → 当成机器人。这是**fail-safe 默认**；
  RequireLoginMiddleware 通常会先把未知用户的写请求挡掉，所以这条分支
  只会在 `helpers.py:146-152` 的几条登录豁免路径上生效。

### 4.2 `_require_human` 门禁

`_require_human(conn, actor, action, entity_type, entity_id)`
（`helpers.py:67-81`）在 actor 是机器人时抛 403，并且在抛错**之前**
先用 `action='rejected'` 把这次尝试写进审计日志。所以审计流不仅记录
机器人成功做了什么，也记录它**尝试**做了什么。

route 里这样调：

```python
# routes/projects.py:43
_require_human(conn, actor, "create projects")
```

这种方式落实的限制：

- 不能把任务标成 `done` / `abandoned`（`routes/tasks.py` 里）。
- 不能删除 project / workstream / task / bug（每个 route 一处调用）。
- 不能创建或修改 project / workstream。
- 不能改 workstream 优先级。
- 不能改用户角色。

### 4.3 Bug 创建策略

Bug 分两路（`source='manual'` vs `source='agent'`），就是为了让 QA 团队
人工梳理的那张 bug 表干净。`routes/bugs.py:103-104` 不直接拒绝机器人
创建 bug，而是**静默把 `source` 改写成 `agent`**：

```python
if _is_bot(conn, actor) and b.source != "agent":
    b.source = "agent"
```

这是整套代码里**唯一**一处会无声重写机器人输入的地方。理由是：
机器人不小心默认到 `source='manual'`，就会污染人类的 bug 表，事后清理
比当场把它放对位置麻烦多了。

机器人**可以**改任意 bug，不论 source —— 限制只在创建时的 `source`
字段上。

---

## 5. notify.py 分发器模式

`notify.py`（89 行）是这套代码处理可选集成最干净的样板。它对外暴露一组
小 API（`notify_task_created`、`notify_bug_created`、…），把每次调用
扇出到所有"能 import 进来"的聊天后端：

```python
# notify.py:25-43
_BACKENDS: list = []

try:
    import feishu_notify
    _BACKENDS.append(feishu_notify)
except ImportError:
    pass

try:
    import slack_notify
    _BACKENDS.append(slack_notify)
except ImportError:
    pass

try:
    import dingtalk_notify
    _BACKENDS.append(dingtalk_notify)
except ImportError:
    pass
```

每个调用点都走 `_dispatch()`（`notify.py:46-58`）：

```python
for backend in _BACKENDS:
    fn = getattr(backend, method_name, None)
    if fn is None:
        continue
    try:
        fn(*args, **kwargs)
    except Exception as e:
        log.warning("notify backend %s.%s raised %s (swallowed)", ...)
```

**为什么是平行模块而不是基类？** 三个理由：

1. **失败模式各自独立。** 每个后端的 webhook 格式、debounce 计时、
   错误处理都完全不一样。Slack 挂了跟 Feishu 限流长得没有任何相似处。
   抽公共基类只会强迫一边迁就另一边。
2. **`method_name` 的鸭子类型。** 后端可以只支持一部分通知类型。
   `getattr(..., None)` 静默跳过缺失的方法，所以再加第四个"只关心
   bug"的后端是零成本的。
3. **可选安装。** 每个后端模块都可独立跳过。哪天 `feishu_notify.py`
   长出对 `lark-oapi` 的硬依赖，删掉它也只关掉那一路通知 ——
   `slack_notify.py` 和 `dingtalk_notify.py` 还能正常加载。

每个后端都自带 debounce：事件先缓 ~5 秒再合成一张卡片或一条消息
发出去（`slack_notify.py:36-39`、`feishu_notify.py:19-22`）。所以批量
操作每个平台只会收到一条通知，不是 N 条。

---

## 6. Feishu 双向同步

`feishu_sync.py`（~2300 行，单文件）是一个独立的 Python 脚本，跑在
自己的进程里 —— 通常 `docker compose --profile feishu up`。它**不**
import `app.py`；直接打开同一个 SQLite 文件。文件头的 docstring
在 `feishu_sync.py:1-15`。

**模型：** SQLite 是唯一事实源。Feishu Bitable 是一个"人也能改"的
投影，人工编辑会在下一轮轮询里被拉回 SQLite。

```
每 30 秒：
  从每张 Bitable 拉更新过的行
  ─────────────────────────────────────────────
  对每条远端记录：
    if 本地没有：
      INSERT 到 SQLite
    elif local.updated_at >= last_sync 且 remote.updated_at >= last_sync：
      # 上次同步以来两边都改过 → 按字段记冲突
      _record_conflicts(...)
    elif 远端更新：
      把本地 UPDATE 成远端的值
    else：
      把远端 UPDATE 成本地的值
```

`last_sync_ts_*` 这张映射存在 `data/feishu_sync_state.json`
（`feishu_sync.py:59`）。冲突探测器（`feishu_sync.py:1134-1151`）
把每个分歧字段独立写入 `sync_conflicts` 表（`db.py:268-284`），一行
一字段。人工解决冲突走 `routes/sync_conflicts.py` 和分析页。

值得注意的几个结果：

- 看板 API 从不阻塞等 Feishu。把变更推到 Feishu 是下一轮 30s 轮询的事，
  不是 API 调用期间。
- `feishu_sync.py` 离线时看板照样接受写入；Feishu 那边只是落后，恢复
  同步后会追上。
- 冲突的粒度是**字段**，不是行。QA 在 Feishu 改某 bug 的 "severity"
  同时代理在看板改它的 "status"，**不会**产生冲突 —— 只有同一字段
  两边都改才算。

Feishu 鉴权和 HTTP 重试 / token 缓存见 `feishu_sync.py:96-117`。

---

## 7. Display ID

Bug 同时有两个 ID：内部 UUID（`bugs.id`，`uuid.uuid4().hex[:12]`）
和人类可读的 `display_id`，形如 `BUG-260520-001` 或 `RD-260520-001`。
格式是 `<前缀>-<YYMMDD>-<NNN>`，其中：

- `BUG-` = 人工创建（QA 团队）。
- `RD-` = 代理创建（`source='agent'`）。
- `NNN` 每天按前缀重置。

生成逻辑在 `helpers.py:20-46`。本质上就是按当天前缀查"最大值 + 1"：

```python
pattern = f"{prefix}-{yymmdd}-%"
row = conn.execute(
    "SELECT display_id FROM bugs WHERE display_id LIKE ? "
    "ORDER BY display_id DESC LIMIT 1", (pattern,)
).fetchone()
```

为什么要这么折腾？两个原因：

1. **在 Feishu 里讨论 bug。** QA 在群里说 "BUG-260520-007 还有问题"
   比贴一串 12 位的 hex UUID 清楚太多。display_id 作为纯文本列
   流到 Feishu Bitable。
2. **一眼区分两路 bug。** `BUG-` vs `RD-` 立刻就能看出来这个 bug 是
   人提的还是代理报的，根本不用过滤 `source`。

注意 2026-05-09 之前的格式是 `MMDD`（4 位）。老的 ID 保持原样不动；
新的 ID 用 `YYMMDD`（6 位）。docstring 见 `helpers.py:20-29`。

---

## 8. 测试架构

`tests/conftest.py`（56 行）把整个测试套件需要的环境一次搞定：

```python
# tests/conftest.py:9-11
_tmpdir = tempfile.mkdtemp(prefix="kanban_test_")
os.environ["KANBAN_DATA_DIR"] = _tmpdir
os.environ["FEISHU_WEBHOOK_URL"] = ""  # 关掉通知
```

关键属性：

- **每个 session 一个隔离的 DB。** `KANBAN_DATA_DIR` 在 `db.py` 被 import
  **之前**就被设成一个新临时目录，所以 `data/kanban.db` 变成 session 级
  的 SQLite 文件。`init_db()` 只跑一次（`conftest.py:19-24`），所有测试
  共用同一套表。
- **无网络。** `FEISHU_WEBHOOK_URL=""` 让 Feishu 通知器直接 no-op；
  Slack 和 DingTalk 沿用同一个"没设 URL 就 no-op"的模式。`notify.py`
  仍然把后端 import 进来，但 POST 函数本身啥都不发。
- **两个治理测试用 fixture。** `human_headers` 和 `bot_headers`
  （`conftest.py:46-55`）预先种入一个 `test-human` 和一个 `test-bot`
  用户，让治理代码不需要每个测试单独建用户就能跑。
- **FastAPI TestClient。** `client()` fixture（`conftest.py:27-30`）
  返回 `TestClient(app)` —— 真实的 ASGI 应用，没有 mock。

整个套件共 239 个测试用例，本地笔记本能在 5 秒内跑完。最大的两个文件
是 `tests/test_api_basic.py`（146 个测试，覆盖面广）和
`tests/test_bot_governance.py` / `tests/test_bugs.py`（聚焦两个最容易
出 bug 的区域）。

跑测试：

```bash
pip install -r requirements-dev.txt
pytest tests/ -x -q
```

---

## 9. 这份文档**没有**讲的

- **接口清单。** 实时版本在 `GET /api/agent-guide?format=quickstart`。
  详细文字版见 [`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md)。
- **Feishu 应用 scope、token、wiki 节点配置。** 见
  [`SETUP.md`](SETUP.md)。
- **这个项目为什么要存在。** 见 [`WHY_THIS_PROJECT.md`](WHY_THIS_PROJECT.md)。
- **代理交互的完整叙事。** 见
  [`AGENT_ARCHITECTURE_zh.md`](AGENT_ARCHITECTURE_zh.md)。

如果这份文档跟代码对不上，以代码为准 —— 欢迎提 issue 或 PR。

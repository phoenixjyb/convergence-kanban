# ConvergenceKanban — System Architecture

> 🇨🇳 中文版本请见 [`ARCHITECTURE_zh.md`](ARCHITECTURE_zh.md)

**Audience:** developers considering contributing or self-hosting.
**Reading time:** ~10 minutes.
**Scope:** how the pieces fit together — not an API reference. For
endpoint-level details see [`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md);
for setup see [`SETUP.md`](SETUP.md).

ConvergenceKanban is a small FastAPI app (~9k LOC of Python total) backed
by a single SQLite file, with a handful of *optional* Feishu / Slack /
DingTalk integrations that are wired in via duck-typed sibling modules.
Most of the surprise lives in the bot-governance and two-way-sync
layers; everything else is intentionally boring.

---

## 1. Big picture

```
                ┌───────────────────────────────────────────────────┐
                │ Browser  ·  curl  ·  AI agent (Claude / Codex)    │
                └────────────────────────┬──────────────────────────┘
                                         │  HTTP  +  X-Kanban-User
                                         ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI process  (app.py, single uvicorn worker)                    │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ Middleware                                                     │  │
│  │   CORS  →  RequireLoginMiddleware (helpers.py:155)             │  │
│  │           rejects writes from unknown X-Kanban-User             │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│  ┌───────────────────────────▼────────────────────────────────────┐  │
│  │ 22 route modules (routes/*.py)                                 │  │
│  │   projects · workstreams · tasks · bugs · blockers ·           │  │
│  │   comments · attachments · time_tracking · dependencies ·      │  │
│  │   recurring · templates · analytics · dashboard · bin ·        │  │
│  │   users · activity · alerts · export · auth · qa_tickets ·     │  │
│  │   agent_guide · sync_conflicts                                 │  │
│  │   — each imports only db / models / helpers / notify           │  │
│  └───────────────────────────┬────────────────────────────────────┘  │
│                              │                                       │
│  ┌───────────────────────────▼─────────────┐  ┌────────────────────┐ │
│  │ helpers.py  (TZ, get_actor, _is_bot,    │  │ models.py          │ │
│  │   _require_human, log_activity,         │  │ Pydantic request   │ │
│  │   generate_bug_display_id,              │  │ shapes only        │ │
│  │   build_person_map, ...)                │  └────────────────────┘ │
│  └───────────────────────────┬─────────────┘                         │
│                              │                                       │
│  ┌───────────────────────────▼────────────────────────────────────┐  │
│  │ db.py — SQLite WAL, idempotent init_db(), 17 tables            │  │
│  │         data/kanban.db is the single source of truth           │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │ notify.py — dispatcher: fan-out to N parallel chat backends    │  │
│  │   ├─ feishu_notify.py    (FEISHU_WEBHOOK_URL)                  │  │
│  │   ├─ slack_notify.py     (SLACK_WEBHOOK_URL)                   │  │
│  │   └─ dingtalk_notify.py  (DINGTALK_WEBHOOK_URL)                │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘

       ── Optional sidecar processes (separate uvicorn / scripts) ──

┌─────────────────────────────┐   ┌──────────────────────────────────┐
│ feishu_sync.py              │   │ feishu_bot.py                    │
│   30 s poll loop            │   │   long-poll WebSocket            │
│   SQLite ⇄ Bitable          │   │   @bot commands                  │
│   per-field conflict detect │   │   bilingual responses            │
└─────────────────────────────┘   └──────────────────────────────────┘
```

The kanban is genuinely usable with everything below the dashed line
turned off — leave `FEISHU_APP_ID` blank in `.env` and you get a plain
SQLite + REST kanban with a web UI.

---

## 2. Layered structure

### 2.1 Entry point — `app.py`

`app.py:28-46` is the whole wiring. It does four things:

1. Construct a `FastAPI` instance and attach `CORSMiddleware` and
   `RequireLoginMiddleware`.
2. Mount `/static` for the vanilla HTML/JS/CSS frontend.
3. Loop over 22 route modules and call `app.include_router(...)` on each.
4. Register `init_db()` as the startup hook.

Notably absent: there is no dependency-injection container, no plugin
loader, no service locator. Every route module is imported by name at
the top of `app.py`. Adding a new feature area means:

1. Create `routes/myfeature.py` with `router = APIRouter(prefix="/api", tags=["myfeature"])`.
2. Add `myfeature` to the import tuple at `app.py:19-24`.
3. Add it again to the `include_router` tuple at `app.py:40-45`.

### 2.2 Routes — `routes/*.py`

One module per feature area, no cross-route imports. This is enforced
socially, not mechanically — but the rule is "routes import only from
`db`, `models`, `helpers`, and `notify`." If you find yourself wanting
to import another route module, the shared helper belongs in
`helpers.py` instead.

Each route file follows the same shape (see `routes/tasks.py:14-80`
for a canonical example):

```python
router = APIRouter(prefix="/api", tags=["tasks"])

@router.post("/tasks")
def create_task(t: TaskCreate, request: Request):
    actor = get_actor(request)                      # X-Kanban-User
    with get_db() as conn:
        _require_human(conn, actor, "...")          # bot governance
        conn.execute("INSERT ...", (...))
        log_activity(conn, "task", tid, "created",  # audit trail
                     actor=actor, detail=...)
        notify.notify_task_created(...)             # fan-out
        return {"id": tid}
```

Route order matters in one place: literal paths must be registered
before parametrised ones. For example
`/api/projects/reorder` (literal) is declared *before*
`/api/projects/{pid}` (`routes/projects.py:52` vs subsequent handlers)
or FastAPI will route `reorder` into `{pid}`.

### 2.3 Shared utilities — `helpers.py` and `db.py`

`helpers.py` (180 lines) is the only module routes share. It owns:

- **Timezone** — `TZ = timezone(timedelta(hours=8))` at
  `helpers.py:13`. All timestamps in the DB are UTC+8 strings via
  `now_iso()`. Slack and Feishu notifiers each carry their own copy of
  the same constant; if you fork for a non-Shanghai deployment, search
  for `TZ = timezone(timedelta(hours=8))`.
- **Bot governance** — `_is_bot()` / `_require_human()` (see §4).
- **Display IDs** — `generate_bug_display_id()` (see §7).
- **Audit log** — `log_activity()` writes one row to `activity_log`.
- **Login middleware** — `RequireLoginMiddleware` (`helpers.py:155-180`)
  rejects POST/PUT/DELETE if `X-Kanban-User` is missing or unknown.

`db.py` is a context-managed SQLite connection plus an
**idempotent `init_db()`** that handles every migration the project has
ever needed. There is no Alembic, no migration version table — instead
the function:

1. Runs `CREATE TABLE IF NOT EXISTS` for every table.
2. Probes each table for newer columns and `ALTER TABLE ADD COLUMN`
   one at a time (see `db.py:154-185, 318-348`).
3. For CHECK-constraint changes (which SQLite can't `ALTER`), it
   probes by attempting an insert with a known-new value, and if that
   fails it does the "create new table, copy, drop old, rename"
   dance. See `db.py:288-315` (tasks) and `db.py:407-458` (bugs).

The trade-off: cold starts are slow only on schema changes, and you
can never accidentally end up "between" migration versions. New columns
just appear next time `init_db()` runs.

### 2.4 Optional integrations — `feishu_*.py`, `slack_notify.py`, `dingtalk_notify.py`

These all sit alongside `app.py` at the repo root. None of them are
imported by routes; instead, `notify.py` lazy-imports the notification
backends, and `feishu_sync.py` / `feishu_bot.py` are run as separate
processes (typically via Docker Compose profiles — see
`docker-compose.yml`).

The invariant: **no optional integration is on the critical path of an
API call.** A Slack outage cannot break `POST /api/bugs`. See §5 for
how the dispatcher enforces this.

---

## 3. Soft-delete + audit log

Every user-visible entity table has a `deleted_at TEXT` column. There
are no hard deletes from the route layer. The pattern is:

- `DELETE /api/tasks/{tid}` sets `deleted_at = now_iso()`.
- Every list query has `WHERE deleted_at IS NULL`.
- The **bin** route (`routes/bin.py`) lists deleted entities by
  timestamp and supports restore.
- Cascades happen at the SQL level via `FOREIGN KEY ... ON DELETE
  CASCADE` for *true* deletes (rare; usually used when permanently
  emptying the bin).

The soft-delete is paired with the `activity_log` table
(`db.py:138-146`):

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

Every route that mutates state calls `log_activity(conn, entity_type,
entity_id, action, actor=actor, detail=...)` in the same transaction
as the write. Because `get_db()` is a context manager that commits on
exit and rolls back on exception (`db.py:18-32`), an audit entry can
never be orphaned from its mutation. `routes/activity.py` exposes this
as a paginated feed.

This is what makes "agent did X at time T" answerable from a single
table even when Feishu sync has rewritten the bug's `updated_at` field
many times since.

---

## 4. Bot governance

The system distinguishes **humans** and **bots** at the `users.role`
column (`db.py:43`). Bots get fewer rights, enforced at write time by
two helpers in `helpers.py`:

### 4.1 Identity resolution

Every request carries `X-Kanban-User: <name>`. `RequireLoginMiddleware`
(`helpers.py:155-180`) blocks mutations from unknown actors with 401.
For GETs, the header is optional — read traffic is unauthenticated.

`helpers.get_actor()` (`helpers.py:49`) extracts the header. Inside a
route, `helpers._is_bot(conn, actor)` (`helpers.py:54-64`) looks up the
user:

- `actor == "system"` → trusted (used by web UI when not logged in, and
  by internal background jobs).
- known user with `role='human'` → human.
- known user with `role='bot'` → bot.
- unknown user → treated as bot. This is the **fail-safe default**;
  RequireLoginMiddleware would normally reject unknown users on
  mutations, so this branch only fires for the few login-exempt paths
  in `helpers.py:146-152`.

### 4.2 The `_require_human` gate

`_require_human(conn, actor, action, entity_type, entity_id)`
(`helpers.py:67-81`) raises 403 if the actor is a bot, and logs the
attempted action with `action='rejected'` *before* raising. The audit
trail therefore records what bots tried to do, not just what they
succeeded at.

Routes call it like this:

```python
# routes/projects.py:43
_require_human(conn, actor, "create projects")
```

Restrictions enforced this way:

- Can't mark tasks `done` / `abandoned` (handled in
  `routes/tasks.py`).
- Can't delete projects / workstreams / tasks / bugs (one call per
  route).
- Can't create or modify projects / workstreams.
- Can't change workstream priorities.
- Can't change user roles.

### 4.3 Bug-creation policy

Bugs have two streams (`source='manual'` vs `source='agent'`) so that
the QA team's hand-curated bug list stays clean. Rather than reject
bot bug-creates, `routes/bugs.py:103-104` *silently coerces* `source`
to `agent`:

```python
if _is_bot(conn, actor) and b.source != "agent":
    b.source = "agent"
```

This is the only place in the codebase where a bot's input is silently
rewritten. The reasoning: a bot accidentally defaulting to
`source='manual'` would pollute the human bug table, which is harder
to clean up than just routing it correctly in the first place.

Bots *can* modify any bug regardless of source — the restriction is
only on the create-time `source` field.

---

## 5. The notify.py dispatcher pattern

`notify.py` (89 lines) is the cleanest example of how this codebase
handles optional integrations. It exposes a small public API
(`notify_task_created`, `notify_bug_created`, ...) and fans every call
out to whichever chat backends happen to be loadable:

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

Each call site goes through `_dispatch()` (`notify.py:46-58`):

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

**Why parallel modules and not a base class?** Three reasons:

1. **Independent failure modes.** Each backend's webhook format,
   debounce timer, and error handling are completely different. A
   Slack outage looks nothing like a Feishu rate-limit. Sharing a
   class would force one to dictate the other.
2. **Duck typing on `method_name`.** Backends can support a subset of
   notification types. `getattr(..., None)` skips missing methods
   silently, so adding a fourth backend that only cares about bugs is
   trivial.
3. **Optional installs.** Each backend module is independently
   skippable. If `feishu_notify.py` ever grew a hard dependency on
   `lark-oapi`, dropping it would only disable that one backend —
   `slack_notify.py` and `dingtalk_notify.py` still load.

Each backend has its own debounce: events are buffered for ~5 s and
flushed as a single card or message (`slack_notify.py:36-39`,
`feishu_notify.py:19-22`). Bulk operations therefore produce one
notification per platform, not N.

---

## 6. Feishu two-way sync

`feishu_sync.py` (~2300 lines, one file) is a standalone Python script
that runs in its own process — usually `docker compose --profile feishu
up`. It does *not* import `app.py`; it talks to the same SQLite file
directly. The header docstring lives at `feishu_sync.py:1-15`.

**Model:** SQLite is the single source of truth. Feishu Bitable is a
projection that humans can also edit; edits are pulled back into
SQLite on each poll.

```
every 30 s:
  fetch updated rows from each Bitable
  ─────────────────────────────────────────────
  for each remote row:
    if local missing:
      INSERT into SQLite
    elif local.updated_at >= last_sync and remote.updated_at >= last_sync:
      # both sides changed since last sync → record per-field conflict
      _record_conflicts(...)
    elif remote newer:
      UPDATE SQLite from remote
    else:
      UPDATE remote from SQLite
```

The `last_sync_ts_*` map lives in `data/feishu_sync_state.json`
(`feishu_sync.py:59`). Per-field conflict detection writes one row per
diverged field to the `sync_conflicts` table (`db.py:268-284`, conflict
recorder at `feishu_sync.py:1134-1151`). Humans resolve those via
`routes/sync_conflicts.py` and the analytics page.

Notable consequences:

- The kanban API never blocks on Feishu. A push to Feishu happens
  on the next 30 s tick, not during the API call.
- If `feishu_sync.py` is offline, the kanban keeps accepting writes;
  Feishu just falls behind until sync resumes.
- Conflicts are per-*field*, not per-row. A QA editing the bug's
  "severity" in Feishu while an agent updates the "status" in the
  kanban produces no conflict — only same-field divergence does.

For Feishu auth and HTTP retry / token caching, see
`feishu_sync.py:96-117`.

---

## 7. Display IDs

Bugs have two IDs: an internal UUID (`bugs.id`, `uuid.uuid4().hex[:12]`)
and a human-readable `display_id` like `BUG-260520-001` or
`RD-260520-001`. The format is `<prefix>-<YYMMDD>-<NNN>` where:

- `BUG-` = manually created (QA team).
- `RD-` = agent-created (`source='agent'`).
- `NNN` resets daily, per prefix.

Generation is in `helpers.py:20-46`. It's a simple "max + 1" lookup
scoped to today's prefix pattern:

```python
pattern = f"{prefix}-{yymmdd}-%"
row = conn.execute(
    "SELECT display_id FROM bugs WHERE display_id LIKE ? "
    "ORDER BY display_id DESC LIMIT 1", (pattern,)
).fetchone()
```

Why bother? Two reasons:

1. **Talking about bugs in Feishu.** A QA tester saying "BUG-260520-007
   is still broken" in chat is dramatically clearer than pasting a
   12-character hex UUID. The display_id flows through Feishu Bitable
   as a plain text column.
2. **Stream separation at a glance.** `BUG-` vs `RD-` makes it
   immediately obvious whether a bug came from a human or an agent,
   without filtering by `source`.

Note the format used to be `MMDD` (4 digits) prior to 2026-05-09. Old
IDs in that format are left in place; new IDs use `YYMMDD`. See the
docstring at `helpers.py:20-29`.

---

## 8. Test architecture

`tests/conftest.py` (56 lines) sets up the entire suite:

```python
# tests/conftest.py:9-11
_tmpdir = tempfile.mkdtemp(prefix="kanban_test_")
os.environ["KANBAN_DATA_DIR"] = _tmpdir
os.environ["FEISHU_WEBHOOK_URL"] = ""  # disable notifications
```

Key properties:

- **Isolated DB per session.** `KANBAN_DATA_DIR` is set to a fresh
  temp directory *before* `db.py` is imported, so `data/kanban.db`
  becomes a per-session SQLite file. `init_db()` runs once
  (`conftest.py:19-24`) and tables are reused across tests.
- **No network.** `FEISHU_WEBHOOK_URL=""` disables the Feishu notifier;
  Slack/DingTalk inherit the same "no URL → no-op" pattern. `notify.py`
  still loads the backends but their POST functions short-circuit.
- **Two fixtures for governance tests.** `human_headers` and
  `bot_headers` (`conftest.py:46-55`) pre-seed a `test-human` and
  `test-bot` user so governance code paths can be exercised without
  per-test user setup.
- **FastAPI TestClient.** `client()` fixture (`conftest.py:27-30`)
  returns a `TestClient(app)` — the real ASGI app, no mocks.

The suite covers 239 tests and finishes in <5 s on a laptop. Largest
files are `tests/test_api_basic.py` (146 tests, broad coverage) and
`tests/test_bot_governance.py` / `tests/test_bugs.py` (focused on the
two trickier areas).

Running tests:

```bash
pip install -r requirements-dev.txt
pytest tests/ -x -q
```

---

## 9. What's *not* in this doc

- **Endpoint catalogue.** The live one is at
  `GET /api/agent-guide?format=quickstart`. For the long form see
  [`AGENT_INSTRUCTIONS.md`](AGENT_INSTRUCTIONS.md).
- **Feishu app scopes, tokens, wiki node setup.** See
  [`SETUP.md`](SETUP.md).
- **Why this project exists at all.** See
  [`WHY_THIS_PROJECT.md`](WHY_THIS_PROJECT.md).
- **Agent integration narrative.** See
  [`AGENT_ARCHITECTURE_zh.md`](AGENT_ARCHITECTURE_zh.md) (currently
  Chinese-only; English version tracked as future work).

If something in this doc no longer matches the code, the code wins —
file an issue or send a PR.

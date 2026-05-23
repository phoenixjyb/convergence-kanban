# ConvergenceKanban — Claude Code Instructions

This file is auto-read by Claude Code when you open this repo. It applies to
the **kanban service itself**, not to projects that consume the kanban as
their own AI-agent backend.

If you're an AI agent in *another* repo and want to interact with this
kanban (file bugs, submit QA tickets, etc.), fetch the live integration
guide:

```bash
curl <KANBAN_HOST>/api/agent-guide?format=quickstart
```

(`<KANBAN_HOST>` is wherever ConvergenceKanban is deployed — e.g. `http://localhost:8666`.)

## Project Overview

FastAPI + SQLite bilingual (EN / ZH) kanban with optional Feishu / Lark Bitable two-way sync.

- Web UI: `http://localhost:8666` (configurable via `PORT`)
- API base: `http://localhost:8666/api`
- Repo: `phoenixjyb/convergence-kanban` — `main` = stable, `dev` = active development
- License: MIT

## Key files

| File | Purpose |
|------|---------|
| `app.py` | Entry point — creates FastAPI app, mounts routers |
| `db.py` | SQLite init, migrations, `get_db()` context manager |
| `models.py` | Pydantic request models |
| `helpers.py` | Shared utilities: `now_iso`, `get_actor`, `_is_bot`, `_require_human`, `log_activity`, `generate_bug_display_id` |
| `routes/` | One module per feature area (`tasks`, `bugs`, `qa_tickets`, `agent_guide`, ...) — no cross-route imports |
| `feishu_sync.py` | Optional two-way Feishu Bitable sync (30s polling) |
| `feishu_bot.py` | Optional interactive Feishu bot (lark-oapi WebSocket) |
| `feishu_notify.py` | Optional webhook notifications on task/blocker/bug events |
| `feishu_docs.py` | Optional Feishu Docs/Wiki/Sheets integration (QA ticket creation) |
| `feishu_digest.py` | Optional weekly digest script |
| `agents/` | CLI helper (`kanban_worker.py`) for AI coding agents |
| `static/` | Frontend: main kanban, bug tracker, analytics |
| `data/kanban.db` | SQLite database (WAL mode) — created on first run |

## Local dev

```bash
cp .env.example .env       # configure (everything optional except PORT)
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python3 app.py             # → http://localhost:8666
```

Or via Docker:
```bash
./install.sh               # interactive setup
# or:
docker compose up -d
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -x -q        # ~220 tests; should pass under 5 seconds
```

## Rules

- `.env*` files are gitignored — never commit credentials. Only `.env.example` is checked in.
- `data/` is gitignored — the DB is single-user state.
- Route modules in `routes/` import from `db`, `models`, `helpers` only — no cross-route imports.
- All timestamps use UTC+8 (Asia/Shanghai) by default — see `helpers.now_iso()`. Change `TZ` in `helpers.py` for other deployments.
- Soft-delete pattern: `deleted_at` timestamp instead of hard delete. Cascades: deleting a project cascades to workstreams → tasks, blockers, recurring_tasks. Restore matches by timestamp.
- Bot governance — users have `role` (`human` / `bot`). Unknown actors are treated as bots. Bots cannot mark tasks `done` / `abandoned`, delete projects/workstreams/tasks/bugs, create projects/workstreams, change workstream priorities, or change user roles. They submit `in_review` for human approval. Bug creation: bots are silently coerced to `source='agent'` (goes to a separate bug table from `source='manual'`). Bots can modify any bug regardless of source.
- Route order: literal routes (`/projects/reorder`) must be registered before parameterized (`/projects/{pid}`).

## Bug status flow

`open → investigating → fixing → fix_complete → to_verify → resolved → closed` (also `wontfix`)

- **`fix_complete`** — fix committed/merged. The default move agents make after a daily MR-level fix; QA team monitors this bucket and spot-checks via the linked QA ticket.
- **`to_verify`** — fix bundled into a weekly/monthly release; reserved for formal end-to-end release verification.

When moving a bug to `fix_complete`/`to_verify`/`resolved`, also populate the fix metadata (`fix_method`, `fix_version`, `fix_date`) in the same call.

## Display IDs

Human-readable bug IDs use `BUG-YYMMDD-NNN` (manual / QA) or `RD-YYMMDD-NNN` (agent). NNN resets daily per prefix.

## Optional Feishu features

All Feishu features are opt-in via env vars (see `.env.example` + `docs/SETUP.md`). If `FEISHU_APP_ID` is blank, the kanban runs standalone — no sync, no chat bot, no wiki tickets. Everything still works via the REST API and web UI.

## See also

- `docs/AGENT_INSTRUCTIONS.md` — full integration guide for AI agents in **other** repos that want to use this kanban as their backend
- `docs/AGENT_QUICKSTART.md` — short reference of the same
- `docs/AGENT_ARCHITECTURE_zh.md` — Chinese architecture explainer for team members deploying this
- `docs/SETUP.md` — full Feishu app setup walkthrough (scopes, tokens, wiki sub-pages)
- `CONTRIBUTING.md` — how to contribute

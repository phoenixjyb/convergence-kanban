# ConvergenceKanban

> A self-hosted kanban for teams that live in **Feishu / Lark** *and* use
> **AI coding agents** as active contributors.
> Bilingual (EN / ZH), Feishu-native, agent-first.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-modern-009688.svg)](https://fastapi.tiangolo.com/)

```
projects → workstreams → tasks → subtasks
bugs (manual + agent streams, 7-status flow)
optional Feishu Bitable sync · chat bot · wiki QA tickets
REST API · agent governance · audit log
```

## Why?

If your team uses Feishu (or Lark) and is starting to let AI coding agents
file bugs, claim tasks, and submit MRs, you've hit the same wall I did:
Feishu is great for humans but hostile to scripts, and REST-first tools
like Jira force humans out of Feishu. ConvergenceKanban sits between both.

The agent talks to a clean REST API. The kanban service mirrors state into
Feishu Bitable using its own credentials. Humans keep their Feishu views.
SQLite is the single source of truth. Bidirectional sync with conflict
detection means manual edits in Feishu flow back into the DB cleanly.

[→ Long-form rationale](docs/WHY_THIS_PROJECT.md)

## Quick start

```bash
# One-liner installer (Docker required)
curl -fsSL https://raw.githubusercontent.com/phoenixjyb/convergence-kanban/main/install.sh | bash
```

That gets you a working kanban on `http://localhost:8666` in about 60
seconds with zero Feishu configuration required.

To enable Feishu integration:

1. Create a custom app on https://open.feishu.cn/app (or your Lark
   equivalent)
2. Paste `FEISHU_APP_ID` / `FEISHU_APP_SECRET` into `.env`
3. `docker compose --profile feishu up -d`

Full walkthrough including required scopes: [→ docs/SETUP.md](docs/SETUP.md).

### Or run from source

```bash
git clone https://github.com/phoenixjyb/convergence-kanban.git
cd convergence-kanban
cp .env.example .env
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python3 app.py
# → http://localhost:8666
```

## Features

### Kanban

- Projects → workstreams → tasks → subtasks
- Per-task priority, assignees, start/due dates, dependencies, time
  tracking, recurring tasks
- Soft-delete + restore (per-entity), with a bin view
- Bulk operations on tasks (multi-select)
- Comments threaded per entity
- Bilingual fields — every title/description has `*_en` / `*_zh` variants;
  language toggle in the UI
- Activity log with full audit trail keyed by `X-Kanban-User`

### Bug pipeline

7-status flow with two streams:

```
open → investigating → fixing → fix_complete → to_verify → resolved → closed
                                  ↑                ↑
                       (daily MR-level QA)  (release verification)
```

- `source='manual'` (QA team) and `source='agent'` (AI-submitted) bugs
  routed to separate tables for clean filtering
- Human-readable display IDs: `BUG-YYMMDD-NNN` / `RD-YYMMDD-NNN` with daily
  counter reset
- Fix metadata fields (`fix_method`, `fix_version`, `fix_date`) populated
  when moving to `fix_complete`/`to_verify`/`resolved`
- Many-to-many bug ↔ task linking

### Analytics

- Burndown / burnup
- Bug trends
- Workload per assignee
- Blocker aging
- Gantt with multi-project chip selector + workstream filter

### Optional Feishu / Lark integration

All Feishu features are opt-in. Leave `FEISHU_APP_ID` blank in `.env` and
ConvergenceKanban runs as a standalone kanban. Enable individually:

| Feature | Module | What it does |
|---------|--------|--------------|
| Bitable two-way sync | `feishu_sync.py` | Polls Bitable every 30s; pushes local changes; pulls remote changes; per-field conflict detection |
| Interactive chat bot | `feishu_bot.py` | Long-poll WebSocket; bilingual `@bot help`, `@bot my tasks`, `@bot bugs`, etc. |
| Webhook notifications | `feishu_notify.py` | Posts cards to a Feishu group webhook on bug/blocker/task events |
| Weekly digest | `feishu_digest.py` | Scheduled per-project summary card |
| Wiki QA tickets | `feishu_docs.py` + `routes/qa_tickets.py` | Creates wiki pages under a configurable parent for QA test/data-collection requests |

### AI agent integration

- REST API at `/api/...` — every kanban action has a JSON endpoint
- Identity enforced via `X-Kanban-User: alice-claude` (`{firstname}-{tool}`)
- Pre-registered bot accounts only; unknown users get HTTP 401
- Bot governance: bots can't mark tasks `done`/`abandoned`, can't delete
  projects/workstreams/tasks/bugs, can't change workstream priorities
- Bug-creation policy: bots silently coerced to `source='agent'` so they
  can't accidentally pollute the human-curated bug table
- Live agent guide at `GET /api/agent-guide` — drop a one-liner into any
  repo's `CLAUDE.md` / `AGENTS.md` and the agent always pulls the current
  version
- CLI helper at `agents/kanban_worker.py` (`my-tasks`, `pick-task`,
  `report-bug`, `complete-task`, etc.)

[→ Full agent integration guide (English)](docs/AGENT_INSTRUCTIONS.md)
[→ Short reference](docs/AGENT_QUICKSTART.md)
[→ Architecture (Chinese)](docs/AGENT_ARCHITECTURE_zh.md)

## Architecture

```
Browser / curl / AI agent
        │
        │ HTTP (X-Kanban-User: alice-claude)
        ▼
┌──────────────────────────────────────────┐
│ FastAPI (app.py)                         │
│  - 22 route modules                      │
│  - middleware: identity + governance     │
│  - SQLite (WAL mode)                     │
└──────────────────────────────────────────┘
        │
        │ (optional) Feishu app credentials
        ▼
┌──────────────────────────────────────────┐
│ Feishu / Lark Open Platform              │
│  - Bitable (records)                     │
│  - Wiki (QA tickets)                     │
│  - IM (chat bot + webhook notifications) │
└──────────────────────────────────────────┘
```

## Project layout

```
.
├── app.py                  Entry point
├── db.py                   SQLite init + migrations
├── models.py               Pydantic models
├── helpers.py              Shared utilities (TZ, bot governance, display IDs)
├── routes/                 Feature modules (tasks, bugs, qa_tickets, ...)
├── feishu_*.py             Optional Feishu integrations
├── agents/                 CLI helper for AI agents (kanban_worker.py)
├── static/                 Vanilla HTML/JS/CSS frontend
├── docs/                   Setup, agent guide, architecture
├── tests/                  ~220 pytest tests
├── scripts/                Backup, integrity check, dev seed
├── Dockerfile              Single-stage production image
├── docker-compose.yml      Kanban + optional sync/bot via profiles
├── install.sh              One-line installer
└── .env.example            Documented configuration template
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -x -q
```

~220 tests. Fresh run should complete in under 5 seconds.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Code of conduct:
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

[MIT](LICENSE)

# ConvergenceKanban

> A self-hosted kanban for teams that live in **Feishu / Lark** *and* use
> **AI coding agents** as active contributors.
> Bilingual (EN / ZH), Feishu-native, agent-first.

> 🇨🇳 中文版本请见 [`README_zh.md`](README_zh.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-modern-009688.svg)](https://fastapi.tiangolo.com/)
[![CI](https://github.com/phoenixjyb/convergence-kanban/actions/workflows/test.yml/badge.svg)](https://github.com/phoenixjyb/convergence-kanban/actions)
[![Latest release](https://img.shields.io/github/v/release/phoenixjyb/convergence-kanban)](https://github.com/phoenixjyb/convergence-kanban/releases)

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

### Use with Claude Code (30 seconds)

Point any AI agent at this kanban by dropping a single line into the target
repo's `CLAUDE.md` / `AGENTS.md`:

```bash
echo 'Read kanban API contract: curl http://localhost:8666/api/agent-guide' >> CLAUDE.md
```

The agent fetches the live integration guide on first run, then files bugs
and claims tasks via REST. Example: an agent submits a crash report with
`POST /api/bugs` — it lands on your board as an `RD-YYMMDD-NNN` card,
visible to the human QA team, no Feishu round-trip required.

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

### Optional Slack / DingTalk notifications

Bug/blocker/task events can fan out to multiple chat platforms in parallel —
enable any combination by setting the corresponding webhook URL in `.env`.

| Platform | Module | How to enable |
|----------|--------|---------------|
| Slack | `slack_notify.py` | Incoming Webhook URL → `SLACK_WEBHOOK_URL` |
| DingTalk / 钉钉 | `dingtalk_notify.py` | Group robot webhook → `DINGTALK_WEBHOOK_URL` (+ HMAC secret) |

A dispatcher (`notify.py`) fans every event to all configured backends.
One failing backend never blocks the others. See [docs/SETUP.md](docs/SETUP.md)
sections 4 & 5 for the walkthrough.

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

## Compared to other kanbans

|                    | ConvergenceKanban | Vikunja | WeKan | Focalboard | Trello | Jira |
|--------------------|:-:|:-:|:-:|:-:|:-:|:-:|
| Bilingual EN / ZH (per-field)  | yes | partial UI | partial UI | partial UI | no | partial UI |
| Feishu / Lark native           | yes | no  | no  | no  | no  | no  |
| AI-agent native (REST + governance) | yes | no | no | no | no | partial |
| Self-hosted                    | yes | yes | yes | yes | no  | yes (DC) |
| SQLite, single-file simple     | yes | no (Postgres/MySQL) | no (MongoDB) | no (Postgres) | n/a | no |
| Free / open source             | yes (MIT) | yes (AGPL) | yes (MIT) | yes (MPL, sunset) | no | no |

Where the others are stronger: Vikunja has a far richer permission /
team-management model; WeKan is a more mature pure-Trello-clone with a
larger plugin ecosystem; Jira has an enterprise-grade integration
ecosystem nothing self-hosted will match. ConvergenceKanban's niche is
the intersection of *Feishu shop* and *AI-agents-as-contributors* — if
you're not at that intersection, one of those is likely a better fit.

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
└────────────┬─────────────────────────────┘
             │
             ├─→ Feishu / Lark Open Platform
             │     - Bitable two-way sync
             │     - Wiki (QA tickets)
             │     - IM (chat bot + webhooks)
             │
             └─→ notify.py dispatcher (fan-out)
                   ├─→ feishu_notify.py
                   ├─→ slack_notify.py
                   └─→ dingtalk_notify.py
```

## Project layout

```
.
├── app.py                  Entry point
├── db.py                   SQLite init + migrations
├── models.py               Pydantic models
├── helpers.py              Shared utilities (TZ, bot governance, display IDs)
├── routes/                 Feature modules (tasks, bugs, qa_tickets, ...)
├── notify.py               Chat-platform dispatcher (fan-out)
├── feishu_*.py             Optional Feishu integrations
├── slack_notify.py         Optional Slack Incoming Webhook notifications
├── dingtalk_notify.py      Optional DingTalk group robot notifications
├── agents/                 CLI helper for AI agents (kanban_worker.py)
├── static/                 Vanilla HTML/JS/CSS frontend
├── docs/                   Setup, agent guide, architecture
├── tests/                  239 pytest tests
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

239 tests. Fresh run should complete in under 5 seconds.

## Contributing

PRs welcome. See [CONTRIBUTING.md](CONTRIBUTING.md). Code of conduct:
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

[MIT](LICENSE)

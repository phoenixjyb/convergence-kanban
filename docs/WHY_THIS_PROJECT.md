# Why ConvergenceKanban Exists

## The problem

If your team meets two conditions, this project might be useful to you:

1. **You live in Feishu / Lark** (or a similar bilingual messenger + base) and
   you can't realistically force everyone onto a separate tool like Jira or
   Linear.
2. **You're using AI coding agents** (Claude Code, Codex, Cursor, Aider,
   Copilot, etc.) as active contributors who need to read state, file bugs,
   and submit work programmatically — not just as code-completion sidekicks.

These two requirements pull in opposite directions. Feishu Bitable is great
for humans but hostile to scripted agents (per-record permission model, OAuth
hassles, rate limits, no proper REST contract for the actions you care
about). REST-first tools like Jira are agent-friendly but force the human
side of the team into yet another browser tab.

## The shape of the solution

ConvergenceKanban is a thin layer that sits between both worlds:

- **For humans**: a self-hosted kanban web UI + optional bidirectional sync
  to a Feishu Bitable so the team's existing Feishu views keep working.
- **For agents**: a clean REST API (`/api/...`), enforced identity headers
  (`X-Kanban-User: alice-claude`), and bot-governance rules (agents can't
  mark things `done`, only `in_review`, etc.).

The agent never touches Feishu directly. It posts to the kanban API; the
kanban service uses its own credentials to mirror state into Feishu. So:

- The Feishu side stays familiar — same Bitable views, same chat, same
  permission model.
- The agent side is REST — no OAuth flows, no per-record sharing, no
  Bitable token lifecycle to manage from inside an agent.
- The SQLite DB is the single source of truth — bidirectional sync is
  conflict-detected, not last-write-wins.

## What's in scope

- **Kanban**: projects → workstreams → tasks, with priority, assignees,
  start/due dates, dependencies, time tracking, recurring tasks, soft-delete
  + restore, and a bin.
- **Bug pipeline**: 7-status flow (`open → investigating → fixing →
  fix_complete → to_verify → resolved → closed` plus `wontfix`), with
  separate manual and agent streams, fix-metadata fields, and many-to-many
  task linking.
- **Analytics**: burndown, bug trends, workload, blocker aging, Gantt.
- **Optional Feishu integration**: Bitable two-way sync, long-poll chat
  bot, webhook notifications, weekly digest, wiki QA-ticket creation.
- **Agent integration**: REST API, governance, live agent-guide endpoint,
  helper CLI (`agents/kanban_worker.py`), display-ID generator, full
  audit log.

## What's *not* in scope

- **Account auth / SSO**: this is a self-hosted single-tenant tool. Identity
  is just a header. Put it behind a VPN or your reverse proxy of choice.
- **Multi-tenancy**: one DB, one team. If you need multi-tenancy, fork it.
- **Sprint / agile ceremonies**: no story points, no velocity, no epics
  hierarchy beyond projects → workstreams → tasks → subtasks.
- **Replacement for full Jira / Linear**: this is intentionally small and
  opinionated. If your team needs custom workflows, automation rules, or
  enterprise reporting, use one of those.

## Design choices worth knowing

- **SQLite, not Postgres**: kept on purpose. The DB is small (~10K rows for
  a busy team over a year), single-writer, and the whole point is "you
  unzip and run it." WAL mode handles light concurrency fine.
- **Vanilla HTML/JS/CSS frontend**: no React, no build step. View source on
  any page to see what's happening.
- **Synchronous FastAPI routes**: the data model is small enough that
  async buys nothing. Simpler code paths, easier debugging.
- **Bilingual (EN / ZH) baked in**: every text field has `*_en` / `*_zh`
  variants. Display language is a UI toggle, not a separate translation
  layer.
- **All times in UTC+8 (Asia/Shanghai)** by default — change `TZ` in
  `helpers.py` for other deployments.

## When to use something else

- You need PRD-grade roadmapping, OKRs, and exec-level reports → Linear, Jira.
- You need cross-team / cross-org visibility with permissions → Asana, Jira.
- Your team doesn't use Feishu and doesn't have AI agents writing code → just
  use any of the above.

## What you'll get out of the box

`./install.sh` will get you a working kanban running locally in about a
minute. Without any Feishu configuration it's just a self-hosted kanban with
a clean API. Adding Feishu integration is one app-registration + a paste of
two values into `.env` — see `docs/SETUP.md`.

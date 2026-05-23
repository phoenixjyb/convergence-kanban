# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] — 2026-05-20

### Fixed

- **`feishu_bot` ref resolver no longer mis-parses all-digit task IDs as
  numbered shortcuts.** `uuid.uuid4().hex[:12]` rolls all digits roughly 1
  in 8 times; those IDs used to collide with the 1-20 shortcut namespace
  and return `"No shortcut #..."` instead of resolving the task. The
  resolver now caps shortcut interpretation at 3 digits.
- Tightened `test_done_chinese` assertion + added a focused regression
  test for the resolver. The previous assertion intermittently failed on
  CI when the random task ID happened to be all digits.

## [0.2.1] — 2026-05-20

### Added

- **Chinese README** (`README_zh.md`) — full bilingual coverage of features,
  setup, architecture, and project layout. Cross-linked from the English
  README.

### Changed

- README architecture diagram now shows the `notify.py` dispatcher fan-out
  to all three chat backends (Feishu / Slack / DingTalk) instead of only
  Feishu.
- Project-layout section lists `notify.py`, `slack_notify.py`, and
  `dingtalk_notify.py` explicitly.
- Test count corrected to 238 (was "~220").

## [0.2.0] — 2026-05-20

### Added

- **Slack notifications** — set `SLACK_WEBHOOK_URL` to fan bug/blocker/task
  events to a Slack channel via Incoming Webhook (Block Kit messages).
- **DingTalk / 钉钉 notifications** — set `DINGTALK_WEBHOOK_URL` (+ optional
  `DINGTALK_WEBHOOK_SECRET` for HMAC-SHA256 signed webhooks) to fan events
  to a DingTalk group robot.
- **`notify.py` dispatcher** — single entry point that fans events to all
  configured backends (Feishu, Slack, DingTalk). One backend failing
  doesn't block the others. Each platform module is parallel and
  independently optional.

### Changed

- `routes/{tasks,blockers,bugs}.py` now call `notify.notify_*()` instead of
  `feishu_notify` directly. Behavior is unchanged when only Feishu is
  configured.

## [0.1.0] — 2026-05-19

Initial public release.

### Added

- Bilingual (EN / ZH) kanban board with projects, workstreams, tasks
- Bug pipeline with seven statuses: `open → investigating → fixing →
  fix_complete → to_verify → resolved → closed` (plus `wontfix`)
- Two bug streams: `source='manual'` (human QA) and `source='agent'`
  (AI-submitted)
- Human-readable bug IDs: `BUG-YYMMDD-NNN` / `RD-YYMMDD-NNN`
- Fix metadata fields (`fix_method`, `fix_version`, `fix_date`) with
  two-way Feishu Bitable sync
- Gantt chart with multi-project chip selector + workstream filter
- Bug-to-task many-to-many linking
- Optional Feishu integrations:
  - Two-way Bitable sync (30s polling, conflict detection)
  - Chat bot (long-poll WebSocket) with bilingual commands
  - Webhook notifications for bug/blocker/task events
  - Weekly digest reports
  - Wiki QA-ticket creation under a configurable parent page
- AI-agent integration via REST API:
  - Identity enforced via `X-Kanban-User` header (`{firstname}-{tool}`)
  - Bot governance (cannot mark tasks `done`, etc.)
  - Live agent-guide endpoint at `GET /api/agent-guide`
  - Helper CLI `agents/kanban_worker.py`
- One-line installer (`install.sh`)
- Docker + docker-compose deployment
- 220+ tests

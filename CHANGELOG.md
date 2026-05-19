# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

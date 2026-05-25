# Contributing to ConvergenceKanban

Thanks for considering a contribution! ConvergenceKanban is a small, opinionated
project — issues, ideas, and PRs are all welcome.

## Quick start

```bash
git clone https://github.com/phoenixjyb/convergence-kanban.git
cd convergence-kanban
cp .env.example .env
python3 -m venv venv && . venv/bin/activate
pip install -r requirements.txt
python3 app.py            # → http://localhost:8666
```

The Feishu features (Bitable sync, wiki bot, chat notifications) are
optional — leave the `FEISHU_*` env vars blank and the kanban runs
standalone.

## Running tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -x -q
```

The suite is 239 tests; a clean run should be under 5 seconds.

## Code layout

| Path | What |
|------|------|
| `app.py` | Entry point — mounts FastAPI routers, registers middleware |
| `db.py` | SQLite init, migrations, `get_db()` context manager |
| `models.py` | Pydantic request models |
| `helpers.py` | Shared utilities (timestamps, actor extraction, bot governance) |
| `routes/` | One module per feature area (`tasks`, `bugs`, `qa_tickets`, ...) |
| `notify.py` | Chat-platform dispatcher — fans events to all configured backends |
| `slack_notify.py` | Optional Slack Incoming Webhook backend |
| `dingtalk_notify.py` | Optional DingTalk group robot backend (HMAC-signed) |
| `feishu_*.py` | Optional Feishu integration (sync, bot, docs, notify, digest) |
| `static/` | Frontend (vanilla HTML/JS/CSS) — main board, bug pipeline, analytics |
| `agents/` | CLI helper for AI coding agents (`kanban_worker.py`) |
| `docs/` | All documentation including the AI-agent integration guides |

## Adding a new chat-platform backend

Notification backends are intentionally parallel — there is no abstract base
class to subclass. To add a new platform (e.g. Discord, Teams):

1. Copy `slack_notify.py` to `<platform>_notify.py` and mirror its public
   surface: `notify_bug_event()`, `notify_blocker_event()`,
   `notify_task_event()`. Each function reads its own env var(s) and
   silently no-ops when unset.
2. Add an optional import + dispatch call inside `notify.py` alongside
   the existing backends. Wrap the import in `try/except ImportError` so
   the module stays optional.
3. Add tests under `tests/test_<platform>_notify.py` (stub the webhook
   call) and document the env var in `.env.example` and `docs/SETUP.md`.

## Code style

- Python 3.10+; type hints encouraged but not required everywhere
- 4-space indent, no `from x import *`
- Routes import only from `db`, `models`, `helpers` — no cross-route imports
- Soft-delete pattern: `deleted_at` timestamp instead of hard delete
- All timestamps in Asia/Shanghai (UTC+8) — see `helpers.now_iso()`

## Pull request checklist

- [ ] `pytest tests/ -x -q` passes
- [ ] Any new env vars documented in `.env.example`
- [ ] User-facing changes mentioned in `CHANGELOG.md`
- [ ] No real personal info, internal hostnames, or company-specific
      references — use generic examples (`alice-claude`, `example.com`,
      `192.0.2.0/24` per RFC 5737)

## Filing issues

Please include:

1. What you tried (curl command, UI action)
2. What you expected
3. What actually happened (including any server log line)
4. Output of `git log -1 --oneline` so we know your version

## Licensing

By submitting a PR you agree to license your contribution under the MIT
License (see `LICENSE`).

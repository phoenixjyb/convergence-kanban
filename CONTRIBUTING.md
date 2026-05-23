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

The suite is ~220 tests; a clean run should be under 5 seconds.

## Code layout

| Path | What |
|------|------|
| `app.py` | Entry point — mounts FastAPI routers, registers middleware |
| `db.py` | SQLite init, migrations, `get_db()` context manager |
| `models.py` | Pydantic request models |
| `helpers.py` | Shared utilities (timestamps, actor extraction, bot governance) |
| `routes/` | One module per feature area (`tasks`, `bugs`, `qa_tickets`, ...) |
| `feishu_*.py` | Optional Feishu integration (sync, bot, docs, notify, digest) |
| `static/` | Frontend (vanilla HTML/JS/CSS) — main board, bug pipeline, analytics |
| `agents/` | CLI helper for AI coding agents (`kanban_worker.py`) |
| `docs/` | All documentation including the AI-agent integration guides |

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

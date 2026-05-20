"""Live agent-guide endpoint — serves AGENT_INSTRUCTIONS.md / AGENT_QUICKSTART.md
from disk so any AI agent in any repo can fetch the canonical instructions
without copying them locally.

GET /api/agent-guide              → AGENT_INSTRUCTIONS.md (full guide)
GET /api/agent-guide?format=quickstart → AGENT_QUICKSTART.md (short version)
GET /api/agent-guide?format=index → list both available docs

No auth — read-only. Falls back to a small message if the markdown files
are missing on disk (so the deployed service degrades gracefully).
"""

from pathlib import Path

from fastapi import APIRouter, Query
from starlette.responses import PlainTextResponse, JSONResponse


router = APIRouter(prefix="/api", tags=["agent-guide"])


_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

_FORMATS = {
    "full": "AGENT_INSTRUCTIONS.md",
    "instructions": "AGENT_INSTRUCTIONS.md",
    "quickstart": "AGENT_QUICKSTART.md",
    "short": "AGENT_QUICKSTART.md",
    "architecture": "AGENT_ARCHITECTURE_zh.md",
    "arch": "AGENT_ARCHITECTURE_zh.md",
}


@router.get("/agent-guide")
def get_agent_guide(
    format: str = Query("full", description="full | quickstart | index"),
):
    """Return the agent integration guide as markdown."""
    if format == "index":
        return JSONResponse({
            "available_formats": {
                "full": "AGENT_INSTRUCTIONS.md — complete tutorial (~10KB)",
                "quickstart": "AGENT_QUICKSTART.md — concise reference (~7KB)",
                "architecture": "AGENT_ARCHITECTURE_zh.md — system architecture explainer (Chinese, ~12KB)",
            },
            "usage": [
                "curl <kanban-host>/api/agent-guide",
                "curl '<kanban-host>/api/agent-guide?format=quickstart'",
                "curl '<kanban-host>/api/agent-guide?format=architecture'",
            ],
            "tip": "drop a one-liner in your repo's CLAUDE.md / AGENTS.md pointing here so your agents fetch it on session start.",
        })

    filename = _FORMATS.get(format)
    if not filename:
        return PlainTextResponse(
            f"Unknown format '{format}'. Try: full | quickstart | index\n",
            status_code=400,
            media_type="text/plain; charset=utf-8",
        )

    path = _DOCS_DIR / filename
    if not path.is_file():
        return PlainTextResponse(
            f"# ConvergenceKanban — agent guide\n\n"
            f"(File {filename} not found on the deployed server. "
            f"Source: github.com/phoenixjyb/convergence-kanban/tree/main/docs)\n",
            status_code=404,
            media_type="text/markdown; charset=utf-8",
        )

    return PlainTextResponse(
        path.read_text(encoding="utf-8"),
        media_type="text/markdown; charset=utf-8",
    )

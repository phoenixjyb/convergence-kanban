"""
ConvergenceKanban — Lightweight project management for your team.
FastAPI backend with SQLite persistence.
Bilingual (EN/ZH). Deployed on ZeroTier network.
"""

import os
import sqlite3
import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from db import init_db, get_db
from helpers import RequireLoginMiddleware
from routes import (
    projects, workstreams, tasks, dependencies, time_tracking,
    attachments, recurring, sync_conflicts, comments, blockers,
    bugs, templates, analytics, dashboard, bin, users, activity,
    alerts, export, auth, qa_tickets, agent_guide,
)

APP_VERSION = "1.4.8"

app = FastAPI(title="ConvergenceKanban", version=APP_VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.add_middleware(RequireLoginMiddleware)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


@app.exception_handler(sqlite3.IntegrityError)
async def integrity_error_handler(request, exc):
    return JSONResponse(status_code=400, content={"detail": f"Constraint violation: {exc}"})


# Include all route modules
for router_module in (
    projects, workstreams, tasks, dependencies, time_tracking,
    attachments, recurring, sync_conflicts, comments, blockers,
    bugs, templates, analytics, dashboard, bin, users, activity,
    alerts, export, auth, qa_tickets, agent_guide,
):
    app.include_router(router_module.router)


@app.get("/", response_class=HTMLResponse)
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/bugs", response_class=HTMLResponse)
async def bugs_page():
    return FileResponse(Path(__file__).parent / "static" / "bugs.html")


@app.get("/analytics", response_class=HTMLResponse)
async def analytics_page():
    return FileResponse(Path(__file__).parent / "static" / "analytics.html")


@app.get("/promo", response_class=HTMLResponse)
async def promo():
    return FileResponse(Path(__file__).parent / "static" / "promo.html")


_start_time = time.time()


@app.get("/api/health")
async def health_check():
    """System health: DB connectivity, uptime, table counts."""
    status = {"status": "ok", "version": APP_VERSION, "uptime_seconds": round(time.time() - _start_time)}
    try:
        with get_db() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            counts = {}
            for (name,) in tables:
                counts[name] = conn.execute(f"SELECT COUNT(*) FROM [{name}]").fetchone()[0]
            status["db"] = "ok"
            status["tables"] = counts
    except Exception as e:
        status["db"] = "error"
        status["db_error"] = str(e)
        status["status"] = "degraded"
    return status


@app.on_event("startup")
def startup():
    init_db()


if __name__ == "__main__":
    import uvicorn
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8666")))

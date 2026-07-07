"""
Shared utilities for ConvergenceKanban sub-agents.
Provides kanban API client, Feishu webhook posting, and report formatting.
"""

import json
import os
import sys
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

# Project-wide timezone: Asia/Shanghai (UTC+8)
TZ = timezone(timedelta(hours=8))
from pathlib import Path

# Load env
_base = Path(__file__).resolve().parent.parent
for f in [".env.team", ".env"]:
    p = _base / f
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

KANBAN_API = os.getenv("KANBAN_API_URL", "http://127.0.0.1:8666/api")
FEISHU_WEBHOOK_URL = os.getenv("FEISHU_WEBHOOK_URL", "")
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ── Kanban API ────────────────────────────────────────────────────────────

def kanban_get(path: str, agent_name: str = "agent"):
    url = f"{KANBAN_API}{path}"
    req = urllib.request.Request(url, headers={"X-Kanban-User": agent_name})
    resp = _opener.open(req, timeout=15)
    return json.loads(resp.read())


def kanban_post(path: str, data: dict, agent_name: str = "agent"):
    url = f"{KANBAN_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json", "X-Kanban-User": agent_name},
    )
    resp = _opener.open(req, timeout=15)
    return json.loads(resp.read())


def kanban_put(path: str, data: dict, agent_name: str = "agent"):
    url = f"{KANBAN_API}{path}"
    body = json.dumps(data).encode()
    req = urllib.request.Request(
        url, data=body, method="PUT",
        headers={"Content-Type": "application/json", "X-Kanban-User": agent_name},
    )
    resp = _opener.open(req, timeout=15)
    return json.loads(resp.read())


def get_dashboard():
    return kanban_get("/dashboard")


def get_activity_log(limit: int = 50):
    return kanban_get(f"/activity?limit={limit}")


# ── Feishu Webhook ────────────────────────────────────────────────────────

def post_feishu_card(card: dict):
    if not FEISHU_WEBHOOK_URL:
        return None
    body = json.dumps({"msg_type": "interactive", "card": card}).encode()
    req = urllib.request.Request(
        FEISHU_WEBHOOK_URL, data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = _opener.open(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        print(f"[webhook] Failed: {e}")
        return None


def build_report_card(title: str, sections: list[dict], color: str = "blue") -> dict:
    """Build a Feishu interactive card from sections.

    Each section: {"header": str, "content": str}  (lark_md format)
    """
    elements = []
    for sec in sections:
        if sec.get("header"):
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**{sec['header']}**"}
            })
        if sec.get("content"):
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": sec["content"]}
            })
        elements.append({"tag": "hr"})

    if elements and elements[-1].get("tag") == "hr":
        elements.pop()

    color_map = {"blue": "blue", "red": "red", "green": "green", "orange": "orange", "purple": "purple"}
    return {
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": color_map.get(color, "blue"),
        },
        "elements": elements,
    }


def post_report(title: str, sections: list[dict], color: str = "blue"):
    """Build and post a report card to Feishu. Also prints to stdout."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    for sec in sections:
        if sec.get("header"):
            print(f"\n--- {sec['header']} ---")
        if sec.get("content"):
            print(sec["content"])
    print()

    card = build_report_card(title, sections, color)
    result = post_feishu_card(card)
    if result:
        print("[webhook] Report posted to Feishu.")
    elif not FEISHU_WEBHOOK_URL:
        print("[webhook] FEISHU_WEBHOOK_URL not set, skipped.")
    return result


# ── Helpers ───────────────────────────────────────────────────────────────

def now_str():
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def days_since(iso_str: str) -> int:
    if not iso_str:
        return -1
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return (datetime.now(TZ) - dt).days
    except Exception:
        return -1


def parse_args():
    """Parse common agent CLI args: --post (send to Feishu), --quiet."""
    post = "--post" in sys.argv
    quiet = "--quiet" in sys.argv
    return {"post": post, "quiet": quiet}

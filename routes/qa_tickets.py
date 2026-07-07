"""QA 工单 (work-order ticket) — submit / list / delete entries on the QA
team's Feishu wiki page.

POST /api/qa-tickets         create a new ticket
GET  /api/qa-tickets         list tickets (filter by owner)
DELETE /api/qa-tickets/{node_token}  best-effort delete (may need wiki admin)

Owner identity flows from the X-Kanban-User header (agents should send
{firstname}-{tool} like alice-claude).
"""

import logging
from typing import Optional, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from db import get_db
from helpers import get_actor, log_activity

try:
    import feishu_docs
except ImportError:
    feishu_docs = None  # type: ignore[assignment]


router = APIRouter(prefix="/api", tags=["qa-tickets"])
log = logging.getLogger(__name__)


class QARequirements(BaseModel):
    scenario: str = Field(default="", max_length=2000)
    expected_result: str = Field(default="", max_length=2000)
    record_screen: bool = False
    record_data: bool = False
    record_performance: bool = False
    duration: str = Field(default="", max_length=100)
    other: str = Field(default="", max_length=2000)


class QATicketCreate(BaseModel):
    task_type: Literal["采集任务", "测试任务", "其它任务"] = "测试任务"
    product: str = Field(min_length=1, max_length=200)
    task_name: str = Field(min_length=1, max_length=200)
    requirements: QARequirements
    version: str = Field(default="", max_length=200)
    schedule_time: str = Field(default="", max_length=10)  # HH:MM
    owner: Optional[str] = Field(default=None, max_length=100)
    # Kanban bug display_id this ticket verifies (e.g. BUG-260509-001 or RD-260509-002).
    # Optional but strongly recommended when the ticket is for bug verification.
    bug_id: str = Field(default="", max_length=30)


def _safe_log_activity(entity_type: str, entity_id: str, action: str,
                       actor: str, detail: str) -> None:
    """Log activity but never raise — DB lock or any other failure must not
    fail the parent request when the actual work (Feishu side) succeeded."""
    try:
        with get_db() as conn:
            log_activity(conn, entity_type, entity_id, action,
                         actor=actor, detail=detail)
    except Exception as e:
        log.warning("activity log failed (silently swallowed): %s", e)


@router.post("/qa-tickets")
def create_qa_ticket(payload: QATicketCreate, request: Request):
    """Create a new 工单 under the QA team's wiki page.

    `owner` defaults to X-Kanban-User header. For agents this should be
    {firstname}-{tool} (e.g. alice-claude).

    On Feishu API failure, attempts a best-effort cleanup of any orphan
    wiki node. If cleanup also fails, the orphan node_token is included
    in the error response so the client can manually delete via Feishu UI.
    """
    if feishu_docs is None:
        raise HTTPException(503, "feishu_docs module unavailable")
    if not feishu_docs.qa_ticket_configured():
        raise HTTPException(503, "QA ticket integration not configured. "
                                  "Set KANBAN_QA_WIKI_* env vars — see docs/SETUP.md.")

    actor = get_actor(request)
    owner = payload.owner or actor

    try:
        result = feishu_docs.create_qa_ticket(
            task_type=payload.task_type,
            product=payload.product,
            task_name=payload.task_name,
            owner=owner,
            requirements=payload.requirements.model_dump(),
            version=payload.version,
            schedule_time=payload.schedule_time,
            bug_id=payload.bug_id,
        )
    except Exception as e:
        # If feishu_docs raised after copy_wiki_node succeeded, the message
        # may include the orphan node token — but we don't have a clean way
        # to extract it. Log and surface a clear error.
        log.exception("qa-ticket create failed")
        raise HTTPException(502, f"Feishu ticket creation failed: {e}")

    # Activity log is non-critical: the ticket already exists in Feishu.
    # Don't let a DB lock or any other local failure turn this into a 500
    # — the agent already got their wiki page.
    _safe_log_activity("qa_ticket", result["node_token"], "created",
                        actor=actor, detail=result["title"])

    return result


@router.get("/qa-tickets")
def list_qa_tickets(owner: str = ""):
    """List tickets under the QA team's parent wiki page.

    `owner`: optional filter — substring match on title (e.g. 'alice-claude').

    Returns: list of {node_token, obj_token, title, status, wiki_url}.
    `status` is one of 'active', 'completed', 'cancelled' (derived from
    title prefix).
    """
    if feishu_docs is None or not feishu_docs.qa_ticket_configured():
        raise HTTPException(503, "QA ticket integration not configured. "
                                  "Set KANBAN_QA_WIKI_* env vars — see docs/SETUP.md.")
    try:
        return feishu_docs.list_qa_tickets(owner=owner)
    except Exception as e:
        log.exception("qa-ticket list failed")
        raise HTTPException(502, f"list failed: {e}")


@router.delete("/qa-tickets/{node_token}")
def delete_qa_ticket(node_token: str, request: Request):
    """Best-effort delete of a QA 工单 wiki node.

    NOTE: Feishu wiki space permissions can prevent the bot from deleting
    nodes even if it created them. If the API rejects, the response
    includes a hint to delete via Feishu UI (with the wiki URL).
    """
    if feishu_docs is None or not feishu_docs.qa_ticket_configured():
        raise HTTPException(503, "QA ticket integration not configured. "
                                  "Set KANBAN_QA_WIKI_* env vars — see docs/SETUP.md.")

    actor = get_actor(request)
    resp = feishu_docs.delete_wiki_node(
        feishu_docs.QA_WIKI_SPACE_ID, node_token, obj_type="docx",
    )
    if resp.get("code") == 0:
        _safe_log_activity("qa_ticket", node_token, "deleted",
                            actor=actor, detail="")
        return {"deleted": True, "node_token": node_token}

    # Failed — surface details so caller knows what to do
    msg = str(resp.get("msg", ""))[:500]
    return {
        "deleted": False,
        "node_token": node_token,
        "feishu_code": resp.get("code"),
        "feishu_msg": msg,
        "wiki_url": f"https://{feishu_docs.QA_WIKI_SUBDOMAIN}/wiki/{node_token}",
        "hint": "Feishu rejected the bot's delete (likely a wiki-space "
                "permission). Open the wiki URL in Feishu and delete from the UI.",
    }

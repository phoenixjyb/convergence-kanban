#!/usr/bin/env python3
"""
Feishu Docs (docx v1) read/write module.

Reuses the same app credentials and auth flow as feishu_sync.py.
All functions return parsed JSON dicts from the Feishu API.

Env vars (or .env / .env.team):
  FEISHU_APP_ID / FEISHU_APP_SECRET

Usage:
  from feishu_docs import (
      get_document, get_blocks, get_raw_text,
      create_document, append_blocks, update_block, delete_block,
      search_docs, list_folder,
  )
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Config (same pattern as feishu_sync.py) ──────────────────────────────

def _load_dotenv(path=".env"):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_profile = os.environ.get("FEISHU_PROFILE", "default")
for i, arg in enumerate(sys.argv):
    if arg == "--profile" and i + 1 < len(sys.argv):
        _profile = sys.argv[i + 1]

_base = Path(__file__).parent
if _profile != "default":
    _load_dotenv(_base / f".env.{_profile}")
_load_dotenv(_base / ".env")

_APP_ID = os.environ.get("FEISHU_APP_ID", "")
_APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")

# ── HTTP helpers (bypass proxy, same as feishu_sync.py) ──────────────────

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

def _request(url, method="GET", data=None, headers=None, _retries=3):
    hdrs = {"Content-Type": "application/json; charset=utf-8"}
    if headers:
        hdrs.update(headers)
    body = json.dumps(data).encode() if data else None
    for attempt in range(_retries):
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        try:
            with _opener.open(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode()
            if e.code < 500 and e.code != 429:
                print(f"  [docs] HTTP {e.code}: {err_body[:300]}", flush=True)
                return {"code": e.code, "msg": err_body[:200]}
            wait = 2 ** attempt
            print(f"[docs] Retry {attempt+1}/{_retries}: HTTP {e.code}", flush=True)
            if attempt < _retries - 1:
                time.sleep(wait)
            else:
                return {"code": e.code, "msg": err_body[:200]}
        except (urllib.error.URLError, OSError) as e:
            wait = 2 ** attempt
            print(f"[docs] Retry {attempt+1}/{_retries}: {e}", flush=True)
            if attempt < _retries - 1:
                time.sleep(wait)
            else:
                return {"code": -1, "msg": str(e)[:200]}


# ── Feishu Auth (cached tenant_access_token) ─────────────────────────────

_token_cache = {"token": "", "expires_at": 0}

def _get_token():
    now = time.time()
    if _token_cache["token"] and now < _token_cache["expires_at"] - 60:
        return _token_cache["token"]
    resp = _request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        method="POST",
        data={"app_id": _APP_ID, "app_secret": _APP_SECRET},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"Feishu auth failed: {resp}")
    _token_cache["token"] = resp["tenant_access_token"]
    _token_cache["expires_at"] = now + resp.get("expire", 7200)
    return _token_cache["token"]


def _api(path, method="GET", data=None):
    """Call Feishu Open API. `path` starts with / (e.g. /docx/v1/documents)."""
    url = f"https://open.feishu.cn/open-apis{path}"
    return _request(url, method=method, data=data,
                    headers={"Authorization": f"Bearer {_get_token()}"})


# ── Document-level operations ────────────────────────────────────────────

def get_document(document_id: str) -> dict:
    """Get document metadata (title, revision, create/update time)."""
    resp = _api(f"/docx/v1/documents/{document_id}")
    if resp.get("code") != 0:
        raise RuntimeError(f"get_document failed: {resp}")
    return resp["data"]["document"]


def get_blocks(document_id: str, page_size: int = 500) -> list:
    """
    Get all blocks in a document. Handles pagination.
    Returns a flat list of block dicts.
    """
    blocks = []
    page_token = ""
    while True:
        path = f"/docx/v1/documents/{document_id}/blocks?page_size={page_size}"
        if page_token:
            path += f"&page_token={page_token}"
        resp = _api(path)
        if resp.get("code") != 0:
            raise RuntimeError(f"get_blocks failed: {resp}")
        items = resp.get("data", {}).get("items", [])
        blocks.extend(items)
        if not resp["data"].get("has_more"):
            break
        page_token = resp["data"].get("page_token", "")
    return blocks


def get_block(document_id: str, block_id: str) -> dict:
    """Get a single block by ID."""
    resp = _api(f"/docx/v1/documents/{document_id}/blocks/{block_id}")
    if resp.get("code") != 0:
        raise RuntimeError(f"get_block failed: {resp}")
    return resp["data"]["block"]


def get_raw_text(document_id: str) -> str:
    """Get the plain-text content of a document."""
    resp = _api(f"/docx/v1/documents/{document_id}/raw_content")
    if resp.get("code") != 0:
        raise RuntimeError(f"get_raw_text failed: {resp}")
    return resp["data"]["content"]


def create_document(title: str, folder_token: str = "") -> dict:
    """
    Create a new document. Returns {"document_id": ..., "revision_id": ..., "title": ...}.
    If folder_token is provided, creates the doc in that folder;
    otherwise it lands in the app's root space.
    """
    payload = {"title": title}
    if folder_token:
        payload["folder_token"] = folder_token
    resp = _api("/docx/v1/documents", method="POST", data=payload)
    if resp.get("code") != 0:
        raise RuntimeError(f"create_document failed: {resp}")
    return resp["data"]["document"]


# ── Block-level write operations ─────────────────────────────────────────

def append_blocks(document_id: str, parent_block_id: str, children: list,
                  index: int = -1) -> list:
    """
    Append child blocks under a parent block.
    `parent_block_id` is usually the document's root block (== document_id).
    `children` is a list of block dicts (see _make_text_block helper).
    `index` — insertion position (-1 = append at end).

    Returns the list of created block dicts.
    """
    payload = {"children": children}
    if index >= 0:
        payload["index"] = index
    resp = _api(
        f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children",
        method="POST", data=payload,
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"append_blocks failed: {resp}")
    return resp["data"].get("children", [])


def update_block(document_id: str, block_id: str, update_body: dict) -> dict:
    """
    Update an existing block's content.
    `update_body` follows the Feishu UpdateBlockRequest schema, e.g.:
      {"update_text_elements": {"elements": [...]}}
    """
    resp = _api(
        f"/docx/v1/documents/{document_id}/blocks/{block_id}",
        method="PATCH", data=update_body,
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"update_block failed: {resp}")
    return resp["data"]["block"]


def delete_blocks(document_id: str, parent_block_id: str,
                  start_index: int, end_index: int) -> None:
    """
    Delete child blocks from start_index to end_index (exclusive)
    under a parent block.
    """
    resp = _api(
        f"/docx/v1/documents/{document_id}/blocks/{parent_block_id}/children"
        f"/batch_delete",
        method="DELETE",
        data={"start_index": start_index, "end_index": end_index},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"delete_blocks failed: {resp}")


# ── Drive operations (search, list folders) ──────────────────────────────

def search_docs(query: str, count: int = 20, doc_type: str = "docx") -> list:
    """
    Search for documents in shared drive space.
    `doc_type`: docx, sheet, bitable, folder, etc.
    Returns list of file metadata dicts.
    """
    payload = {
        "search_key": query,
        "count": count,
        "docs_type": doc_type,
    }
    resp = _api("/suite/docs-api/search/object", method="POST", data=payload)
    if resp.get("code") != 0:
        raise RuntimeError(f"search_docs failed: {resp}")
    return resp.get("data", {}).get("docs_entities", [])


def list_folder(folder_token: str, page_size: int = 200) -> list:
    """
    List files in a Drive folder. Returns list of file metadata dicts.
    """
    files = []
    page_token = ""
    while True:
        path = (f"/drive/v1/files?folder_token={folder_token}"
                f"&page_size={page_size}")
        if page_token:
            path += f"&page_token={page_token}"
        resp = _api(path)
        if resp.get("code") != 0:
            raise RuntimeError(f"list_folder failed: {resp}")
        items = resp.get("data", {}).get("files", [])
        files.extend(items)
        if not resp["data"].get("has_more"):
            break
        page_token = resp["data"].get("page_token", "")
    return files


# ── Block builder helpers ────────────────────────────────────────────────

def make_text_block(text: str, block_type: int = 2) -> dict:
    """
    Build a block dict for plain text content.
    Block types: 2=text, 3=heading1, 4=heading2, 5=heading3,
                 9=bullet, 10=ordered, 12=code, 14=quote.
    """
    # Map block_type int to the Feishu block_type enum value
    type_map = {
        2: "text", 3: "heading1", 4: "heading2", 5: "heading3",
        9: "bullet", 10: "ordered", 12: "code", 14: "quote",
    }
    type_name = type_map.get(block_type, "text")
    return {
        "block_type": block_type,
        type_name: {
            "elements": [
                {"text_run": {"content": text}}
            ]
        }
    }


def make_heading(text: str, level: int = 1) -> dict:
    """Convenience: heading block. level: 1=H1, 2=H2, 3=H3."""
    type_map = {1: 3, 2: 4, 3: 5}
    return make_text_block(text, block_type=type_map.get(level, 3))


# ── Wiki operations ──────────────────────────────────────────────────────

def resolve_wiki_token(node_token: str) -> dict:
    """Resolve a wiki node_token (the token from a wiki URL) to its metadata,
    including obj_token (which is the docx/sheet/bitable token to call the
    underlying API with) and obj_type."""
    resp = _api(f"/wiki/v2/spaces/get_node?token={node_token}")
    if resp.get("code") != 0:
        raise RuntimeError(f"resolve_wiki_token failed: {resp}")
    return resp["data"]["node"]


def copy_wiki_node(space_id: str, source_node_token: str,
                   target_parent_token: str, target_title: str,
                   target_space_id: str = "") -> dict:
    """Copy a wiki node (with all its embedded content) under a parent node.
    Useful for instantiating a template into a new ticket/doc.
    Returns the new node dict (node_token, obj_token, title, etc.)."""
    payload = {
        "target_parent_token": target_parent_token,
        "target_space_id": target_space_id or space_id,
        "title": target_title,
    }
    resp = _api(
        f"/wiki/v2/spaces/{space_id}/nodes/{source_node_token}/copy",
        method="POST", data=payload,
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"copy_wiki_node failed: {resp}")
    return resp["data"]["node"]


def update_wiki_node_title(space_id: str, node_token: str, title: str) -> None:
    """Rename a wiki node."""
    resp = _api(
        f"/wiki/v2/spaces/{space_id}/nodes/{node_token}/update_title",
        method="POST", data={"title": title},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"update_wiki_node_title failed: {resp}")


def list_wiki_children(space_id: str, parent_node_token: str,
                        page_size: int = 50) -> list:
    """List child wiki nodes under a parent. Returns list of node dicts
    (each has node_token, obj_token, obj_type, title, has_child, etc.)."""
    items = []
    page_token = ""
    while True:
        path = (f"/wiki/v2/spaces/{space_id}/nodes"
                f"?parent_node_token={parent_node_token}&page_size={page_size}")
        if page_token:
            path += f"&page_token={page_token}"
        resp = _api(path)
        if resp.get("code") != 0:
            raise RuntimeError(f"list_wiki_children failed: {resp}")
        items.extend(resp["data"].get("items", []))
        if not resp["data"].get("has_more"):
            break
        page_token = resp["data"].get("page_token", "")
    return items


def delete_wiki_node(space_id: str, node_token: str, obj_type: str = "docx") -> dict:
    """Best-effort delete of a wiki node.

    NOTE: Feishu's wiki delete API behavior depends on space-level permissions.
    The bot may receive `131005 node not found` even for nodes it created if
    the wiki space restricts deletion to admins.

    Returns the API response dict (caller should check `code`). Raises only on
    network errors — auth/permission failures come back as a non-zero code so
    the caller can decide how to handle (e.g. include in error response).
    """
    return _api(
        f"/wiki/v2/spaces/{space_id}/nodes/{node_token}",
        method="DELETE", data={"obj_type": obj_type},
    )


# ── Sheets operations ────────────────────────────────────────────────────

def parse_embedded_sheet_token(token: str) -> tuple:
    """An embedded sheet block (docx block_type=30) has a compound token
    formatted as 'spreadsheet_token_sheet_id'. Return (spreadsheet_token, sheet_id)."""
    spreadsheet_token, sheet_id = token.rsplit("_", 1)
    return spreadsheet_token, sheet_id


def find_embedded_sheet_token(document_id: str) -> str:
    """Find the first embedded sheet block (block_type=30) inside a docx.
    Returns the compound token, or '' if none found."""
    blocks = get_blocks(document_id)
    for b in blocks:
        if b.get("block_type") == 30 and "sheet" in b:
            return b["sheet"].get("token", "")
    return ""


def update_sheet_cells(spreadsheet_token: str, value_ranges: list) -> None:
    """Batch-update cells in a spreadsheet.
    `value_ranges`: list of {"range": "<sheet_id>!A1:B2", "values": [[...]]}.
    """
    resp = _api(
        f"/sheets/v2/spreadsheets/{spreadsheet_token}/values_batch_update",
        method="POST", data={"valueRanges": value_ranges},
    )
    if resp.get("code") != 0:
        raise RuntimeError(f"update_sheet_cells failed: {resp}")


# ── QA Ticket (工单) creation ────────────────────────────────────────────
#
# Configurable via env vars — leave blank to disable the QA-ticket feature.
# See docs/SETUP.md for how to get these tokens from your Feishu wiki.
#
#   KANBAN_QA_WIKI_SPACE_ID       — numeric wiki space id
#   KANBAN_QA_WIKI_PARENT_NODE    — node_token of the page where new
#                                   tickets are created as children
#   KANBAN_QA_WIKI_TEMPLATE_NODE  — node_token of the empty template doc
#                                   that gets copied for each ticket
#   KANBAN_QA_WIKI_SUBDOMAIN      — your Feishu tenant subdomain
#                                   (e.g. yourorg.feishu.cn). Used only to
#                                   render the wiki_url returned by the API.

QA_WIKI_SPACE_ID = os.environ.get("KANBAN_QA_WIKI_SPACE_ID", "")
QA_WIKI_PARENT_NODE = os.environ.get("KANBAN_QA_WIKI_PARENT_NODE", "")
QA_WIKI_TEMPLATE_NODE = os.environ.get("KANBAN_QA_WIKI_TEMPLATE_NODE", "")
QA_WIKI_SUBDOMAIN = os.environ.get("KANBAN_QA_WIKI_SUBDOMAIN", "feishu.cn")


def qa_ticket_configured() -> bool:
    """True if the QA-ticket integration has all required env vars set."""
    return bool(QA_WIKI_SPACE_ID and QA_WIKI_PARENT_NODE and QA_WIKI_TEMPLATE_NODE)


def _format_requirements(req: dict) -> str:
    """Render the requirements dict into the multi-line text the QA template uses."""
    def yn(v):
        if v is True or str(v).lower() in ("true", "yes", "是", "1"):
            return "是"
        if v is False or str(v).lower() in ("false", "no", "否", "0"):
            return "否"
        return str(v) if v else ""

    lines = []
    if req.get("scenario"):
        lines.append(f"场景要求：{req['scenario']}")
    if req.get("expected_result"):
        lines.append(f"预期结果：{req['expected_result']}")
    if "record_screen" in req:
        lines.append(f"是否录制屏幕：{yn(req['record_screen'])}")
    if "record_data" in req:
        lines.append(f"是否录制数据：{yn(req['record_data'])}")
    if "record_performance" in req:
        lines.append(f"是否录制性能：{yn(req['record_performance'])}")
    if req.get("duration"):
        lines.append(f"测试时长：{req['duration']}")
    if req.get("other"):
        lines.append(f"其他：{req['other']}")
    return "\n".join(lines)


def create_qa_ticket(
    task_type: str,
    product: str,
    task_name: str,
    owner: str,
    requirements: dict,
    version: str = "",
    schedule_time: str = "",
    bug_id: str = "",
) -> dict:
    """Create a new 工单 under the QA team's wiki (问题修复专项工单 sub-page).

    Workflow:
      1. Copy the QA template wiki node into the agent parent page → new node + new sheet.
      2. Populate the embedded sheet (rows 1-4: 任务类型/产品/版本/需求描述; row 7: Bug ID).
      3. Rename the node to '{YYYYMMDD}-{HH:MM}-{task_name}-{owner}'.

    `task_type`: e.g. "采集任务" / "测试任务" / "其它任务"
    `product`: e.g. "rev-A hardware" / "rev-B hardware"
    `task_name`: short title fragment
    `owner`: 发起人, should be {firstname}-{tool} for agents (e.g. "alice-claude")
    `requirements` keys (all optional):
      scenario, expected_result, record_screen (bool), record_data (bool),
      record_performance (bool), duration, other
    `version`: build version
    `schedule_time`: HH:MM (defaults to current Asia/Shanghai time)
    `bug_id`: kanban bug display_id (e.g. 'BUG-260509-001' or 'RD-260509-002')
              that this ticket is verifying. Optional but strongly recommended
              when the ticket is for bug verification.

    Returns: {wiki_url, node_token, doc_token, sheet_token, title}
    """
    from datetime import datetime, timezone, timedelta

    tz = timezone(timedelta(hours=8))
    now = datetime.now(tz)
    date_str = now.strftime("%Y%m%d")
    time_str = schedule_time or now.strftime("%H:%M")
    final_title = f"{date_str}-{time_str}-{task_name}-{owner}"

    # 1. Copy template into 问题修复专项工单 sub-page
    new_node = copy_wiki_node(
        QA_WIKI_SPACE_ID, QA_WIKI_TEMPLATE_NODE,
        QA_WIKI_PARENT_NODE,
        target_title=f"[creating] {final_title}",
    )
    node_token = new_node["node_token"]
    doc_token = new_node["obj_token"]

    # 2. Find embedded sheet inside the new doc
    sheet_full_token = find_embedded_sheet_token(doc_token)
    if not sheet_full_token:
        raise RuntimeError(f"no embedded sheet in copied doc {doc_token}")
    spreadsheet_token, sheet_id = parse_embedded_sheet_token(sheet_full_token)

    # 3. Populate rows 1-4 (the template has these labels in column A) +
    #    row 7 = Bug ID (we add the label too since template only has 6 rows).
    requirements_text = _format_requirements(requirements)
    cells = [
        {"range": f"{sheet_id}!B1:B1", "values": [[task_type]]},
        {"range": f"{sheet_id}!B2:B2", "values": [[product]]},
        {"range": f"{sheet_id}!B3:B3", "values": [[version]]},
        {"range": f"{sheet_id}!B4:B4", "values": [[requirements_text]]},
    ]
    if bug_id:
        cells.append({"range": f"{sheet_id}!A7:B7",
                      "values": [["Bug ID：", bug_id]]})
    update_sheet_cells(spreadsheet_token, cells)

    # 4. Rename to final title
    update_wiki_node_title(QA_WIKI_SPACE_ID, node_token, final_title)

    return {
        "wiki_url": f"https://{QA_WIKI_SUBDOMAIN}/wiki/{node_token}",
        "node_token": node_token,
        "doc_token": doc_token,
        "sheet_token": sheet_full_token,
        "title": final_title,
        "bug_id": bug_id,
    }


def list_qa_tickets(owner: str = "", include_template: bool = False) -> list:
    """List all 工单 under the QA team's parent page.

    Each entry is a dict with keys: node_token, obj_token, title, status.
    `status` is derived from the title prefix: 'completed' (完成-), 'cancelled'
    (取消-), or 'active' (no prefix).
    `owner` filter: case-sensitive substring match on the title (e.g. 'alice-claude'
    matches `...alice-claude` titles). Empty owner returns all.
    """
    items = list_wiki_children(QA_WIKI_SPACE_ID, QA_WIKI_PARENT_NODE)
    result = []
    for n in items:
        title = n.get("title", "")
        node_token = n.get("node_token", "")
        if not include_template and node_token == QA_WIKI_TEMPLATE_NODE:
            continue
        if owner and owner not in title:
            continue
        if title.startswith("完成-"):
            status = "completed"
        elif title.startswith("取消-"):
            status = "cancelled"
        else:
            status = "active"
        result.append({
            "node_token": node_token,
            "obj_token": n.get("obj_token", ""),
            "obj_type": n.get("obj_type", ""),
            "title": title,
            "status": status,
            "wiki_url": f"https://{QA_WIKI_SUBDOMAIN}/wiki/{node_token}",
        })
    return result


# ── CLI smoke test ───────────────────────────────────────────────────────

def _cli():
    """Quick smoke test: python feishu_docs.py <document_id>"""
    import textwrap
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        print("Usage: python feishu_docs.py [--profile <name>] <command> [args]")
        print()
        print("Commands:")
        print("  get <doc_id>           — print document metadata + raw text")
        print("  blocks <doc_id>        — print all blocks (JSON)")
        print("  create <title>         — create a new empty document")
        print("  search <query>         — search docs in drive")
        print("  list <folder_token>    — list files in a folder")
        return

    # Skip --profile args
    args = []
    skip = False
    for a in sys.argv[1:]:
        if skip:
            skip = False
            continue
        if a == "--profile":
            skip = True
            continue
        args.append(a)

    if not _APP_ID or not _APP_SECRET:
        print("Error: FEISHU_APP_ID and FEISHU_APP_SECRET must be set",
              flush=True)
        sys.exit(1)

    cmd = args[0] if args else "help"

    if cmd == "get" and len(args) >= 2:
        doc_id = args[1]
        doc = get_document(doc_id)
        print(f"Title: {doc.get('title', '(untitled)')}")
        print(f"Revision: {doc.get('revision_id')}")
        print(f"Create: {doc.get('create_time')}  Update: {doc.get('modify_time')}")
        print("--- raw text ---")
        text = get_raw_text(doc_id)
        print(textwrap.shorten(text, width=2000, placeholder="..."))

    elif cmd == "blocks" and len(args) >= 2:
        blocks = get_blocks(args[1])
        print(json.dumps(blocks, ensure_ascii=False, indent=2))

    elif cmd == "create" and len(args) >= 2:
        title = " ".join(args[1:])
        doc = create_document(title)
        print(f"Created: {doc['document_id']}")
        print(f"Title: {doc.get('title')}")

    elif cmd == "search" and len(args) >= 2:
        query = " ".join(args[1:])
        results = search_docs(query)
        for r in results:
            print(f"  {r.get('docs_token', '?')}  {r.get('title', '?')}")

    elif cmd == "list" and len(args) >= 2:
        files = list_folder(args[1])
        for f in files:
            print(f"  {f.get('token', '?')}  {f.get('type', '?')}  {f.get('name', '?')}")

    else:
        print(f"Unknown command: {cmd}. Run with --help.")


if __name__ == "__main__":
    _cli()

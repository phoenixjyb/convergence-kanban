"""Optional issues sync using acknowledged field snapshots, not timestamps."""

import json
import uuid
from datetime import datetime

from fastapi import HTTPException
from pydantic import ValidationError

from helpers import (
    TZ, generate_issue_display_id, issue_to_dict, log_activity, now_iso,
    validate_issue_values,
)
from models import IssueCreate

TABLE_NAME = "Top Issues"
FIELDS = {
    "title": ("Title", 1),
    "introduction": ("Introduction", 1),
    "content": ("Issue Content", 1),
    "raised_by": ("Raised By", 1),
    "raised_date": ("Raised Date", 5),
    "category": ("Category", 3),
    "priority": ("Priority", 3),
    "rank": ("Rank", 2),
    "owner": ("Owner", 1),
    "due_date": ("Target Date", 5),
    "status": ("Status", 3),
    "resolution_criteria": ("Resolution Criteria", 1),
    "resolution": ("Outcome", 1),
    "project_id": ("Project ID", 1),
    "workstream_id": ("Workstream ID", 1),
    "task_ids": ("Task IDs", 1),
    "bug_ids": ("Bug IDs", 1),
    "deleted_at": ("Archived", 7),
}
OPTIONS = {
    "category": ["hardware", "software", "product_experience", "process", "delivery", "operations", "other"],
    "priority": ["critical", "high", "medium", "low"],
    "status": ["open", "triaged", "in_progress", "blocked", "pending_review", "closed"],
}


def snapshot(row):
    values = {key: row[key] for key in FIELDS}
    values["deleted_at"] = "archived" if row.get("deleted_at") else None
    for key in ("task_ids", "bug_ids"):
        values[key] = sorted(set(values[key]))
    return values


def _text(value):
    if isinstance(value, list):
        return "".join(v.get("text", "") if isinstance(v, dict) else str(v) for v in value)
    return "" if value is None else str(value)


def _date(value):
    if not value:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, TZ).date().isoformat()
    return _text(value)


def from_fields(fields):
    values = {}
    for key, (label, kind) in FIELDS.items():
        raw = fields.get(label)
        if key == "deleted_at":
            if raw not in (None, False, True, 0, 1):
                raise ValueError("Invalid Archived checkbox")
            values[key] = "archived" if raw else None
        elif key in ("task_ids", "bug_ids"):
            values[key] = json.loads(_text(raw) or "[]")
        elif kind == 5:
            values[key] = _date(raw)
        elif key == "rank":
            values[key] = raw or 0
        elif key in ("project_id", "workstream_id"):
            values[key] = _text(raw) or None
        else:
            values[key] = _text(raw)
    for key, default in (("category", "other"), ("priority", "medium"), ("status", "open")):
        values[key] = values[key] or default
    values["raised_date"] = values["raised_date"] or now_iso()[:10]
    validated = IssueCreate.model_validate({k: v for k, v in values.items() if k != "deleted_at"}).model_dump(mode="json")
    return snapshot(validated | {"deleted_at": values["deleted_at"]})


def to_fields(values, iid, display_id):
    result = {"kanban_id": iid, "Issue ID": display_id}
    for key, (label, kind) in FIELDS.items():
        val = values[key]
        if key == "deleted_at":
            val = bool(val)
        elif key in ("task_ids", "bug_ids"):
            val = json.dumps(val)
        elif kind == 5:
            val = int(datetime.strptime(val, "%Y-%m-%d").replace(tzinfo=TZ).timestamp() * 1000) if val else None
        elif val is None:
            val = ""
        result[label] = val
    return result


def _write(transport, table, rid, fields):
    path = f"/bitable/v1/apps/{transport.bt()}/tables/{table}/records"
    response = transport.feishu_api(path + (f"/{rid}" if rid else ""),
                                    method="PUT" if rid else "POST", data={"fields": fields})
    if response.get("code") != 0:
        raise RuntimeError("Feishu issue write failed")
    if rid:
        return rid
    new_id = response.get("data", {}).get("record", {}).get("record_id")
    if not new_id:
        raise RuntimeError("Feishu issue create returned no record ID")
    return new_id


def _apply(db, iid, values, create=False, display_id=None, previous=None):
    ts = now_iso()
    encoded = dict(values)
    encoded["deleted_at"] = ts if encoded["deleted_at"] else None
    for key in ("task_ids", "bug_ids"):
        encoded[key] = json.dumps(encoded[key])
    encoded["updated_at"] = ts
    if create:
        encoded.update(id=iid, display_id=display_id, created_at=ts)
        db.execute(f"INSERT INTO issues ({','.join(encoded)}) VALUES ({','.join('?' for _ in encoded)})", list(encoded.values()))
    else:
        # Guard against an API edit made while a Feishu request was in flight.
        # Compare actual values, since second-resolution timestamps can collide.
        guards = {key: previous[key] for key in FIELDS} if previous else {}
        for key in ("task_ids", "bug_ids"):
            if key in guards:
                guards[key] = json.dumps(guards[key])
        condition = " AND " + " AND ".join(k + " IS ?" for k in guards) if guards else ""
        cur = db.execute(f"UPDATE issues SET {','.join(k+'=?' for k in encoded)} WHERE id=?" + condition,
                         [*encoded.values(), iid, *guards.values()])
        if not cur.rowcount:
            raise RuntimeError("Issue changed locally while syncing; retry next cycle")
    log_activity(db, "issue", iid, "synced_from_feishu", "feishu-sync")


def _conflict(db, iid, field, local, remote):
    encode = lambda value: json.dumps(value) if isinstance(value, list) else str(value or "")
    lv, rv = encode(local), encode(remote)
    existing = db.execute(
        "SELECT id FROM sync_conflicts WHERE entity_type='issue' AND entity_id=? AND field_name=? AND resolved=0",
        (iid, field),
    ).fetchone()
    if existing:
        db.execute("UPDATE sync_conflicts SET local_value=?,remote_value=? WHERE id=?", (lv, rv, existing["id"]))
    else:
        db.execute(
            "INSERT INTO sync_conflicts (id,entity_type,entity_id,field_name,local_value,remote_value) VALUES (?,'issue',?,?,?,?)",
            (uuid.uuid4().hex, iid, field, lv, rv),
        )


def sync_issues(db, transport):
    """Advance baselines only after acknowledged writes. Archive is explicit."""
    table = transport._state.get("issues_table")
    stats = {"pushed": 0, "pulled": 0, "conflicts": 0, "errors": 0}
    if not table:
        return stats
    records, complete = transport.list_records(table)
    # A partial read is neither evidence of deletion nor safe for creation.
    if not complete:
        stats["errors"] += 1
        transport._state["issues_last_cycle"] = {"at": now_iso(), **stats}
        transport.save_state()
        return stats
    baselines = transport._state.setdefault("issues_baselines", {})
    timestamps = transport._state.setdefault("last_sync_ts_issues", {})
    local = {r["id"]: issue_to_dict(r) for r in db.execute("SELECT * FROM issues").fetchall()}
    record_counts = {}
    for record in records:
        key = _text(record.get("fields", {}).get("kanban_id"))
        if key:
            record_counts[key] = record_counts.get(key, 0) + 1
    seen = set()
    for record in records:
        fields = record.get("fields", {})
        iid = _text(fields.get("kanban_id"))
        rid = record["record_id"]
        if iid and record_counts[iid] > 1:
            seen.add(iid)
            stats["errors"] += 1
            continue
        seen.add(iid)
        try:
            remote = from_fields(fields)
            validate_issue_values(db, remote, previous=local.get(iid))
            if not iid or iid not in local:
                if iid in baselines:
                    # Never recreate an entity locally after its history is lost.
                    stats["errors"] += 1
                    continue
                iid = iid or uuid.uuid4().hex[:12]
                display = generate_issue_display_id(db)
                _apply(db, iid, remote, create=True, display_id=display)
                _write(transport, table, rid, to_fields(remote, iid, display))
                db.commit()
                local[iid] = issue_to_dict(db.execute("SELECT * FROM issues WHERE id=?", (iid,)).fetchone())
                seen.add(iid)
                baselines[iid] = remote
                timestamps[iid] = now_iso()
                stats["pulled"] += 1
                transport.save_state()
                continue
            current = snapshot(local[iid])
            base = baselines.get(iid)
            merged = dict(current)
            conflicts = []
            for key in FIELDS:
                lv, rv = current[key], remote[key]
                if lv == rv:
                    continue
                if base is None or (lv != base[key] and rv != base[key]):
                    resolved = db.execute(
                        "SELECT local_value,remote_value FROM sync_conflicts WHERE entity_type='issue' "
                        "AND entity_id=? AND field_name=? AND resolved=1 ORDER BY resolved_at DESC LIMIT 1",
                        (iid, key),
                    ).fetchone()
                    encode = lambda value: json.dumps(value) if isinstance(value, list) else str(value or "")
                    if resolved and resolved["local_value"] == encode(lv) and resolved["remote_value"] == encode(rv):
                        continue
                    conflicts.append(key)
                    _conflict(db, iid, key, lv, rv)
                elif lv == base[key]:
                    merged[key] = rv
            if conflicts:
                # Keep the whole baseline until a human resolves conflicting
                # fields. Disjoint edits can be merged on the following cycle.
                db.commit()
                stats["conflicts"] += len(conflicts)
                continue
            validate_issue_values(db, merged, previous=local[iid])
            if merged != remote or _text(fields.get("Issue ID")) != local[iid]["display_id"]:
                _write(transport, table, rid, to_fields(merged, iid, local[iid]["display_id"]))
                stats["pushed"] += 1
            if merged != current:
                _apply(db, iid, merged, previous=local[iid])
                stats["pulled"] += 1
            db.commit()
            baselines[iid] = merged
            timestamps[iid] = now_iso()
            transport.save_state()
        except (ValueError, TypeError, OverflowError, OSError, ValidationError, HTTPException, RuntimeError) as exc:
            db.rollback()
            stats["errors"] += 1
            print(f"[sync-issues] rejected record {rid}: {type(exc).__name__}", flush=True)

    for iid, row in local.items():
        if iid in seen:
            continue
        if iid in baselines:
            # Missing remote records require operator attention; use Archived
            # for reversible deletion instead of inferring intent from absence.
            stats["errors"] += 1
            continue
        try:
            current = snapshot(row)
            _write(transport, table, None, to_fields(current, iid, row["display_id"]))
            baselines[iid] = current
            timestamps[iid] = now_iso()
            transport.save_state()
            stats["pushed"] += 1
        except RuntimeError:
            stats["errors"] += 1
    transport._state["issues_last_cycle"] = {"at": now_iso(), **stats}
    transport.save_state()
    return stats

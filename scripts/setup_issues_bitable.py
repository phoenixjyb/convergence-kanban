"""Provision the optional Top Issues table. Defaults to a local schema preview."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from feishu_issues import FIELDS, OPTIONS, TABLE_NAME


def provision(transport):
    token = transport.bt()
    if not token:
        raise RuntimeError("Run the existing Feishu setup first; no Bitable app is configured")

    def request(path, method="GET", data=None):
        result = transport.feishu_api(f"/bitable/v1/apps/{token}" + path, method=method, data=data)
        if result.get("code") != 0:
            raise RuntimeError("Feishu table/schema request failed")
        return result.get("data", {})

    configured = transport._state.get("issues_table")
    if configured:
        tid = configured
    else:
        tables = []
        page = ""
        while True:
            data = request("/tables?page_size=100" + (f"&page_token={page}" if page else ""))
            tables.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page = data["page_token"]
        matches = [t for t in tables if t.get("name") == TABLE_NAME]
        if len(matches) > 1:
            raise RuntimeError("More than one Top Issues table exists; select one in the sync profile")
        tid = matches[0]["table_id"] if matches else request("/tables", "POST", {"table": {"name": TABLE_NAME}})["table_id"]

    fields = []
    page = ""
    while True:
        data = request(f"/tables/{tid}/fields?page_size=100" + (f"&page_token={page}" if page else ""))
        fields.extend(data.get("items", []))
        if not data.get("has_more"):
            break
        page = data["page_token"]
    by_name = {f["field_name"]: f for f in fields}
    if "Title" not in by_name:
        primary = next((f for f in fields if f.get("is_primary")), None)
        if primary:
            request(f"/tables/{tid}/fields/{primary['field_id']}", "PUT", {"field_name": "Title", "type": 1})
            by_name["Title"] = primary | {"type": 1}
    wanted = dict(FIELDS) | {"display_id": ("Issue ID", 1), "id": ("kanban_id", 1)}
    for key, (name, kind) in wanted.items():
        payload = {"field_name": name, "type": kind}
        if key in OPTIONS:
            old = by_name.get(name, {}).get("property", {}).get("options", [])
            names = {o.get("name") for o in old}
            payload["property"] = {"options": old + [{"name": v} for v in OPTIONS[key] if v not in names]}
        if name not in by_name:
            request(f"/tables/{tid}/fields", "POST", payload)
        elif by_name[name]["type"] != kind:
            raise RuntimeError(f"Existing {name} field has an incompatible type; no conversion performed")
        elif key in OPTIONS and payload["property"]["options"] != by_name[name].get("property", {}).get("options", []):
            request(f"/tables/{tid}/fields/{by_name[name]['field_id']}", "PUT", payload)
    transport._state["issues_table"] = tid
    transport.save_state()
    return tid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="default")
    parser.add_argument("--apply", action="store_true", help="Create/extend the live Bitable schema")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"table": TABLE_NAME, "fields": FIELDS, "options": OPTIONS}, indent=2, ensure_ascii=False))
        print("Preview only. Use --apply with the intended deployment profile to provision.")
        return
    # Import only in explicit apply mode; the preview never loads credentials.
    sys.argv = [sys.argv[0], "--profile", args.profile]
    import feishu_sync
    feishu_sync.load_state()
    provision(feishu_sync)
    print("Top Issues table is ready and enabled for this sync profile.")


if __name__ == "__main__":
    main()

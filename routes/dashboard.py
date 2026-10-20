"""Dashboard summary endpoint."""

from fastapi import APIRouter

from db import derive_workstream_state, get_db

router = APIRouter(prefix="/api", tags=["dashboard"])


@router.get("/dashboard")
def dashboard():
    with get_db() as conn:
        projects = conn.execute("SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY sort_order, name_en").fetchall()
        all_ws = conn.execute("SELECT * FROM workstreams WHERE deleted_at IS NULL ORDER BY sort_order, title_en").fetchall()
        all_tasks = conn.execute("SELECT * FROM tasks WHERE deleted_at IS NULL ORDER BY sort_order").fetchall()
        all_blockers = conn.execute("SELECT * FROM blockers WHERE resolved=0 AND deleted_at IS NULL").fetchall()
        sub_counts = conn.execute(
            "SELECT parent_task_id, count(*) c, sum(CASE WHEN status IN ('done','abandoned') THEN 1 ELSE 0 END) done "
            "FROM tasks WHERE parent_task_id IS NOT NULL AND deleted_at IS NULL GROUP BY parent_task_id"
        ).fetchall()

        ws_by_project = {}
        for ws in all_ws:
            ws_by_project.setdefault(ws["project_id"], []).append(ws)
        tasks_by_ws = {}
        for t in all_tasks:
            tasks_by_ws.setdefault(t["workstream_id"], []).append(t)
        blockers_by_ws = {}
        for b in all_blockers:
            blockers_by_ws.setdefault(b["workstream_id"], []).append(b)
        sub_map = {r["parent_task_id"]: {"c": r["c"], "done": r["done"] or 0} for r in sub_counts}

        dep_rows = conn.execute(
            "SELECT td.task_id, td.depends_on_id, td.dep_type, t.title_en as dep_title, t.status as dep_status "
            "FROM task_dependencies td JOIN tasks t ON t.id=td.depends_on_id WHERE t.deleted_at IS NULL"
        ).fetchall()
        deps_by_task = {}
        for d in dep_rows:
            deps_by_task.setdefault(d["task_id"], []).append(
                {"dep_title": d["dep_title"], "dep_status": d["dep_status"], "dep_type": d["dep_type"]})

        time_rows = conn.execute("SELECT task_id, sum(minutes) m FROM time_entries GROUP BY task_id").fetchall()
        time_by_task = {r["task_id"]: r["m"] for r in time_rows}

        attach_rows = conn.execute(
            "SELECT entity_id, count(*) c FROM attachments "
            "WHERE entity_type='task' AND deleted_at IS NULL GROUP BY entity_id"
        ).fetchall()
        attach_by_task = {r["entity_id"]: r["c"] for r in attach_rows}

        result = []
        for p in projects:
            pid = p["id"]
            ws_list = []
            for ws in ws_by_project.get(pid, []):
                wid = ws["id"]
                tasks = tasks_by_ws.get(wid, [])
                blockers = blockers_by_ws.get(wid, [])
                task_state = derive_workstream_state(t["status"] for t in tasks)
                top_tasks = [t for t in tasks if not t["parent_task_id"]]
                task_list = []
                for t in top_tasks:
                    td = dict(t)
                    sc = sub_map.get(td["id"], {"c": 0, "done": 0})
                    td["subtask_count"] = sc["c"]
                    td["subtask_done"] = sc["done"]
                    td["dependencies"] = deps_by_task.get(td["id"], [])
                    td["time_logged"] = time_by_task.get(td["id"], 0)
                    td["attachment_count"] = attach_by_task.get(td["id"], 0)
                    task_list.append(td)
                ws_list.append({
                    **dict(ws),
                    "status": task_state["status"],
                    "status_source": task_state["status_source"],
                    "tasks": task_list,
                    "blockers": [dict(b) for b in blockers],
                    "task_stats": task_state,
                })
            total_tasks = sum(ws["task_stats"]["total"] for ws in ws_list)
            done_tasks = sum(ws["task_stats"]["done"] for ws in ws_list)
            result.append({
                **dict(p),
                "workstreams": ws_list,
                "stats": {
                    "total": len(ws_list),
                    "done": sum(1 for w in ws_list if w["status"] == "done"),
                    "in_progress": sum(1 for w in ws_list if w["status"] == "in-progress"),
                    "blocked": sum(1 for w in ws_list if w["status"] == "blocked"),
                },
                "task_progress": {
                    "total": total_tasks,
                    "done": done_tasks,
                    "pct": int(done_tasks / total_tasks * 100) if total_tasks else 0,
                },
            })
        return result

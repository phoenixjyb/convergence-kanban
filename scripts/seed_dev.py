"""Seed a dev database with realistic test data."""

import json
import os
import sys
import uuid
from datetime import datetime, timedelta

# Must set before importing db
os.environ.setdefault("KANBAN_DATA_DIR", "data/dev")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db import get_db, init_db, DATA_DIR

TZ_OFFSET = timedelta(hours=8)


def now_iso():
    return (datetime.utcnow() + TZ_OFFSET).strftime("%Y-%m-%d %H:%M:%S")


def days_ago(n):
    return (datetime.utcnow() + TZ_OFFSET - timedelta(days=n)).strftime("%Y-%m-%d %H:%M:%S")


def date_ago(n):
    return (datetime.utcnow() + TZ_OFFSET - timedelta(days=n)).strftime("%Y-%m-%d")


def uid():
    return uuid.uuid4().hex[:8]


def seed():
    print(f"Seeding dev DB at {DATA_DIR}/kanban.db ...")
    init_db()

    with get_db() as db:
        # Check if already seeded
        count = db.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count > 0:
            print(f"  DB already has {count} projects — skipping seed.")
            print("  Delete data/dev/kanban.db to re-seed.")
            return

        # ── Users ─────────────────────────────────────────────────────
        users = [
            ("u1", "alice", "Alice Wang", "", "human"),
            ("u2", "bob", "Bob Li", "", "human"),
            ("u3", "claude-code", "Claude Code", "", "bot"),
        ]
        for u in users:
            db.execute(
                "INSERT INTO users (id, name, display_name, feishu_open_id, role) "
                "VALUES (?, ?, ?, ?, ?)", u
            )
        print("  3 users created")

        # ── Projects ──────────────────────────────────────────────────
        projects = [
            ("p1", "Demo Project", "示例项目", "Sample seed project", "#6366f1", 0),
            ("p2", "Planning & Control", "规划控制", "Motion planning", "#f59e0b", 1),
            ("p3", "SLAM & Mapping", "建图定位", "Localization & mapping", "#10b981", 2),
        ]
        for p in projects:
            db.execute(
                "INSERT INTO projects (id, name_en, name_zh, description, color, sort_order, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (*p, days_ago(30), now_iso())
            )
        print("  3 projects created")

        # ── Workstreams ───────────────────────────────────────────────
        workstreams = [
            ("ws1", "p1", "Video Streaming", "视频流", "alice", "high", "in-progress"),
            ("ws2", "p1", "Gamepad Control", "手柄控制", "bob", "medium", "in-progress"),
            ("ws3", "p2", "Path Following", "循迹", "alice", "critical", "in-progress"),
            ("ws4", "p2", "Obstacle Avoidance", "避障", "bob", "medium", "planned"),
            ("ws5", "p3", "Map Building", "建图", "alice", "high", "in-progress"),
        ]
        for ws in workstreams:
            db.execute(
                "INSERT INTO workstreams (id, project_id, title_en, title_zh, owner, priority, "
                "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*ws, days_ago(25), now_iso())
            )
        print("  5 workstreams created")

        # ── Tasks ─────────────────────────────────────────────────────
        tasks = [
            # ws1 — Video Streaming
            ("t01", "ws1", "RTSP stream setup", "RTSP流搭建", "alice", "done", date_ago(10), date_ago(5)),
            ("t02", "ws1", "Latency optimization", "延迟优化", "alice", "doing", date_ago(5), date_ago(0)),
            ("t03", "ws1", "Multi-camera support", "多摄像头支持", "bob", "todo", None, date_ago(-7)),
            ("t04", "ws1", "Video recording", "视频录制", "", "todo", None, date_ago(-14)),
            # ws2 — Gamepad
            ("t05", "ws2", "Xbox controller mapping", "Xbox手柄映射", "bob", "done", date_ago(15), date_ago(8)),
            ("t06", "ws2", "Sensitivity calibration", "灵敏度校准", "bob", "in_review", date_ago(3), date_ago(0)),
            ("t07", "ws2", "Haptic feedback", "触觉反馈", "", "todo", None, date_ago(-10)),
            # ws3 — Path Following
            ("t08", "ws3", "Waypoint navigation", "航点导航", "alice", "doing", date_ago(7), date_ago(-3)),
            ("t09", "ws3", "GPS integration", "GPS集成", "alice", "blocked", date_ago(4), date_ago(-2)),
            ("t10", "ws3", "Route optimization", "路径优化", "", "todo", None, date_ago(-14)),
            # ws4 — Obstacle Avoidance
            ("t11", "ws4", "LiDAR point cloud processing", "激光雷达点云处理", "bob", "todo", None, date_ago(-10)),
            ("t12", "ws4", "Emergency stop logic", "急停逻辑", "", "todo", None, date_ago(-7)),
            # ws5 — Map Building
            ("t13", "ws5", "SLAM algorithm integration", "SLAM算法集成", "alice", "doing", date_ago(12), date_ago(-5)),
            ("t14", "ws5", "Map export format", "地图导出格式", "alice", "done", date_ago(20), date_ago(3)),
            ("t15", "ws5", "Real-time map update", "实时地图更新", "bob", "todo", None, date_ago(-14)),
            # Overdue tasks (for alert testing)
            ("t16", "ws1", "Fix frame drop issue", "修复丢帧问题", "bob", "doing", date_ago(8), date_ago(2)),
            ("t17", "ws3", "Calibrate compass sensor", "校准罗盘传感器", "alice", "todo", None, date_ago(1)),
            # Stale task (doing for a long time, no updates)
            ("t18", "ws2", "Bluetooth pairing flow", "蓝牙配对流程", "bob", "doing", date_ago(10), date_ago(-5)),
            ("t19", "ws5", "Indoor positioning fallback", "室内定位降级方案", "alice", "in_review", date_ago(5), date_ago(0)),
            ("t20", "ws4", "Depth camera calibration", "深度摄像头标定", "", "todo", None, date_ago(-21)),
        ]
        for t in tasks:
            db.execute(
                "INSERT INTO tasks (id, workstream_id, title_en, title_zh, assignee, status, "
                "start_date, due_date, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*t, days_ago(20), now_iso())
            )
        print("  20 tasks created")

        # ── Blockers ──────────────────────────────────────────────────
        blockers = [
            ("b1", "ws3", "GPS module not arriving until next week", "GPS模块下周才到", 0, days_ago(3)),
            ("b2", "ws1", "Server GPU driver crash under load", "服务器GPU驱动在负载下崩溃", 0, days_ago(5)),
            ("b3", "ws5", "LiDAR sensor firmware update pending", "激光雷达固件更新等待中", 1, days_ago(10)),
            ("b4", "ws2", "Waiting for USB adapter shipment", "等待USB适配器发货", 0, days_ago(1)),
        ]
        for bl in blockers:
            db.execute(
                "INSERT INTO blockers (id, workstream_id, description_en, description_zh, "
                "resolved, created_at) VALUES (?, ?, ?, ?, ?, ?)", bl
            )
        print("  4 blockers created")

        # ── Bugs ──────────────────────────────────────────────────────
        bugs = [
            ("bug1", "Video freezes after 30min", "high", "open", "alice", "bob", "p1", "遥控功能", "100%"),
            ("bug2", "Gamepad disconnects randomly", "medium", "fixing", "bob", "bob", "p1", "遥控功能", "sometimes"),
            ("bug3", "Path deviation >2m on turns", "critical", "investigating", "alice", "alice", "p2", "循迹", "always"),
            ("bug4", "Map tiles fail to load offline", "medium", "open", "bob", "", "p3", "地图", "50%"),
            ("bug5", "Compass reading drift", "low", "resolved", "alice", "alice", "p2", "定位", "rare"),
            ("bug6", "Emergency stop delayed 500ms", "critical", "open", "bob", "", "p2", "基础功能", "100%"),
        ]
        for bg in bugs:
            db.execute(
                "INSERT INTO bugs (id, title, severity, status, reporter, assignee, "
                "project_id, feature, repro_rate, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*bg, days_ago(7), now_iso())
            )
        # Bug-task links
        for bug_id, task_id in [("bug1", "t02"), ("bug2", "t06"), ("bug3", "t08"),
                                 ("bug4", "t15"), ("bug6", "t12")]:
            db.execute("INSERT INTO bug_task_links (bug_id, task_id) VALUES (?, ?)",
                       (bug_id, task_id))
        print("  6 bugs created (5 with task links)")

        # ── Time entries ──────────────────────────────────────────────
        for tid, user, mins in [("t01", "alice", 120), ("t02", "alice", 90),
                                 ("t05", "bob", 180), ("t08", "alice", 60),
                                 ("t13", "alice", 240), ("t14", "alice", 150)]:
            db.execute(
                "INSERT INTO time_entries (id, task_id, user_name, minutes, description, date) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid(), tid, user, mins, f"Work on {tid}", date_ago(3))
            )
        print("  6 time entries created")

        # ── Comments ──────────────────────────────────────────────────
        comments = [
            ("task", "t02", "alice", "Reduced latency from 200ms to 80ms"),
            ("task", "t06", "bob", "Ready for review — tested on 3 controllers"),
            ("task", "t08", "alice", "Waypoint following works, need to test with GPS"),
            ("bug", "bug3", "alice", "Investigating — may be a PID tuning issue"),
            ("task", "t13", "claude-code", "[claude-code] Refactored SLAM pipeline interface"),
        ]
        for et, eid, author, body in comments:
            db.execute(
                "INSERT INTO comments (id, entity_type, entity_id, author, body, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (uid(), et, eid, author, body, days_ago(2))
            )
        print("  5 comments created")

        # ── Activity log ──────────────────────────────────────────────
        for i, (etype, eid, actor, action, detail) in enumerate([
            ("task", "t01", "alice", "updated", "status → done"),
            ("task", "t02", "alice", "updated", "status → doing"),
            ("task", "t05", "bob", "updated", "status → done"),
            ("task", "t06", "bob", "updated", "status → in_review"),
            ("bug", "bug3", "alice", "created", "Path deviation >2m on turns"),
            ("blocker", "b1", "alice", "created", "GPS module not arriving"),
            ("task", "t13", "claude-code", "updated", "status → doing"),
            ("task", "t08", "alice", "updated", "status → doing"),
        ]):
            db.execute(
                "INSERT INTO activity_log (entity_type, entity_id, actor, action, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (etype, eid, actor, action, detail, days_ago(7 - i))
            )
        print("  8 activity log entries created")

        # ── Snapshots (7 days) ────────────────────────────────────────
        for day_offset in range(7, 0, -1):
            done_count = 3 + (7 - day_offset)  # gradually more done
            snap_data = {
                "global": {
                    "total": 20, "todo": 8 - (7 - day_offset) // 2,
                    "doing": 4, "in_review": 1 + (7 - day_offset) // 3,
                    "done": min(done_count, 8), "blocked": 1
                },
                "projects": {
                    "p1": {"total": 7, "done": min(2 + (7 - day_offset) // 3, 4)},
                    "p2": {"total": 6, "done": min(1 + (7 - day_offset) // 4, 3)},
                    "p3": {"total": 5, "done": min(1 + (7 - day_offset) // 3, 3)},
                }
            }
            db.execute(
                "INSERT INTO snapshots (id, date, data, created_at) VALUES (?, ?, ?, ?)",
                (uid(), date_ago(day_offset), json.dumps(snap_data), days_ago(day_offset))
            )
        print("  7 daily snapshots created")

        db.commit()
        print("\nDev DB seeded successfully!")
        print(f"Run: bash dev.sh")


if __name__ == "__main__":
    seed()

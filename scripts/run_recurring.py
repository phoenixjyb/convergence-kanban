#!/usr/bin/env python3
"""
Trigger recurring task creation.
Run via cron every morning (e.g., 08:00 UTC+8).

Usage:
    KANBAN_DATA_DIR=data python scripts/run_recurring.py

Crontab example (on the server):
    0 8 * * * cd /opt/convergence-kanban && venv/bin/python scripts/run_recurring.py
"""

import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routes.recurring import check_recurring_tasks


def main():
    created = check_recurring_tasks()
    if created:
        print(f"[recurring] Created {len(created)} task(s): {', '.join(created)}")
    else:
        print("[recurring] No tasks due today.")


if __name__ == "__main__":
    main()

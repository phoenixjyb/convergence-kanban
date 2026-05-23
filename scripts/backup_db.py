#!/usr/bin/env python3
"""
Backup ConvergenceKanban SQLite database.
Creates timestamped copies with optional rotation.

Usage:
    KANBAN_DATA_DIR=data python scripts/backup_db.py
    KANBAN_DATA_DIR=data python scripts/backup_db.py --keep 7
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DATA_DIR = os.getenv("KANBAN_DATA_DIR", "data")
DB_PATH = Path(DATA_DIR) / "kanban.db"
BACKUP_DIR = Path(DATA_DIR) / "backups"
KEEP = 30  # default: keep last 30 backups

for i, arg in enumerate(sys.argv):
    if arg == "--keep" and i + 1 < len(sys.argv):
        KEEP = int(sys.argv[i + 1])


def main():
    if not DB_PATH.exists():
        print(f"Database not found: {DB_PATH}")
        sys.exit(1)

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"kanban_{timestamp}.db"

    # Use SQLite online backup API for consistency (handles WAL mode)
    src = sqlite3.connect(str(DB_PATH))
    dst = sqlite3.connect(str(backup_path))
    src.backup(dst)
    dst.close()
    src.close()

    size_mb = backup_path.stat().st_size / (1024 * 1024)
    print(f"Backup created: {backup_path} ({size_mb:.1f} MB)")

    # Rotate old backups
    backups = sorted(BACKUP_DIR.glob("kanban_*.db"))
    if len(backups) > KEEP:
        to_remove = backups[:len(backups) - KEEP]
        for old in to_remove:
            old.unlink()
            print(f"Removed old backup: {old.name}")

    print(f"Total backups: {len(list(BACKUP_DIR.glob('kanban_*.db')))}/{KEEP}")


if __name__ == "__main__":
    main()

"""Nightly SQLite backup (goal 8) — WAL-safe online `.backup` to a second on-disk path.

Uses the sqlite3 online backup API (checkpoints WAL cleanly, no lock-and-copy race),
writes a timestamped copy under /data/backups, and prunes to the most recent N.
Off-box copies are explicitly out of scope (goal-8 lock: overlay data is recreatable).

Run from the app container via host cron:
    docker compose exec -T app uv run python scripts/backup.py
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

KEEP = int(os.environ.get("BACKUP_KEEP", "14"))


def _db_path() -> Path:
    url = os.environ.get("DATABASE_URL", "sqlite:////data/overlay.db")
    if not url.startswith("sqlite"):
        raise SystemExit(f"backup.py only supports SQLite (got {url!r})")
    # sqlite:////abs/path → /abs/path ; sqlite:///rel/path → rel/path
    return Path(url.split("sqlite:///", 1)[1])


def main() -> None:
    src = _db_path()
    if not src.exists():
        raise SystemExit(f"database not found at {src}")
    backups = src.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = backups / f"{src.stem}-{stamp}.db"

    with sqlite3.connect(src) as source, sqlite3.connect(dest) as target:
        source.backup(target)
    print(f"backup written: {dest}")

    copies = sorted(backups.glob(f"{src.stem}-*.db"))
    for old in copies[:-KEEP]:
        old.unlink()
        print(f"pruned: {old}")


if __name__ == "__main__":
    main()

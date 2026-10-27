"""Consistent SQLite snapshots (online backup API, safe while the worker writes), keeping
the newest N. On Postgres, use the provider's automated backups / pg_dump instead."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import settings


def backup_sqlite(keep: int = 14) -> Path | None:
    if not settings.database_url.startswith("sqlite"):
        return None
    src_path = settings.database_url.split("sqlite:///", 1)[1]
    backup_dir = Path(src_path).parent / "backups"  # next to the DB, i.e. on the persistent disk
    backup_dir.mkdir(parents=True, exist_ok=True)
    dest = backup_dir / f"gradient-{datetime.now(timezone.utc):%Y%m%d-%H%M}.db"
    with sqlite3.connect(src_path) as src, sqlite3.connect(dest) as dst:
        src.backup(dst)
    for old in sorted(backup_dir.glob("gradient-*.db"))[:-keep]:
        old.unlink()
    return dest


def restore_sqlite(snapshot: Path) -> None:
    """Restore a snapshot over the live DB. Stop the API and worker first."""
    target = settings.database_url.split("sqlite:///", 1)[1]
    with sqlite3.connect(snapshot) as src, sqlite3.connect(target) as dst:
        src.backup(dst)

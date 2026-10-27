"""Copy a Gradient SQLite database into Postgres (e.g. Neon) so a new deploy starts full.

    python scripts/sqlite_to_postgres.py data/gradient.db "postgresql+psycopg://USER:PASS@HOST/DB?sslmode=require"

Creates the schema on the target, copies boards, jobs, runs and source runs in batches, then
fixes the id sequences. Refuses to run if the target already has jobs (no accidental overwrite).
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

if len(sys.argv) != 3:
    sys.exit(__doc__)
SOURCE, TARGET = sys.argv[1], sys.argv[2]
os.environ["GRADIENT_DATABASE_URL"] = TARGET  # must be set before gradient modules load settings
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import bindparam, create_engine, func, select, text  # noqa: E402

from gradient.db import engine as target, init_db  # noqa: E402
from gradient.models import Board, Job, ScrapeRun, SourceRun  # noqa: E402

BATCH = 1000


def utc(row: dict) -> dict:
    # SQLite hands back naive datetimes; Postgres timestamptz would read them as server-local time.
    return {k: (v.replace(tzinfo=timezone.utc) if isinstance(v, datetime) and v.tzinfo is None else v) for k, v in row.items()}


def main() -> None:
    init_db()
    with target.connect() as conn:
        existing = conn.execute(select(func.count()).select_from(Job.__table__)).scalar()
    if existing:
        sys.exit(f"Target already has {existing} jobs — refusing to overwrite. Use an empty database.")

    source = create_engine(f"sqlite:///{Path(SOURCE).resolve().as_posix()}")
    # Parents before children (jobs.duplicate_of references jobs, source_runs references scrape_runs).
    for model in (Board, ScrapeRun, SourceRun, Job):
        table = model.__table__
        order = table.c.id
        copied = 0
        links: list[dict] = []
        with source.connect() as src, target.begin() as dst:
            result = src.execute(select(table).order_by(order)).mappings()
            while rows := result.fetchmany(BATCH):
                payload = [utc(dict(r)) for r in rows]
                if model is Job:  # a duplicate may point at a later row: insert all rows, then link
                    links += [{"jid": r["id"], "dup": r["duplicate_of"]} for r in payload if r["duplicate_of"]]
                    for r in payload:
                        r["duplicate_of"] = None
                dst.execute(table.insert(), payload)
                copied += len(payload)
            if links:
                dst.execute(table.update().where(table.c.id == bindparam("jid")).values(duplicate_of=bindparam("dup")), links)
            if target.dialect.name == "postgresql":
                dst.execute(text(f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), COALESCE(MAX(id), 1)) FROM {table.name}"))
        print(f"{table.name:12} {copied:>7} rows")

    with target.connect() as conn:
        open_jobs = conn.execute(select(func.count()).select_from(Job.__table__).where(Job.status == "open")).scalar()
    print(f"done — {open_jobs} open jobs in target")


if __name__ == "__main__":
    main()

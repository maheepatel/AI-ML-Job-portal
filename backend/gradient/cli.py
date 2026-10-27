"""python -m gradient.cli <command>

  scrape [--only greenhouse,linkedin] [--no-liveness]   one full pipeline run
  liveness [--limit N]                                    URL re-checks only
  worker                                                  scheduler: scrape every N hours
  serve [--port 8270]                                     API + built frontend
  profile <resume.pdf>                                    build data/profile.json for /for-me
  stats                                                   quick DB summary
  rescore                                                 re-apply trust rules + dedupe to every stored job
  backup | restore <snapshot.db>                          SQLite snapshots in data/backups
"""

import argparse
import asyncio
import json
import logging
import os

from .config import settings


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(prog="gradient")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scrape")
    sc.add_argument("--only", help="comma-separated source names or keys")
    sc.add_argument("--no-liveness", action="store_true")
    lv = sub.add_parser("liveness")
    lv.add_argument("--limit", type=int, default=settings.liveness_batch)
    sub.add_parser("worker")
    sv = sub.add_parser("serve")
    sv.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8270)))  # PaaS hosts inject PORT
    sv.add_argument("--host", default="127.0.0.1")
    pf = sub.add_parser("profile")
    pf.add_argument("pdf")
    sub.add_parser("stats")
    sub.add_parser("rescore")
    sub.add_parser("backup")
    rs = sub.add_parser("restore")
    rs.add_argument("snapshot")
    args = ap.parse_args()

    if args.cmd == "scrape":
        from .ingest.pipeline import run_pipeline

        only = set(args.only.split(",")) if args.only else None
        print(json.dumps(asyncio.run(run_pipeline("manual", only, not args.no_liveness)), indent=2, default=str))
    elif args.cmd == "liveness":
        from .db import init_db
        from .ingest.base import Http
        from .ingest.liveness import run_liveness

        init_db()
        r = asyncio.run(run_liveness(Http(), args.limit))
        print({k: v for k, v in r.items() if k != "closed_fps"})
    elif args.cmd == "worker":
        from .worker import run_worker

        run_worker()
    elif args.cmd == "serve":
        import uvicorn

        uvicorn.run("gradient.api.app:app", host=args.host, port=args.port)
    elif args.cmd == "profile":
        from pathlib import Path

        from .domain.matching import profile_from_pdf

        profile = profile_from_pdf(Path(args.pdf).read_bytes())
        settings.profile_file.parent.mkdir(parents=True, exist_ok=True)
        settings.profile_file.write_text(json.dumps(profile, indent=2))
        print(json.dumps(profile, indent=2))
    elif args.cmd == "rescore":
        from sqlalchemy import select

        from .db import init_db, session_scope
        from .ingest.pipeline import dedupe_and_score
        from .models import Job

        init_db()
        with session_scope() as s:
            fps = set(s.scalars(select(Job.fingerprint).distinct()))
            dedupe_and_score(s, fps)
        print(f"rescored {len(fps)} fingerprints")
    elif args.cmd == "backup":
        from .backup import backup_sqlite

        print(backup_sqlite() or "not SQLite — use your Postgres provider's backups")
    elif args.cmd == "restore":
        from pathlib import Path

        from .backup import restore_sqlite

        restore_sqlite(Path(args.snapshot))
        print("restored", args.snapshot)
    elif args.cmd == "stats":
        from sqlalchemy import func, select

        from .db import init_db, session_scope
        from .models import Board, Job

        init_db()
        with session_scope() as s:
            by = s.execute(select(Job.status, Job.source, func.count()).group_by(Job.status, Job.source)).all()
            boards = s.execute(select(Board.enabled, func.count()).group_by(Board.enabled)).all()
        for row in sorted(by):
            print(*row)
        print("boards:", dict(boards))


if __name__ == "__main__":
    main()

"""Long-running scheduler: one full pipeline run every N hours, aligned to the clock in IST
(00:00, 04:00, 08:00 … by default). Catches up immediately if the last run is overdue."""

import asyncio
import logging
from datetime import timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import func, select

from .backup import backup_sqlite
from .config import settings
from .db import aware, init_db, session_scope, utcnow
from .ingest.pipeline import run_pipeline
from .models import ScrapeRun

log = logging.getLogger("gradient.worker")


def _job() -> None:
    try:
        asyncio.run(run_pipeline("schedule"))
    except Exception:
        log.exception("scheduled run failed")


def _backup() -> None:
    try:
        log.info("backup written: %s", backup_sqlite())
    except Exception:
        log.exception("backup failed")


def _overdue() -> bool:
    with session_scope() as s:
        last = s.scalar(select(func.max(ScrapeRun.finished_at)).where(ScrapeRun.status != "failed"))
    return last is None or utcnow() - aware(last) > timedelta(hours=settings.scrape_interval_hours)


def build_scheduler(sched: BaseScheduler) -> BaseScheduler:
    sched.add_job(
        _job, CronTrigger(hour=f"*/{settings.scrape_interval_hours}", minute=0, timezone="Asia/Kolkata"),
        id="scrape", max_instances=1, coalesce=True, misfire_grace_time=3600,
    )
    sched.add_job(_backup, CronTrigger(hour=3, minute=30, timezone="Asia/Kolkata"), id="backup", max_instances=1)
    if settings.run_on_start or _overdue():
        log.info("last run is overdue — starting one now")
        sched.add_job(_job, id="catch-up", max_instances=1)
    log.info("scheduler up: full scrape every %sh (IST-aligned)", settings.scrape_interval_hours)
    return sched


def run_worker() -> None:
    """Standalone worker process (docker-compose / multi-machine setups)."""
    init_db()
    build_scheduler(BlockingScheduler(timezone="Asia/Kolkata")).start()


def start_embedded() -> BackgroundScheduler:
    """Scheduler thread inside the API process (single-container deploys)."""
    sched = build_scheduler(BackgroundScheduler(timezone="Asia/Kolkata"))
    sched.start()
    return sched

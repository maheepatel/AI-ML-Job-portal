"""One scrape run: fetch every source → normalise → classify → upsert → dedupe → trust →
lifecycle → liveness. Safe to run repeatedly; every stage is idempotent."""

import asyncio
import hashlib
import logging
import re
import time
from collections import defaultdict
from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..db import aware, init_db, session_scope, utcnow
from ..domain.classify import classify
from ..domain.normalize import fingerprint, html_to_text, parse_location, parse_salary
from ..domain.trust import score_trust
from ..models import Board, Job, ScrapeRun, SourceRun
from .base import FetchResult, Http, RawJob, Source
from .discovery import board_from_url, is_ats_url
from ..search_index import build_and_store
from .liveness import run_liveness
from .registry import DISABLE_AFTER_FAILURES, add_boards, build_sources, seed_from_yaml
from .sources.yc import YCJobBoard, ai_hiring, crawl_yc_websites, yc_directory

log = logging.getLogger("gradient.pipeline")

# Bump when classification/normalisation rules change: every stored job is re-processed
# on the next run instead of being skipped as "unchanged".
CLASSIFIER_VERSION = 2
LISTING_ONLY = {"simplify"}  # sources that publish only a link to the employer, no description
KIND_PRIORITY = {"ats": 90, "bigtech": 85, "linkedin": 60, "board": 45, "community": 40}
_SALARY_HINT = re.compile(r"[^.\n]{0,80}(salary|compensation|ctc|pay range|stipend|base pay)[^.\n]{0,120}", re.I)


def job_priority(job: Job) -> int:
    # Simplify links straight to the employer; a YC posting loses to the company's own ATS copy.
    return KIND_PRIORITY.get(job.source_kind, 30) + (10 if job.source == "simplify" else 0) - (10 if job.source == "yc" else 0)


# ---------------------------------------------------------------- fetch


SOURCE_TIMEOUT_S = 300  # per-source cap (Microsoft, the slowest healthy source, takes ~150-230s)


async def _fetch_one(src: Source, http: Http, slots: asyncio.Semaphore) -> tuple[Source, FetchResult | None, str | None, int]:
    # The timeout starts once the source holds a slot, so a long queue never times sources out.
    async with slots:
        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(src.fetch(http), timeout=SOURCE_TIMEOUT_S)
            return src, result, None, int((time.perf_counter() - t0) * 1000)
        except Exception as exc:  # one broken source must never sink the run
            msg = f"{type(exc).__name__}: {exc}"[:480]
            return src, None, msg, int((time.perf_counter() - t0) * 1000)


def _due(session: Session, src: Source) -> bool:
    if not src.min_interval_hours:
        return True
    last_ok = session.scalar(
        select(func.max(SourceRun.finished_at)).where(SourceRun.source_key == src.key, SourceRun.ok.is_(True), SourceRun.skipped.is_(False))
    )
    return last_ok is None or utcnow() - aware(last_ok) >= timedelta(hours=src.min_interval_hours)


# ---------------------------------------------------------------- normalise + upsert


def _salary(raw: RawJob, description: str):
    if raw.salary_min or raw.salary_max:
        return _f(raw.salary_min), _f(raw.salary_max), raw.salary_currency, raw.salary_period
    text = raw.salary_text
    if not text:
        # Only scan around pay keywords; a full-text money regex would catch "$10B raised".
        low = description.lower()
        spots = [low.find(k) for k in ("salary", "compensation", "ctc", "pay range", "stipend", "base pay")]
        text = " ".join(description[max(0, i - 80): i + 160] for i in spots if i >= 0)
    return parse_salary(text)


def _f(v):
    try:
        return float(v) if v not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return None


def _apply(job: Job, raw: RawJob, src: Source, description: str, cls, now) -> None:
    loc = parse_location(raw.location, raw.remote, raw.title)
    smin, smax, scur, sper = _salary(raw, description)
    job.title = raw.title.strip()[:300]
    job.company = (raw.company or src.company or "").strip()[:200]
    job.company_domain = raw.company_domain or src.domain
    job.url = raw.url[:1000]
    job.description = description
    job.desc_hash = hashlib.sha1(description[:600].lower().encode()).hexdigest()[:16] if len(description) > 200 else None
    job.location_raw = (raw.location or "")[:400]
    job.city, job.country, job.work_mode = loc.city, loc.country, loc.work_mode
    job.employment_type = (raw.employment_type or None) and str(raw.employment_type)[:40]
    job.salary_min, job.salary_max, job.salary_currency, job.salary_period = smin, smax, scur, sper
    job.role_family, job.ai_score, job.seniority = cls.role_family, cls.ai_score, cls.seniority
    job.exp_min, job.exp_max, job.skills = cls.exp_min, cls.exp_max, cls.skills
    job.fingerprint = fingerprint(job.company, job.title, job.city)
    if raw.posted_at:
        job.posted_at = min(raw.posted_at, now)
    job.deadline_at = raw.deadline_at


def _process_source(session: Session, run: ScrapeRun, src: Source, result: FetchResult | None, error: str | None,
                    duration: int, touched_fps: set[str], discovered: dict) -> dict:
    now = utcnow()
    sr = SourceRun(run_id=run.id, source_key=src.key, source=src.name, ok=error is None, duration_ms=duration,
                   error=error, finished_at=now)
    board = session.get(Board, src.board_id) if src.board_id else None

    if error is not None or result is None:
        # Rate limiting says nothing about the board itself, so it never counts toward disabling it.
        if board and "HTTP 429" not in (error or ""):
            board.consecutive_failures += 1
            if "HTTP 404" in error or board.consecutive_failures >= DISABLE_AFTER_FAILURES:
                board.enabled = False
        session.add(sr)
        return {"ok": False}

    existing = {j.source_job_id: j for j in session.scalars(select(Job).where(Job.source_key == src.key))}
    new = kept = closed = reopened = 0

    for raw in result.jobs:
        if not raw.source_job_id or not raw.title:
            continue
        job = existing.get(raw.source_job_id)

        if raw.detail_skipped:
            if job is None:
                continue
            if job.status == "open" or job.close_reason in ("removed_from_source", "expired", "liveness_failed"):
                if job.status == "closed":
                    job.status, job.closed_at, job.close_reason, job.close_evidence = "open", None, None, None
                    job.reopened_count += 1
                    reopened += 1
                job.last_seen_at = job.last_verified_at = now
                job.missed_runs = 0
                kept += 1
                touched_fps.add(job.fingerprint)
            continue

        chash = hashlib.sha1(f"{CLASSIFIER_VERSION}|{raw.title}|{raw.location}|{raw.url}|{raw.description}".encode("utf-8", "ignore")).hexdigest()[:16]
        if job is not None and job.content_hash == chash and job.status == "open":
            job.last_seen_at = job.last_verified_at = now
            job.missed_runs = 0
            if raw.posted_at and not job.posted_at:
                job.posted_at = raw.posted_at
            kept += 1
            continue  # unchanged since last run: no re-classification needed

        description = html_to_text(raw.description)
        cls = classify(raw.title, description, settings.max_years_experience)
        if not cls.in_scope:
            if job is not None and job.status == "open":
                job.status, job.closed_at, job.close_reason = "closed", now, "out_of_scope"
                job.close_evidence = f"Re-classified: {cls.reject_reason}"
                closed += 1
            continue

        if job is None:
            job = Job(source=src.name, source_key=src.key, source_kind=src.kind, source_job_id=raw.source_job_id,
                      authoritative=src.authoritative, first_seen_at=now, last_seen_at=now, status="open")
            session.add(job)
            existing[raw.source_job_id] = job
            new += 1
        elif job.status == "closed" and job.close_reason != "deadline_passed":
            job.status, job.closed_at, job.close_reason, job.close_evidence = "open", None, None, None
            job.reopened_count += 1
            reopened += 1

        _apply(job, raw, src, description, cls, now)
        job.content_hash = chash
        job.last_seen_at = job.last_verified_at = now
        job.missed_runs = 0
        kept += 1
        touched_fps.add(job.fingerprint)

    # Lifecycle: authoritative listings prove removal by absence.
    if src.authoritative:
        for jid, job in existing.items():
            if job.status != "open" or jid in result.seen_ids:
                continue
            job.missed_runs += 1
            if job.missed_runs >= settings.missed_runs_to_close:
                job.status, job.closed_at, job.close_reason = "closed", now, "removed_from_source"
                job.close_evidence = f"Missing from {src.key} listing for {job.missed_runs} consecutive runs"
                closed += 1
                touched_fps.add(job.fingerprint)
    else:
        # Search-based sources: a sighting refreshes the job, absence proves nothing.
        for jid in result.seen_ids:
            if (job := existing.get(jid)) is not None and job.status == "open":
                job.last_seen_at = now

    if board:
        board.consecutive_failures = 0
        board.last_ok_at = now
        board.last_job_count = len(result.seen_ids)
        board.last_relevant_count = kept
        if not board.company and result.jobs:
            board.company = result.jobs[0].company

    sr.fetched, sr.kept, sr.new, sr.closed = len(result.seen_ids), kept, new, closed
    session.add(sr)
    return {"ok": True, "fetched": len(result.seen_ids), "kept": kept, "new": new, "closed": closed, "reopened": reopened}


# ---------------------------------------------------------------- dedupe + trust


def dedupe_and_score(session: Session, fingerprints: set[str]) -> None:
    fps = list(fingerprints)
    for i in range(0, len(fps), 500):
        chunk = fps[i: i + 500]
        groups: dict[str, list[Job]] = defaultdict(list)
        for job in session.scalars(select(Job).where(Job.fingerprint.in_(chunk))):
            groups[job.fingerprint].append(job)

        hashes = {j.desc_hash for g in groups.values() for j in g if j.desc_hash}
        dup_text: dict[str, int] = {}
        if hashes:
            rows = session.execute(
                select(Job.desc_hash, func.count(func.distinct(Job.company)))
                .where(Job.desc_hash.in_(hashes), Job.status == "open").group_by(Job.desc_hash)
            )
            dup_text = dict(rows.all())

        for group in groups.values():
            open_jobs = [j for j in group if j.status == "open"]
            canonical = max(open_jobs, key=lambda j: (job_priority(j), -aware(j.first_seen_at).timestamp())) if open_jobs else None
            on_ats = any(j.source_kind in ("ats", "bigtech") for j in open_jobs)
            earliest = min((aware(j.posted_at) or aware(j.first_seen_at) for j in open_jobs), default=None)
            for job in group:
                job.duplicate_of = None if canonical is None or job is canonical or job.status != "open" else canonical.id
                if job is canonical and earliest and (job.posted_at is None or earliest < aware(job.posted_at)):
                    job.posted_at = earliest  # live since the earliest sighting on any platform
                t = score_trust(
                    title=job.title, company=job.company, description=job.description, url=job.url,
                    source_kind=job.source_kind, company_domain=job.company_domain,
                    salary_max=job.salary_max, salary_currency=job.salary_currency, salary_period=job.salary_period,
                    exp_min=job.exp_min, cross_listed_on_ats=on_ats, apply_on_ats=is_ats_url(job.url),
                    listing_only=job.source in LISTING_ONLY,
                    duplicate_text_count=dup_text.get(job.desc_hash, 0) if job.desc_hash else 0,
                )
                job.trust_score, job.trust_label, job.trust_reasons = t.score, t.label, t.reasons
        session.flush()


def prune(session: Session) -> dict:
    """Retention so the DB stays small (Neon free = 1 GB): run history 14 days, closed jobs keep
    full text 30 days and are deleted after 180. Open jobs are never touched."""
    now = utcnow()
    runs = session.execute(delete(SourceRun).where(SourceRun.finished_at < now - timedelta(days=14))).rowcount
    slim = session.execute(
        update(Job).where(Job.status == "closed", Job.closed_at < now - timedelta(days=30), Job.description != "")
        .values(description="", desc_hash=None)
    ).rowcount
    old = select(Job.id).where(Job.status == "closed", Job.closed_at < now - timedelta(days=180))
    session.execute(update(Job).where(Job.duplicate_of.in_(old)).values(duplicate_of=None))
    gone = session.execute(delete(Job).where(Job.id.in_(old))).rowcount
    return {"source_runs_pruned": runs, "closed_slimmed": slim, "closed_deleted": gone}


def expire_and_deadlines(session: Session) -> int:
    now = utcnow()
    n = session.execute(
        update(Job).where(Job.status == "open", Job.deadline_at.is_not(None), Job.deadline_at < now)
        .values(status="closed", closed_at=now, close_reason="deadline_passed", close_evidence="Application deadline passed")
    ).rowcount
    n += session.execute(
        update(Job).where(Job.status == "open", Job.authoritative.is_(False),
                          Job.last_verified_at < now - timedelta(days=settings.expire_after_days))
        .values(status="closed", closed_at=now, close_reason="expired",
                close_evidence=f"Not re-confirmed on any source for {settings.expire_after_days} days")
    ).rowcount
    return n


# ---------------------------------------------------------------- run


async def run_pipeline(trigger: str = "manual", only: set[str] | None = None, liveness: bool = True) -> dict:
    init_db()
    t0 = time.perf_counter()
    http = Http()
    # YC directory (yc-oss JSON on GitHub Pages): feeds the YC job-board slice and the website crawl.
    yc_hiring, yc_crawl = [], []
    if not only or "yc" in only:
        try:
            yc_hiring, yc_crawl = await yc_directory(http)
        except Exception as exc:
            log.warning("YC directory unavailable this run: %s", exc)
    with session_scope() as s:
        seeded = seed_from_yaml(s)
        # A run killed mid-way (deploy, crash) would otherwise show "running" forever.
        s.execute(update(ScrapeRun).where(ScrapeRun.status == "running", ScrapeRun.started_at < utcnow() - timedelta(hours=2))
                  .values(status="failed", finished_at=utcnow()))
        run = ScrapeRun(started_at=utcnow(), trigger=trigger, status="running")
        s.add(run)
        s.flush()
        run_id = run.id
        all_sources = build_sources(s, only)
        due = [src for src in all_sources if _due(s, src)]
        skipped = [src for src in all_sources if src not in due]
        keys = [src.key for src in due]
        known: dict[str, set[str]] = defaultdict(set)
        for i in range(0, len(keys), 500):
            for key, jid in s.execute(select(Job.source_key, Job.source_job_id)
                                          # jobs stored without a description get their detail page re-fetched
                                          .where(Job.source_key.in_(keys[i: i + 500]), Job.description != "")):
                known[key].add(jid)
        for src in due:
            src.known_ids = known.get(src.key, set())
            if isinstance(src, YCJobBoard):
                src.companies, src.run_id = ai_hiring(yc_hiring), run_id
        for src in skipped:
            s.add(SourceRun(run_id=run_id, source_key=src.key, source=src.name, ok=True, skipped=True, finished_at=utcnow()))

    log.info("run %s: %d sources due, %d skipped (min interval), %d boards seeded", run_id, len(due), len(skipped), seeded)
    # Runs alongside the sweep: this run's slice of YC company websites -> ATS boards (origin yc).
    yc_task = asyncio.create_task(crawl_yc_websites(http, yc_crawl, run_id))
    slots = asyncio.Semaphore(settings.sources_in_flight)
    totals = defaultdict(int)
    touched: set[str] = set()
    discovered: dict[tuple[str, str], str] = {}
    failed: list[str] = []

    def persist(src, result, error, duration) -> None:
        """Runs in a worker thread, one source at a time (single DB writer)."""
        with session_scope() as s:
            run = s.get(ScrapeRun, run_id)
            r = _process_source(s, run, src, result, error, duration, touched, discovered)
        if r["ok"]:
            for k in ("fetched", "kept", "new", "closed", "reopened"):
                totals[k] += r[k]
        else:
            failed.append(src.key)
        # Raw URLs of filtered-out jobs still reveal boards worth adding.
        if result:
            for raw in result.jobs:
                if b := board_from_url(raw.url):
                    discovered.setdefault(b, raw.company)

    # Stream: each source is persisted as soon as it finishes, so the site fills in during
    # the sweep and memory stays flat no matter how many boards the registry grows to.
    done = 0
    for next_done in asyncio.as_completed([_fetch_one(src, http, slots) for src in due]):
        src, result, error, duration = await next_done
        await asyncio.to_thread(persist, src, result, error, duration)
        done += 1
        if done % 200 == 0:
            log.info("run %s: %d/%d sources processed, %d requests", run_id, done, len(due), http.requests)
    log.info("run %s: fetch+persist finished in %.0fs, %d HTTP requests", run_id, time.perf_counter() - t0, http.requests)
    try:
        yc_found = await asyncio.wait_for(yc_task, timeout=120)
    except Exception as exc:
        log.warning("run %s: YC website crawl incomplete: %s", run_id, exc)
        yc_found = {}

    with session_scope() as s:
        dedupe_and_score(s, touched)
        totals["expired"] = expire_and_deadlines(s)
        totals.update(prune(s))
        totals["boards_discovered_yc"] = add_boards(s, set(yc_found), "yc", yc_found)
        totals["boards_discovered"] = add_boards(s, set(discovered), "auto", discovered)

    if liveness:
        live = await run_liveness(http, settings.liveness_batch)
        totals["liveness_checked"], totals["liveness_closed"] = live["checked"], live["closed"]
        if live["closed_fps"]:
            with session_scope() as s:
                dedupe_and_score(s, live["closed_fps"])

    # Publish the match index so the web tier only has to load it, never fit it.
    try:
        with session_scope() as s:
            totals["index_bytes"] = build_and_store(s, f"run-{run_id}")
    except Exception:
        log.exception("run %s: building the match index failed (web tier keeps the previous one)", run_id)

    with session_scope() as s:
        run = s.get(ScrapeRun, run_id)
        run.finished_at = utcnow()
        run.status = "ok" if not failed else ("partial" if len(failed) < len(due) else "failed")
        run.stats = {
            **totals, "sources": len(all_sources), "sources_ok": len(due) - len(failed), "sources_failed": len(failed),
            "sources_skipped": len(skipped), "requests": http.requests,
            "duration_s": round(time.perf_counter() - t0, 1), "failed_sources": failed[:50],
        }
        stats = dict(run.stats)
    log.info("run %s done: %s", run_id, {k: v for k, v in stats.items() if k != "failed_sources"})
    return {"run_id": run_id, **stats}

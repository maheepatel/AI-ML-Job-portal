"""Public read API + resume matching. Mounts the built SPA in production."""

import asyncio
import json
import logging
import re
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.orm import Session, defer

from ..config import settings
from ..db import SessionLocal, aware, engine, init_db, utcnow
from ..domain.matching import match_jobs, profile_from_pdf
from ..domain.normalize import EU_COUNTRIES
from ..models import Board, Job, ScrapeRun, SourceRun
from ..search_index import ensure_index

app = FastAPI(title="Gradient — AI/ML jobs API", version="1.0", docs_url="/api/docs", openapi_url="/api/openapi.json")
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["GET", "POST"], allow_headers=["*"])

FAMILIES = ["ML Engineer", "Data Scientist", "AI Engineer / LLM", "Research", "Computer Vision", "NLP & Speech",
            "MLOps & ML Platform", "AI Product Engineering", "Data & Analytics"]


@app.on_event("startup")
def _startup() -> None:
    init_db()

    def warm():  # load (or build) the match index off the request path
        try:
            with db() as s:
                ensure_index(s)
        except Exception:
            log.exception("match index warm-up failed")

    threading.Thread(target=warm, daemon=True).start()

    if settings.embedded_worker:
        from ..worker import start_embedded

        app.state.scheduler = start_embedded()


# ---------------------------------------------------------------- helpers

_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    # Behind Fly's proxy every request arrives from the proxy; the real client is in a header
    # the proxy sets (and overwrites), so it can't be spoofed there.
    if settings.trust_proxy_headers:
        forwarded = request.headers.get("fly-client-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if forwarded:
            return forwarded
    return request.client.host if request.client else "?"


def rate_limit(request: Request, key: str, per_minute: int) -> None:
    if len(_hits) > 20_000:  # bound memory: forget idle clients
        for k in [k for k, v in _hits.items() if not v or time.monotonic() - v[-1] > 60]:
            del _hits[k]
    q = _hits[f"{key}:{client_ip(request)}"]
    now = time.monotonic()
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= per_minute:
        raise HTTPException(429, "Too many requests — try again in a minute")
    q.append(now)


def live_since(job: Job):
    return aware(job.posted_at) or aware(job.first_seen_at)


def iso(dt):
    dt = aware(dt)
    return dt.isoformat() if dt else None


def summary(job: Job) -> dict:
    return {
        "id": job.id, "title": job.title, "company": job.company, "url": job.url,
        "location": job.location_raw, "city": job.city, "country": job.country, "work_mode": job.work_mode,
        "role_family": job.role_family, "seniority": job.seniority, "exp_min": job.exp_min, "exp_max": job.exp_max,
        "skills": job.skills[:8], "source": job.source, "source_kind": job.source_kind,
        "trust_score": job.trust_score, "trust_label": job.trust_label,
        "salary": _salary(job), "employment_type": job.employment_type,
        "status": job.status, "live_since": iso(live_since(job)), "posted_at": iso(job.posted_at),
        "first_seen_at": iso(job.first_seen_at), "last_verified_at": iso(job.last_verified_at),
        "closed_at": iso(job.closed_at), "close_reason": job.close_reason,
    }


def _salary(job: Job) -> dict | None:
    if not (job.salary_min or job.salary_max):
        return None
    return {"min": job.salary_min, "max": job.salary_max, "currency": job.salary_currency, "period": job.salary_period}


# Data changes once per sweep (every 4h), so short-lived response caching is safe and keeps
# page-load endpoints well under a second. Bounded so odd query strings can't grow memory.
_cache: dict = {}
_cache_lock = threading.Lock()


def cached(key, ttl: float, compute):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = compute()
    with _cache_lock:
        if len(_cache) > 500:
            _cache.clear()
        _cache[key] = (now + ttl, value)
    return value


def db() -> Session:
    return SessionLocal()


LIVE_SINCE = func.coalesce(Job.posted_at, Job.first_seen_at)


def _filters(q, family, exp, region, posted_within, trust, kind, status):
    conds = [Job.duplicate_of.is_(None), Job.status == status]
    if q:
        like = f"%{q.strip()}%"
        conds.append(or_(Job.title.ilike(like), Job.company.ilike(like), Job.location_raw.ilike(like)))
    if family:
        conds.append(Job.role_family.in_(family))
    if exp == "fresher":
        conds.append(or_(Job.seniority.in_(["intern", "entry"]), Job.exp_min <= 1))
    elif exp == "1-2":
        conds.append(or_(and_(Job.exp_min >= 1, Job.exp_min <= 2), Job.seniority == "junior",
                         and_(Job.exp_min.is_(None), Job.seniority.in_(["entry", "unknown"]))))
    elif exp == "2-4":
        conds.append(or_(and_(Job.exp_min >= 2, Job.exp_min <= 4), Job.seniority == "mid",
                         and_(Job.exp_min.is_(None), Job.seniority == "unknown")))
    elif exp == "no-intern":
        conds.append(Job.seniority != "intern")
    regions = {
        "bengaluru": Job.city == "Bengaluru", "india": Job.country == "India", "remote": Job.work_mode == "remote",
        "north-america": Job.country.in_(["United States", "Canada"]),
        "europe": Job.country.in_([*EU_COUNTRIES, "United Kingdom"]),
    }
    if region:
        conds.append(or_(*[regions[r] for r in region if r in regions]))
    if posted_within:
        conds.append(LIVE_SINCE >= utcnow() - timedelta(hours=posted_within))
    if trust == "verified":
        conds.append(Job.trust_label == "verified")
    elif trust == "genuine":
        conds.append(Job.trust_label.in_(["verified", "likely_genuine"]))
    elif trust != "all":
        conds.append(Job.trust_label != "likely_scam")
    if kind:
        conds.append(Job.source_kind.in_(kind))
    return conds


# ---------------------------------------------------------------- routes


@app.get("/api/health")
def health():
    # Database *type* only (never the URL): a missing GRADIENT_DATABASE_URL silently falls back to
    # a throwaway SQLite file, which looks like "deployed but empty" unless this says so.
    return {"ok": True, "database": engine.dialect.name, "profile": bool(settings.profile_json or settings.profile_file.exists())}


@app.get("/api/jobs")
def list_jobs(
    q: str | None = Query(default=None, max_length=200),
    family: list[str] = Query(default=[]),
    exp: str | None = None,
    region: list[str] = Query(default=[]),
    posted_within: int | None = Query(default=None, ge=1, le=24 * 90),
    trust: str = "default",
    kind: list[str] = Query(default=[]),
    status: str = Query(default="open", pattern="^(open|closed)$"),
    sort: str = Query(default="newest", pattern="^(newest|trust|closed)$"),
    page: int = Query(default=1, ge=1, le=500),
    page_size: int = Query(default=30, ge=1, le=100),
):
    key = ("jobs", q, tuple(sorted(family)), exp, tuple(sorted(region)), posted_within, trust, tuple(sorted(kind)), status, sort, page, page_size)
    return cached(key, 60, lambda: _list_jobs(q, family, exp, region, posted_within, trust, kind, status, sort, page, page_size))


def _list_jobs(q, family, exp, region, posted_within, trust, kind, status, sort, page, page_size):
    conds = _filters(q, family, exp, region, posted_within, trust, kind, status)
    order = {"newest": LIVE_SINCE.desc(), "trust": Job.trust_score.desc(), "closed": Job.closed_at.desc()}[sort]
    with db() as s:
        total = s.scalar(select(func.count()).select_from(Job).where(*conds))
        rows = s.scalars(select(Job).options(defer(Job.description), defer(Job.trust_reasons))  # list view never shows them
                         .where(*conds).order_by(order, Job.id.desc()).offset((page - 1) * page_size).limit(page_size))
        items = [summary(j) for j in rows]
        fam_counts = dict(s.execute(
            select(Job.role_family, func.count()).where(*_filters(q, [], exp, region, posted_within, trust, kind, status))
            .group_by(Job.role_family)
        ).all())
    return {"total": total, "page": page, "page_size": page_size, "items": items, "family_counts": fam_counts}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    with db() as s:
        job = s.get(Job, job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        canonical = s.get(Job, job.duplicate_of) if job.duplicate_of else job
        listings = s.scalars(select(Job).where(Job.fingerprint == canonical.fingerprint)).all()
        data = summary(canonical)
        data.update({
            "description": canonical.description, "skills": canonical.skills, "trust_reasons": canonical.trust_reasons,
            "close_evidence": canonical.close_evidence, "reopened_count": canonical.reopened_count,
            "last_seen_at": iso(canonical.last_seen_at),
            "listings": [{"source": j.source, "source_kind": j.source_kind, "url": j.url, "status": j.status,
                          "first_seen_at": iso(j.first_seen_at)} for j in listings],
        })
    return data


@app.get("/api/stats")
def stats():
    return cached("stats", 60, _stats)


def _stats():
    now = utcnow()
    with db() as s:
        base = [Job.status == "open", Job.duplicate_of.is_(None), Job.trust_label != "likely_scam"]
        def n(cond):
            # SUM over zero rows is NULL in SQL; an empty database must still report 0, not null.
            return func.coalesce(func.sum(case((cond, 1), else_=0)), 0)

        # One pass over open canonical jobs instead of a COUNT query per tile.
        open_n, companies, new_4h, new_24h, india, remote, verified = s.execute(
            select(func.count(), func.count(func.distinct(Job.company)),
                   n(Job.first_seen_at >= now - timedelta(hours=4)), n(LIVE_SINCE >= now - timedelta(hours=24)),
                   n(Job.country == "India"), n(Job.work_mode == "remote"), n(Job.trust_label == "verified"))
            .where(*base)
        ).one()
        closed_7d = s.scalar(select(func.count()).select_from(Job).where(Job.status == "closed", Job.closed_at >= now - timedelta(days=7)))
        flagged = s.scalar(select(func.count()).select_from(Job).where(Job.status == "open", Job.trust_label == "likely_scam"))
        boards = s.scalar(select(func.count()).select_from(Board).where(Board.enabled.is_(True)))
        families = dict(s.execute(select(Job.role_family, func.count()).where(*base).group_by(Job.role_family)).all())
        last = s.scalars(select(ScrapeRun).where(ScrapeRun.finished_at.is_not(None)).order_by(ScrapeRun.id.desc()).limit(1)).first()
        running = s.scalars(select(ScrapeRun).where(ScrapeRun.status == "running").order_by(ScrapeRun.id.desc()).limit(1)).first()
        ticker = s.execute(select(Job.id, Job.title, Job.company, Job.city, Job.work_mode)
                           .where(*base, Job.trust_label.in_(["verified", "likely_genuine"]),
                                  Job.role_family != "Data & Analytics", Job.seniority != "intern")
                           .order_by(LIVE_SINCE.desc()).limit(300)).all()
        seen_companies: set[str] = set()
        ticker = [j for j in ticker if not (j.company in seen_companies or seen_companies.add(j.company))][:24]  # one per company
    last_finished = aware(last.finished_at) if last else None
    return {
        "open": open_n, "companies": companies, "new_4h": new_4h, "new_24h": new_24h, "closed_7d": closed_7d,
        "india": india, "remote": remote, "verified": verified, "flagged_scams": flagged, "boards": boards,
        "families": families, "interval_hours": settings.scrape_interval_hours,
        "last_run": {"id": last.id, "finished_at": iso(last_finished), "status": last.status, "stats": last.stats} if last else None,
        "running": bool(running),
        "next_run_at": iso(last_finished + timedelta(hours=settings.scrape_interval_hours)) if last_finished else None,
        "ticker": [{"id": j.id, "title": j.title, "company": j.company, "city": j.city, "work_mode": j.work_mode} for j in ticker],
    }


@app.get("/api/runs")
def runs(limit: int = Query(default=12, le=50)):
    with db() as s:
        rs = s.scalars(select(ScrapeRun).order_by(ScrapeRun.id.desc()).limit(limit)).all()
        last_id = rs[0].id if rs else None
        sources = []
        if last_id:
            srcs = s.scalars(select(SourceRun).where(SourceRun.run_id == last_id)).all()
            by: dict[str, dict] = defaultdict(lambda: {"sources": 0, "ok": 0, "failed": 0, "fetched": 0, "kept": 0, "new": 0, "closed": 0})
            for r in srcs:
                if r.skipped:
                    continue
                b = by[r.source]
                b["sources"] += 1
                b["ok" if r.ok else "failed"] += 1
                for k in ("fetched", "kept", "new", "closed"):
                    b[k] += getattr(r, k)
            sources = sorted(({"source": k, **v} for k, v in by.items()), key=lambda x: -x["kept"])
        boards = dict(s.execute(select(Board.origin, func.count()).where(Board.enabled.is_(True)).group_by(Board.origin)).all())
        disabled = s.scalar(select(func.count()).select_from(Board).where(Board.enabled.is_(False)))
        closures = dict(s.execute(select(Job.close_reason, func.count()).where(Job.status == "closed").group_by(Job.close_reason)).all())
    return {
        "runs": [{"id": r.id, "started_at": iso(r.started_at), "finished_at": iso(r.finished_at), "status": r.status,
                  "trigger": r.trigger, "stats": {k: v for k, v in (r.stats or {}).items() if k != "failed_sources"}} for r in rs],
        "sources": sources, "boards": boards, "boards_disabled": disabled, "closures": closures,
    }


# ---------------------------------------------------------------- matching


def _matches_response(profile: dict, limit: int, exp: str | None = None) -> dict:
    with db() as s:
        ensure_index(s)
    matches = match_jobs(profile, limit=400)
    with db() as s:
        jobs = {j.id: j for j in s.scalars(select(Job).where(Job.id.in_([m["job_id"] for m in matches])))}
        out = []
        for m in matches:
            j = jobs.get(m["job_id"])
            if j is None or (exp == "no-intern" and j.seniority == "intern"):
                continue
            out.append({**m, "job": summary(j)})
            if len(out) >= limit:
                break
    public_profile = {k: v for k, v in profile.items() if k != "keywords_text"}
    return {"profile": public_profile, "matches": out}


@app.get("/api/match")
def match_owner(limit: int = Query(default=60, le=200), exp: str | None = None):
    if settings.profile_json:
        return _matches_response(json.loads(settings.profile_json), limit, exp)
    if not settings.profile_file.exists():
        raise HTTPException(404, "No profile yet — run `python -m gradient.cli profile resume.pdf` or upload a resume")
    profile = json.loads(settings.profile_file.read_text())
    return _matches_response(profile, limit, exp)


@app.post("/api/match/resume")
async def match_resume(request: Request, file: UploadFile = File(...), limit: int = Query(default=60, le=200)):
    rate_limit(request, "resume", 6)
    data = await file.read(5 * 1024 * 1024 + 1)
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(413, "Resume must be under 5 MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "Please upload a PDF")
    try:
        # Parsed in memory, never stored; off the event loop so a slow PDF can't stall the site.
        profile = await asyncio.wait_for(asyncio.to_thread(profile_from_pdf, data), timeout=20)
    except Exception:
        raise HTTPException(422, "Could not read that PDF")
    return await asyncio.to_thread(_matches_response, profile, limit)


log = logging.getLogger("gradient.api")


@app.middleware("http")
async def _request_context(request: Request, call_next):
    """Request id on every response + a coarse per-IP limit on the whole API."""
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    if request.url.path.startswith("/api/"):
        try:
            rate_limit(request, "api", 240)
        except HTTPException as exc:
            return JSONResponse({"detail": exc.detail, "request_id": request_id}, status_code=exc.status_code)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error request_id=%s path=%s", request_id, request.url.path)
        return JSONResponse({"detail": "Internal error", "request_id": request_id}, status_code=500)
    response.headers["X-Request-ID"] = request_id
    return response


# ---------------------------------------------------------------- SPA

if settings.frontend_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.frontend_dist / "assets"), name="assets")

    SPA_ROUTES = re.compile(r"^(|jobs|jobs/\d+|closed|for-me|status|privacy|terms)/?$")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = settings.frontend_dist / path
        if path and target.is_file() and settings.frontend_dist in target.resolve().parents:
            return FileResponse(target)
        # Unknown URLs still render the SPA's 404 page, but with a real 404 status for crawlers.
        status = 200 if SPA_ROUTES.match(path) else 404
        return FileResponse(settings.frontend_dist / "index.html", status_code=status)

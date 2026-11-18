"""Owner-only API: apply queue, CV tailoring, application tracker and scrape-now.

Every route needs the X-Admin-Token header to equal GRADIENT_ADMIN_TOKEN. With no token
configured the whole router answers 404, so a fresh deploy exposes nothing.
"""

import asyncio
import hmac
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from ..config import settings
from ..db import aware, session_scope, utcnow
from ..domain.matching import match_jobs
from ..models import Application, Job, ScrapeRun
from ..owner import github
from ..owner.notify import owner_profile
from ..owner.queue import build_queue, lane_for, today_ist
from ..owner.tailor import TailorError, load_master, tailor
from ..search_index import ensure_index

_failures: deque = deque()


def require_owner(request: Request, x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.admin_token:
        raise HTTPException(404, "Not found")
    now = time.monotonic()
    while _failures and now - _failures[0] > 600:
        _failures.popleft()
    if len(_failures) >= 20:  # global brake on guessing: 20 bad tokens per 10 minutes
        raise HTTPException(429, "Too many failed attempts; wait 10 minutes")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), settings.admin_token.encode()):
        _failures.append(now)
        raise HTTPException(401, "Wrong owner password")


router = APIRouter(prefix="/api/owner", dependencies=[Depends(require_owner)])

STATUSES = ("queued", "applied", "skipped", "interview", "offer", "rejected", "ghosted")


def _iso(dt):
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _app_out(a: Application, j: Job | None) -> dict:
    return {
        "id": a.id, "job_id": a.job_id, "lane": a.lane, "status": a.status, "score": a.score, "reasons": a.reasons,
        "queued_on": a.queued_on, "applied_at": _iso(a.applied_at), "follow_up_at": _iso(a.follow_up_at),
        "notes": a.notes, "tailored": bool(a.tailored),
        "job": None if j is None else {
            "id": j.id, "title": j.title, "company": j.company, "url": j.url, "location": j.location_raw,
            "city": j.city, "country": j.country, "work_mode": j.work_mode, "status": j.status,
            "trust_label": j.trust_label, "source": j.source, "live_since": _iso(j.posted_at or j.first_seen_at),
        },
    }


@router.get("/me")
def me():
    return {"ok": True, "features": {"scrape_button": bool(settings.github_token), "tailoring": bool(settings.groq_api_key),
                                     "master_cv": bool(settings.master_cv_json or (settings.profile_file.parent / "master_cv.json").exists()),
                                     "profile": owner_profile() is not None},
            "daily_cap": settings.daily_apply_cap}


# ---------------------------------------------------------------- scrape now


@router.post("/scrape")
def scrape_now():
    try:
        current = github.latest_scrape_run()
        if current and current["status"] in ("queued", "in_progress", "waiting", "pending"):
            return {"started": False, "reason": "A sweep is already running", "run": current}
        github.dispatch_scrape()
    except github.GitHubError as exc:
        raise HTTPException(502, str(exc))
    return {"started": True}


@router.get("/scrape")
def scrape_status():
    with session_scope() as s:
        recent = s.scalars(select(ScrapeRun).where(ScrapeRun.finished_at.is_not(None)).order_by(ScrapeRun.id.desc()).limit(5)).all()
        durations = [r.stats.get("duration_s") for r in recent if r.stats and r.stats.get("duration_s")]
        last = recent[0] if recent else None
        last_out = {"id": last.id, "finished_at": _iso(last.finished_at), "status": last.status,
                    "kept": last.stats.get("kept"), "new": last.stats.get("new")} if last else None
    # The workflow spends ~2 min on setup and pip install before the sweep itself starts.
    expected = int(sum(durations) / len(durations) + 120) if durations else 15 * 60
    run, error = None, None
    try:
        run = github.latest_scrape_run()
    except github.GitHubError as exc:
        error = str(exc)
    eta = None
    if run and run["status"] != "completed":
        started = datetime.fromisoformat((run["started_at"] or run["created_at"]).replace("Z", "+00:00"))
        eta = max(30, expected - int((utcnow() - started).total_seconds()))
    return {"run": run, "expected_seconds": expected, "eta_seconds": eta, "last_sweep": last_out, "error": error}


# ---------------------------------------------------------------- queue + tracker


@router.get("/queue")
def queue(view: str = "today"):
    day = today_ist()
    with session_scope() as s:
        q = select(Application)
        if view == "today":
            q = q.where(Application.queued_on == day, Application.status == "queued")
        elif view == "tracker":
            q = q.where(Application.status.not_in(["queued", "skipped"]))
        elif view == "backlog":
            q = q.where(Application.status == "queued", Application.queued_on < day)
        apps = s.scalars(q.order_by(Application.score.desc()).limit(300)).all()
        jobs = {j.id: j for j in s.scalars(select(Job).where(Job.id.in_([a.job_id for a in apps])))} if apps else {}
        counts = dict(s.execute(select(Application.status, func.count()).group_by(Application.status)).all())
        today_n = s.scalar(select(func.count()).select_from(Application).where(Application.queued_on == day)) or 0
        items = [_app_out(a, jobs.get(a.job_id)) for a in apps]
    sent = sum(counts.get(k, 0) for k in ("applied", "interview", "offer", "rejected", "ghosted"))
    replies = counts.get("interview", 0) + counts.get("offer", 0)
    return {"day": day, "items": items, "counts": counts, "queued_today": today_n, "cap": settings.daily_apply_cap,
            "callback_rate": round(100 * replies / sent, 1) if sent else None, "applied_total": sent}


@router.post("/queue/build")
async def queue_build():
    profile = owner_profile()
    if not profile:
        raise HTTPException(409, "No owner profile on the server (GRADIENT_PROFILE_JSON)")

    def run():
        with session_scope() as s:
            return len(build_queue(s, profile))

    return {"added": await asyncio.to_thread(run)}


class AppPatch(BaseModel):
    status: str | None = Field(default=None, pattern="^(" + "|".join(STATUSES) + ")$")
    notes: str | None = Field(default=None, max_length=4000)
    follow_up_days: int | None = Field(default=None, ge=0, le=60)


@router.patch("/applications/{app_id}")
def update_application(app_id: int, patch: AppPatch):
    with session_scope() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "Not found")
        now = utcnow()
        if patch.status:
            if patch.status == "applied" and a.status != "applied":
                a.applied_at = now
                a.follow_up_at = now + timedelta(days=7)  # nudge the recruiter after a week of silence
            a.status = patch.status
        if patch.notes is not None:
            a.notes = patch.notes
        if patch.follow_up_days is not None:
            a.follow_up_at = now + timedelta(days=patch.follow_up_days)
        a.updated_at = now
        return _app_out(a, s.get(Job, a.job_id))


@router.post("/jobs/{job_id}/save")
def save_job(job_id: int):
    """Add any job to the queue by hand (not counted against the automatic daily cap's ranking)."""
    with session_scope() as s:
        j = s.get(Job, job_id)
        if j is None:
            raise HTTPException(404, "Job not found")
        existing = s.scalar(select(Application).where(Application.job_id == job_id))
        if existing:
            return _app_out(existing, j)
        lane, score, reasons = "tailor", 0, {}
        profile = owner_profile()
        if profile:
            ensure_index(s)
            m = next((m for m in match_jobs(profile, limit=5000, min_trust=0) if m["job_id"] == job_id), None)
            if m:
                lane = lane_for(m) or "tailor"
                score = m["score"]
                reasons = {k: m[k] for k in ("breakdown", "matched_skills", "missing_skills", "why")}
        now = utcnow()
        a = Application(job_id=job_id, lane=lane, status="queued", score=score, reasons=reasons,
                        queued_on=today_ist(now), created_at=now, updated_at=now, notes="Saved by hand")
        s.add(a)
        s.flush()
        return _app_out(a, j)


# ---------------------------------------------------------------- CV tailoring


@router.post("/applications/{app_id}/tailor")
async def tailor_cv(app_id: int):
    with session_scope() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "Not found")
        j = s.get(Job, a.job_id)
        job = {"title": j.title, "company": j.company, "description": j.description, "skills": j.skills}
    try:
        master = load_master()
        result = await asyncio.to_thread(tailor, master, job)
    except TailorError as exc:
        raise HTTPException(503, str(exc))
    with session_scope() as s:
        a = s.get(Application, app_id)
        a.tailored = {**result, "created_at": utcnow().isoformat()}
        a.updated_at = utcnow()
    return {"master": master, **result}


@router.get("/applications/{app_id}/tailored")
def get_tailored(app_id: int):
    with session_scope() as s:
        a = s.get(Application, app_id)
        if a is None or not a.tailored:
            raise HTTPException(404, "Not tailored yet")
        data = a.tailored
    try:
        master = load_master()
    except TailorError as exc:
        raise HTTPException(503, str(exc))
    return {"master": master, **data}


@router.get("/applications/{app_id}/cv.pdf")
def cv_pdf(app_id: int, which: str = "tailored"):
    from ..owner.cvpdf import render

    with session_scope() as s:
        a = s.get(Application, app_id)
        if a is None:
            raise HTTPException(404, "Not found")
        j = s.get(Job, a.job_id)
        tailored = a.tailored
        company = j.company if j else "job"
    try:
        cv = tailored["cv"] if which == "tailored" and tailored else load_master()
    except TailorError as exc:
        raise HTTPException(503, str(exc))
    safe = "".join(c for c in company if c.isalnum())[:30] or "job"
    name = "".join(c for c in cv.get("name", "CV") if c.isalnum()) or "CV"
    return Response(render(cv), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}_CV_{safe}.pdf"', "Cache-Control": "no-store"})

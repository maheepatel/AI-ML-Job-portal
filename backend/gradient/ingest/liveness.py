"""Re-checks open jobs at their own URL to catch roles that were filled or taken down.

Each run checks a rolling batch (jobs the listing has stopped showing first, then the
least-recently-checked), so every open job is re-verified at least once a day."""

import asyncio
import re

from datetime import timedelta

from sqlalchemy import and_, or_, select

from ..db import session_scope, utcnow
from ..models import Job
from .base import Http, SourceError

CLOSED_TEXT = re.compile(
    r"no longer accepting applications|job (is )?no longer (available|open|active)|position has been filled|"
    r"this (job|position|posting|role) (has )?(expired|closed|been removed)|job not found|posting is closed|"
    r"no longer exists|isn't available anymore|is not accepting applications",
    re.I,
)
_WORKDAY = re.compile(r"https://([^./]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([^/]+)(/job/.+)")
_GREENHOUSE = re.compile(r"greenhouse\.io/([^/]+)/jobs/(\d+)")
_LEVER = re.compile(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})")
_LINKEDIN = re.compile(r"linkedin\.com/jobs/view/(?:[^/]*-)?(\d+)")


async def check_job(http: Http, job: Job) -> tuple[str, str] | None:
    """('open'|'closed', evidence), or None when the check was inconclusive."""
    url = job.url or ""
    try:
        if m := _WORKDAY.match(url):
            tenant, wd, site, path = m.groups()
            resp = await http.get(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}", attempts=1)
            if resp.status in (404, 410):
                return "closed", f"Workday returned HTTP {resp.status}"
            if resp.status == 200:
                return ("open", "Workday posting live") if resp.json().get("jobPostingInfo") else ("closed", "Workday posting empty")
            return None
        if m := _GREENHOUSE.search(url):
            resp = await http.get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}", attempts=1)
            if resp.status == 404:
                return "closed", "Greenhouse API: job not found (404)"
            return ("open", "Greenhouse API: live") if resp.status == 200 else None
        if m := _LEVER.search(url):
            resp = await http.get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}", attempts=1)
            if resp.status == 404:
                return "closed", "Lever API: posting not found (404)"
            return ("open", "Lever API: live") if resp.status == 200 else None
        if m := _LINKEDIN.search(url):
            resp = await http.get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m[1]}", attempts=1)
            if resp.status in (404, 410):
                return "closed", f"LinkedIn returned HTTP {resp.status}"
            if resp.status == 200:
                text = resp.get_all_text()[:20000]
                if CLOSED_TEXT.search(text):
                    return "closed", "LinkedIn: 'No longer accepting applications'"
                return "open", "LinkedIn posting live"
            return None
        if "news.ycombinator.com" in url:
            return None  # HN comments don't close; handled by expiry

        resp = await http.get(url, attempts=1)
        if resp.status in (404, 410):
            return "closed", f"Job page returned HTTP {resp.status}"
        if resp.status != 200:
            return None
        final = str(resp.url or url)
        if final.rstrip("/") != url.rstrip("/") and ("error=true" in final or final.count("/") <= 3):
            return "closed", f"Job page redirects away to {final[:120]}"
        if CLOSED_TEXT.search(resp.get_all_text()[:30000]):
            return "closed", "Job page says the role is no longer available"
        return "open", "Job page live"
    except (SourceError, ValueError):
        return None


async def run_liveness(http: Http, limit: int) -> dict:
    with session_scope() as s:
        jobs = list(s.scalars(
            select(Job)
            .where(Job.status == "open", Job.duplicate_of.is_(None),
                   # Authoritative listings already verify their jobs every run; re-check those
                   # only once they go missing. Everything else gets a URL check every ~20h.
                   or_(Job.missed_runs > 0,
                       and_(Job.authoritative.is_(False),
                            or_(Job.last_checked_at.is_(None), Job.last_checked_at < utcnow() - timedelta(hours=20)))))
            .order_by(Job.missed_runs.desc(), Job.last_checked_at.asc().nulls_first())
            .limit(limit)
        ))
    verdicts = await asyncio.gather(*(check_job(http, j) for j in jobs))
    now = utcnow()
    closed, closed_fps = 0, set()
    with session_scope() as s:
        for job, verdict in zip(jobs, verdicts):
            row = s.get(Job, job.id)
            row.last_checked_at = now
            if verdict is None:
                continue
            state, evidence = verdict
            if state == "open":
                row.last_verified_at = now
            elif row.status == "open":
                row.status, row.closed_at, row.close_reason, row.close_evidence = "closed", now, "liveness_failed", evidence[:400]
                closed += 1
                closed_fps.add(row.fingerprint)
    return {"checked": len(jobs), "closed": closed, "closed_fps": closed_fps}

"""The daily apply queue: the best-fit open roles, capped per day, split into two lanes.

direct  — the CV already fits: experience matches, location is eligible, at most 2 core skills missing
tailor  — a good role, but the CV undersells the fit (core skills missing or a stretch on experience);
          worth a tailored CV before applying
"""

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import aware, utcnow
from ..domain.matching import CORE_SKILLS, match_jobs
from ..models import Application, Job
from ..search_index import ensure_index

IST = timezone(timedelta(hours=5, minutes=30))
MAX_AGE_DAYS = 14  # past two weeks a role has usually been screened; applications land in a big pile
MIN_SCORE = 60
_SENIOR = re.compile(r"\b(senior|sr\.?|lead|leader|head|principal|staff|director|manager|vp|chief|architect)\b", re.I)
# Remote roles with no country are often US/EU-only in practice; queue them only when the
# posting says it hires from India, APAC or anywhere.
_REMOTE_OK = re.compile(r"\b(india|apac|asia|anywhere|worldwide|global|international)\b", re.I)


def eligible(job: Job) -> bool:
    if _SENIOR.search(job.title or ""):
        return False
    if job.country == "India":
        return True
    if job.work_mode == "remote":
        return bool(_REMOTE_OK.search(f"{job.location_raw} {job.title}"))
    return False  # on-site abroad: needs a visa, not a 0-4 yr fresher's best use of an application


def today_ist(now: datetime | None = None) -> str:
    return (now or utcnow()).astimezone(IST).date().isoformat()


def lane_for(match: dict) -> str | None:
    """None = don't queue at all (not eligible / not worth it)."""
    b = match["breakdown"]
    if match["score"] < MIN_SCORE or b["location"] < 0.5 or b["experience"] < 0.6:
        return None  # abroad without remote, or the experience bar is well above the CV
    core_missing = [s for s in match["missing_skills"] if s in CORE_SKILLS]
    if b["experience"] >= 0.85 and len(core_missing) <= 2 and b["skills"] >= 0.5:
        return "direct"
    return "tailor"


def build_queue(session: Session, profile: dict, cap: int | None = None, now: datetime | None = None) -> list[Application]:
    """Top up today's queue to the cap. Idempotent: re-running adds nothing once the cap is met."""
    cap = settings.daily_apply_cap if cap is None else cap
    now = now or utcnow()
    day = today_ist(now)
    have = session.scalar(select(func.count()).select_from(Application).where(Application.queued_on == day)) or 0
    room = cap - have
    if room <= 0:
        return []
    ensure_index(session)
    matches = match_jobs(profile, limit=600)
    known = set(session.scalars(select(Application.job_id)))
    ids = [m["job_id"] for m in matches if m["job_id"] not in known]
    jobs = {j.id: j for j in session.scalars(select(Job).where(Job.id.in_(ids)))} if ids else {}
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    seen_companies: dict[str, int] = {}
    added: list[Application] = []
    for m in matches:
        j = jobs.get(m["job_id"])
        if j is None or j.status != "open" or j.duplicate_of is not None:
            continue
        if j.trust_label not in ("verified", "likely_genuine") or j.seniority == "intern":
            continue
        live = aware(j.posted_at) or aware(j.first_seen_at)
        if live and live < cutoff:
            continue
        # At most 2 roles per company per day: several applications to one employer look like spam.
        if seen_companies.get(j.company, 0) >= 2:
            continue
        if not eligible(j):
            continue
        lane = lane_for(m)
        if lane is None:
            continue
        seen_companies[j.company] = seen_companies.get(j.company, 0) + 1
        app = Application(job_id=j.id, lane=lane, status="queued", score=m["score"], queued_on=day,
                          reasons={k: m[k] for k in ("breakdown", "matched_skills", "missing_skills", "why")},
                          created_at=now, updated_at=now)
        session.add(app)
        added.append(app)
        if len(added) >= room:
            break
    session.flush()
    return added

"""Public read API for outreach signals: fresh hiring posts and freshly funded startups."""

import re
import time
from collections import Counter
from datetime import timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from ..db import SessionLocal, aware, utcnow
from ..models import FundingEvent, HiringPost, Job, Person
from ..signals.parse import company_key

router = APIRouter(prefix="/api/signals")

# Senior, academic and contract-farm roles aren't the 0-4 yr target; hidden unless asked for.
_NOT_FRESHER = re.compile(r"\b(senior|sr\.|staff|principal|lead|head of|director|vp|postdoc\w*|phd|professor|faculty|tenure)\b", re.I)
# Job-board accounts: by handle ("datasciencejobs", "nearskill") or by their listing format.
_BOT_HANDLE = re.compile(r"(jobs?|hiring|careers?|recruit|skill|talent|vacanc|openings|remote|tenure)", re.I)
_BOT_TEXT = re.compile(r"(\bis hiring:? an? .{3,120}\blocation:|^\W*(new job|open role|job:)|#\w+jobs?\b.*#\w+jobs?\b)", re.I | re.S)
_CACHE: dict = {}


def _cached(key, ttl, fn):
    hit = _CACHE.get(key)
    now = time.monotonic()
    if hit and hit[0] > now:
        return hit[1]
    val = fn()
    if len(_CACHE) > 200:
        _CACHE.clear()
    _CACHE[key] = (now + ttl, val)
    return val


def _iso(dt):
    dt = aware(dt)
    return dt.isoformat() if dt else None


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())[:160]


@router.get("/posts")
def posts(hours: int = Query(default=24, ge=1, le=240), max_likes: int = Query(default=100, ge=0, le=100000),
          q: str | None = Query(default=None, max_length=100), fresher: bool = True, people_only: bool = True,
          source: str | None = Query(default=None, pattern="^(bluesky|mastodon)$")):
    return _cached(("posts", hours, max_likes, q, fresher, people_only, source), 60,
                   lambda: _posts(hours, max_likes, q, fresher, people_only, source))


def _posts(hours, max_likes, q, fresher, people_only, source):
    since = utcnow() - timedelta(hours=hours)
    with SessionLocal() as s:
        # Accounts that post many openings a week are job-board bots, not the person who's hiring.
        week = utcnow() - timedelta(days=7)
        volume = Counter(dict(s.execute(select(HiringPost.author_handle, func.count())
                                        .where(HiringPost.posted_at >= week).group_by(HiringPost.author_handle)).all()))
        stmt = select(HiringPost).where(HiringPost.posted_at >= since, HiringPost.likes <= max_likes)
        if source:
            stmt = stmt.where(HiringPost.source == source)
        if q:
            stmt = stmt.where(HiringPost.text.ilike(f"%{q.strip()}%"))
        rows = s.scalars(stmt.order_by(HiringPost.posted_at.desc()).limit(600)).all()
    seen, out, hidden = set(), [], {"bots": 0, "senior": 0, "duplicates": 0}
    for p in rows:
        key = _norm(p.text)
        if key in seen:
            hidden["duplicates"] += 1
            continue
        seen.add(key)
        bot = volume[p.author_handle] >= 5 or bool(_BOT_HANDLE.search(p.author_handle) or _BOT_TEXT.search(p.text))
        if people_only and bot:
            hidden["bots"] += 1
            continue
        if fresher and _NOT_FRESHER.search(p.text[:400]):
            hidden["senior"] += 1
            continue
        out.append({"id": p.id, "source": p.source, "url": p.url, "author": p.author, "author_handle": p.author_handle,
                    "author_url": p.author_url, "text": p.text, "likes": p.likes, "reposts": p.reposts, "replies": p.replies,
                    "links": p.links, "skills": p.skills, "posted_at": _iso(p.posted_at), "bot": bot})
    return {"items": out[:200], "hidden": hidden, "total": len(out)}


@router.get("/funded")
def funded(days: int = Query(default=30, ge=1, le=90), ai: bool = True, q: str | None = Query(default=None, max_length=100),
           kind: str = Query(default="all", pattern="^(all|news|yc)$")):
    return _cached(("funded", days, ai, q, kind), 120, lambda: _funded(days, ai, q, kind))


def _open_jobs_by_company(s) -> dict[str, int]:
    rows = s.execute(select(Job.company, func.count()).where(Job.status == "open", Job.duplicate_of.is_(None))
                     .group_by(Job.company)).all()
    out: dict[str, int] = {}
    for company, n in rows:
        k = company_key(company)
        out[k] = out.get(k, 0) + n
    return out


def _funded(days, ai, q, kind):
    since = utcnow() - timedelta(days=days)
    with SessionLocal() as s:
        stmt = select(FundingEvent).where(FundingEvent.announced_at >= since)
        if ai:
            stmt = stmt.where(FundingEvent.ai.is_(True))
        if kind == "yc":
            stmt = stmt.where(FundingEvent.source == "yc")
        elif kind == "news":
            stmt = stmt.where(FundingEvent.source != "yc")
        if q:
            like = f"%{q.strip()}%"
            stmt = stmt.where((FundingEvent.company.ilike(like)) | (FundingEvent.one_liner.ilike(like)) | (FundingEvent.headline.ilike(like)))
        events = s.scalars(stmt.order_by(FundingEvent.announced_at.desc()).limit(400)).all()
        keys = [e.company_key for e in events]
        people: dict[str, list] = {}
        if keys:
            for p in s.scalars(select(Person).where(Person.company_key.in_(keys))):
                people.setdefault(p.company_key, []).append(
                    {"name": p.name, "title": p.title, "linkedin_url": p.linkedin_url, "x_url": p.x_url, "source_url": p.source_url})
        jobs = _cached("jobs_by_company", 300, lambda: _open_jobs_by_company(s))
    items = [{"id": e.id, "company": e.company, "company_key": e.company_key, "round": e.round, "amount": e.amount_text,
              "amount_usd": e.amount_usd, "website": e.website, "one_liner": e.one_liner, "location": e.location,
              "source": e.source, "url": e.url, "headline": e.headline, "ai": e.ai, "yc_slug": e.yc_slug,
              "announced_at": _iso(e.announced_at), "people": people.get(e.company_key, [])[:4],
              "open_jobs": jobs.get(e.company_key, 0)} for e in events]
    # Raises in the news first, then YC batch companies; each group stays newest first (stable sort).
    items.sort(key=lambda x: x["source"] == "yc")
    return {"items": items, "total": len(items)}

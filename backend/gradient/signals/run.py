"""Fetch all outreach signals and upsert them. Failures in one source never stop the others."""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import delete, select

from ..db import aware, init_db, session_scope, utcnow
from ..ingest.base import Http
from ..models import FundingEvent, HiringPost, Person
from . import fetch
from .parse import company_key, round_rank

log = logging.getLogger("gradient.signals")

POST_KEEP_DAYS = 10
FUNDING_KEEP_DAYS = 90
FOUNDER_LOOKUPS_PER_RUN = 120  # YC pages are fetched once per company, then cached in `people`


async def _gather():
    http = Http(max_concurrency=12, per_host=3)
    names = ("bluesky", "mastodon", "news", "yc")
    results = await asyncio.gather(fetch.bluesky(http), fetch.mastodon(http), fetch.funding_news(http),
                                   fetch.yc_recent(http), return_exceptions=True)
    out = {}
    for n, r in zip(names, results):
        if isinstance(r, Exception):
            log.warning("signals source %s failed: %s", n, r)
            out[n] = None
        else:
            out[n] = r
    return http, out


def _upsert_posts(s, posts: list[dict], now) -> int:
    if not posts:
        return 0
    existing = {p.post_id: p for p in s.scalars(select(HiringPost).where(HiringPost.post_id.in_([p["post_id"] for p in posts])))}
    new = 0
    for p in posts:
        row = existing.get(p["post_id"])
        if row:  # engagement changes; the rest doesn't
            row.likes, row.reposts, row.replies, row.fetched_at = p["likes"], p["reposts"], p["replies"], now
        else:
            s.add(HiringPost(**p, fetched_at=now))
            new += 1
    return new


def _upsert_funding(s, events: list[dict], yc_index: dict[str, dict], now) -> int:
    """One row per startup. A labelled round beats an unlabelled "raises funding" headline, and a
    news round beats the YC batch entry; the YC slug and website are kept either way."""
    best: dict[str, dict] = {}
    for e in events:
        key = company_key(e["company"])
        if not key:
            continue
        cur = best.get(key)
        if cur is None or (round_rank(e["round"]), e["announced_at"]) > (round_rank(cur["round"]), cur["announced_at"]):
            best[key] = {**e, "yc_slug": e.get("yc_slug") or (cur or {}).get("yc_slug")}
        elif e.get("yc_slug") and not cur.get("yc_slug"):
            cur["yc_slug"] = e["yc_slug"]
    new = 0
    existing = {r.company_key: r for r in s.scalars(select(FundingEvent).where(FundingEvent.company_key.in_(list(best))))} if best else {}
    for key, e in best.items():
        yc = yc_index.get(key)
        if yc:  # a news-funded startup that's also YC: we can find its founders
            e = {**e, "yc_slug": e.get("yc_slug") or yc.get("slug"), "website": e.get("website") or yc.get("website"),
                 "one_liner": e.get("one_liner") or (yc.get("one_liner") or "")[:500]}
        row = existing.get(key)
        if row is None:
            s.add(FundingEvent(company_key=key, **e, fetched_at=now))
            new += 1
            continue
        row.fetched_at = now
        row.yc_slug = row.yc_slug or e.get("yc_slug")
        row.website = row.website or e.get("website")
        row.one_liner = row.one_liner or e.get("one_liner")
        if (round_rank(e["round"]), aware(e["announced_at"])) > (round_rank(row.round), aware(row.announced_at)):
            for k in ("round", "amount_text", "amount_usd", "headline", "source", "url", "announced_at", "ai"):
                setattr(row, k, e[k])
    return new


async def _founders(http: Http, slugs: list[tuple[str, str]]) -> dict[str, list[dict]]:
    sem = asyncio.Semaphore(3)

    async def one(key: str, slug: str):
        async with sem:
            try:
                return key, await fetch.yc_founders(http, slug)
            except Exception as exc:
                log.warning("yc founders %s failed: %s", slug, exc)
                return key, []

    return dict(await asyncio.gather(*(one(k, s) for k, s in slugs)))


def run_signals() -> dict:
    init_db()
    now = utcnow()
    http, got = asyncio.run(_gather())
    stats: dict = {"failed": [k for k, v in got.items() if v is None]}

    posts = fetch.finish_posts((got["bluesky"] or []) + (got["mastodon"] or []))
    yc_events, yc_companies = got["yc"] or ([], [])
    yc_index = {company_key(c["name"]): c for c in yc_companies or [] if c.get("name")}
    events = (got["news"] or []) + yc_events

    with session_scope() as s:
        stats["posts_new"] = _upsert_posts(s, posts, now)
        stats["posts_seen"] = len(posts)
        stats["funding_new"] = _upsert_funding(s, events, yc_index, now)
        stats["funding_seen"] = len(events)
        s.execute(delete(HiringPost).where(HiringPost.posted_at < now - timedelta(days=POST_KEEP_DAYS)))
        s.execute(delete(FundingEvent).where(FundingEvent.announced_at < now - timedelta(days=FUNDING_KEEP_DAYS)))
        have_people = set(s.scalars(select(Person.company_key).distinct()))
        # Founder lookups: newest AI companies first, each company once.
        todo = s.execute(select(FundingEvent.company_key, FundingEvent.yc_slug)
                         .where(FundingEvent.yc_slug.is_not(None)).order_by(FundingEvent.ai.desc(), FundingEvent.announced_at.desc())).all()
    pending = list(dict.fromkeys((k, slug) for k, slug in todo if k not in have_people))[:FOUNDER_LOOKUPS_PER_RUN]
    founders = asyncio.run(_founders(http, pending)) if pending else {}
    with session_scope() as s:
        added = 0
        for key, people in founders.items():
            for p in people[:4]:
                if s.scalar(select(Person.id).where(Person.company_key == key, Person.name == p["name"])):
                    continue
                s.add(Person(company_key=key, **p, fetched_at=now))
                added += 1
        stats["people_new"] = added
        stats["founder_lookups"] = len(pending)
    return stats

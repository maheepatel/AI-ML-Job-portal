"""Network side of the outreach signals. Each fetcher returns plain dicts; run.py stores them."""

import asyncio
import html
import json
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

from ..domain.classify import extract_skills
from ..ingest.base import Http
from .parse import is_ai, is_hiring_post, parse_funding, strip_html

log = logging.getLogger("gradient.signals")

BROWSER = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}

BLUESKY_QUERIES = ["hiring machine learning", "hiring ML engineer", "hiring AI engineer", "we're hiring AI",
                   "hiring data scientist", "hiring LLM", "hiring founding engineer AI", "hiring computer vision"]
MASTODON = [("mastodon.social", t) for t in ("hiring", "aijobs", "mljobs", "getfedihired", "fedihire", "techjobs")]

NEWS_QUERIES = [
    'AI startup raises seed round when:7d',
    'AI startup raises pre-seed when:7d',
    'AI startup "series A" raises when:7d',
    'India startup raises seed funding AI when:7d',
    'Bengaluru startup raises pre-series A when:7d',
]
NEWS_FEEDS = [("techcrunch", "https://techcrunch.com/category/venture/feed/"),
              ("crunchbase-news", "https://news.crunchbase.com/feed/"),
              ("inc42", "https://inc42.com/feed/"),
              ("yourstory", "https://yourstory.com/feed")]


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        if value[:4].isdigit():
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsedate_to_datetime(value)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------- hiring posts


async def bluesky(http: Http) -> list[dict]:
    out: dict[str, dict] = {}

    async def one(q: str):
        url = f"https://api.bsky.app/xrpc/app.bsky.feed.searchPosts?q={quote_plus(q)}&sort=latest&limit=100"
        data = await http.get_json(url, headers=BROWSER)
        for p in data.get("posts", []):
            rec = p.get("record") or {}
            text = rec.get("text") or ""
            if not is_hiring_post(text):
                continue
            a = p.get("author") or {}
            rkey = p["uri"].rsplit("/", 1)[-1]
            links = [f["uri"] for fc in rec.get("facets") or [] for f in fc.get("features") or [] if f.get("uri")]
            ext = ((p.get("embed") or {}).get("external") or {}).get("uri")
            if ext:
                links.append(ext)
            out[p["uri"]] = {
                "source": "bluesky", "post_id": p["uri"], "url": f"https://bsky.app/profile/{a.get('handle')}/post/{rkey}",
                "author": a.get("displayName") or a.get("handle") or "", "author_handle": a.get("handle") or "",
                "author_url": f"https://bsky.app/profile/{a.get('handle')}", "text": text[:3000],
                "likes": p.get("likeCount") or 0, "reposts": p.get("repostCount") or 0, "replies": p.get("replyCount") or 0,
                "links": list(dict.fromkeys(links))[:6], "posted_at": _dt(rec.get("createdAt")) or _dt(p.get("indexedAt")),
            }

    results = await asyncio.gather(*(one(q) for q in BLUESKY_QUERIES), return_exceptions=True)
    for q, r in zip(BLUESKY_QUERIES, results):
        if isinstance(r, Exception):
            log.warning("bluesky %r failed: %s", q, r)
    return list(out.values())


async def mastodon(http: Http) -> list[dict]:
    out: dict[str, dict] = {}

    async def one(host: str, tag: str):
        data = await http.get_json(f"https://{host}/api/v1/timelines/tag/{tag}?limit=40", headers=BROWSER)
        for s in data:
            text = strip_html(s.get("content") or "")
            if not is_hiring_post(text):
                continue
            acct = s.get("account") or {}
            out[s["uri"]] = {
                "source": "mastodon", "post_id": s["uri"], "url": s.get("url") or s["uri"],
                "author": acct.get("display_name") or acct.get("acct") or "", "author_handle": acct.get("acct") or "",
                "author_url": acct.get("url") or "", "text": text[:3000],
                "likes": s.get("favourites_count") or 0, "reposts": s.get("reblogs_count") or 0,
                "replies": s.get("replies_count") or 0,
                "links": [(s.get("card") or {}).get("url")] if (s.get("card") or {}).get("url") else [],
                "posted_at": _dt(s.get("created_at")),
            }

    results = await asyncio.gather(*(one(h, t) for h, t in MASTODON), return_exceptions=True)
    for (h, t), r in zip(MASTODON, results):
        if isinstance(r, Exception):
            log.warning("mastodon %s #%s failed: %s", h, t, r)
    return list(out.values())


def finish_posts(posts: list[dict]) -> list[dict]:
    for p in posts:
        p["skills"] = extract_skills(p["text"])[:10]
    return [p for p in posts if p["posted_at"]]


# ---------------------------------------------------------------- funding


def _rss_items(xml: str) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return []
    items = []
    for it in root.iter("item"):
        items.append({"title": html.unescape(it.findtext("title") or ""), "link": it.findtext("link") or "",
                      "date": _dt(it.findtext("pubDate")), "desc": strip_html(it.findtext("description") or "")[:500]})
    return items


async def funding_news(http: Http) -> list[dict]:
    feeds = [(f"google-news", "https://news.google.com/rss/search?q=" + quote_plus(q) + "&hl=en-IN&gl=IN&ceid=IN:en")
             for q in NEWS_QUERIES] + NEWS_FEEDS
    results = await asyncio.gather(*(http.get_text(u, headers=BROWSER) for _, u in feeds), return_exceptions=True)
    events: list[dict] = []
    for (src, url), body in zip(feeds, results):
        if isinstance(body, Exception):
            log.warning("funding feed %s failed: %s", url, body)
            continue
        for it in _rss_items(body):
            parsed = parse_funding(it["title"])
            if not parsed or not it["date"]:
                continue
            events.append({**parsed, "source": src, "url": it["link"], "announced_at": it["date"],
                           "ai": is_ai(f"{it['title']} {it['desc']}"), "one_liner": None, "website": None,
                           "location": None, "yc_slug": None})
    return events


YC_META = "https://yc-oss.github.io/api/meta.json"
YC_ALL = "https://yc-oss.github.io/api/companies/all.json"


async def yc_recent(http: Http, batches: int = 3) -> tuple[list[dict], list[dict]]:
    """Newest YC batches as funding events (YC invests in every company), plus the full
    company list so news-funded startups can be matched to their YC page."""
    meta = await http.get_json(YC_META)
    recent = list((meta.get("batches") or {}).items())[:batches]
    companies = await http.get_json(YC_ALL)
    events = []
    for key, info in recent:
        try:
            rows = await http.get_json(info["api"])
        except Exception as exc:
            log.warning("yc batch %s failed: %s", key, exc)
            continue
        for c in rows:
            launched = c.get("launched_at")
            when = datetime.fromtimestamp(launched, timezone.utc) if isinstance(launched, (int, float)) else datetime.now(timezone.utc)
            text = " ".join([c.get("one_liner") or "", " ".join(c.get("tags") or []), " ".join(c.get("industries") or [])])
            events.append({
                "company": c["name"], "round": f"yc-{key}", "amount_text": "YC standard deal", "amount_usd": 500_000,
                "headline": f"{c['name']} joined Y Combinator {info['name']}", "source": "yc",
                "url": c.get("url") or f"https://www.ycombinator.com/companies/{c.get('slug')}", "announced_at": when,
                "ai": is_ai(text), "one_liner": (c.get("one_liner") or "")[:500], "website": c.get("website"),
                "location": c.get("all_locations"), "yc_slug": c.get("slug"),
            })
    return events, companies


_DATA_PAGE = re.compile(r'data-page="([^"]+)"')


async def yc_founders(http: Http, slug: str) -> list[dict]:
    """Founders as YC lists them publicly on the company page: name, title, LinkedIn, X."""
    body = await http.get_text(f"https://www.ycombinator.com/companies/{slug}", headers=BROWSER)
    m = _DATA_PAGE.search(body)
    if not m:
        return []
    try:
        company = json.loads(html.unescape(m.group(1)))["props"]["company"]
    except (KeyError, json.JSONDecodeError):
        return []
    out = []
    for f in company.get("founders") or []:
        if not f.get("full_name"):
            continue
        out.append({"name": f["full_name"][:200], "title": (f.get("title") or "Founder")[:200],
                    "linkedin_url": f.get("linkedin_url"), "x_url": f.get("twitter_url"),
                    "source": "yc", "source_url": f"https://www.ycombinator.com/companies/{slug}"})
    return out

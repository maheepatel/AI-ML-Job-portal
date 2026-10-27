"""LinkedIn public guest job search (the logged-out jobs pages). Read-only, no login, and no
challenge bypass: if LinkedIn throttles us (429/999) the source stops early and keeps what it has."""

import asyncio
from datetime import datetime, timezone
from urllib.parse import quote

from scrapling.parser import Selector

from ...domain.classify import title_candidate
from ...domain.normalize import parse_relative
from ..base import FetchResult, Http, RawJob, Source, SourceError

KEYWORDS = [
    "machine learning engineer", "data scientist", "AI engineer", "generative AI", "LLM engineer",
    "computer vision engineer", "NLP engineer", "MLOps engineer", "applied scientist", "deep learning",
]
LOCATIONS = ["India", "Bengaluru", "United States", "European Union"]
SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
DETAIL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"


class LinkedInGuest(Source):
    name = "linkedin"
    kind = "linkedin"
    priority = 60

    def __init__(self, keywords: list[str] | None = None, locations: list[str] | None = None, pages: int = 3):
        super().__init__("guest", "LinkedIn")
        self.keywords = keywords or KEYWORDS
        self.locations = locations or LOCATIONS
        self.pages = pages

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        cards: dict[str, dict] = {}
        now = datetime.now(timezone.utc)
        throttled = False

        async def search(kw: str, loc: str):
            nonlocal throttled
            for page in range(self.pages):
                if throttled:
                    return
                # f_E 1,2,3 = internship, entry, associate. f_TPR r604800 = posted in the last week.
                url = f"{SEARCH}?keywords={quote(kw)}&location={quote(loc)}&f_E=1%2C2%2C3&f_TPR=r604800&start={page * 10}"
                try:
                    resp = await http.get(url, attempts=2)
                except SourceError:
                    throttled = True
                    return
                if resp.status != 200:
                    throttled = resp.status in (429, 999)
                    return
                found = 0
                for li in resp.css("li"):
                    card = li.css("div.base-card").first or li.css("[data-entity-urn]").first
                    if card is None:
                        continue
                    urn = card.attrib.get("data-entity-urn", "")
                    jid = urn.rsplit(":", 1)[-1]
                    if not jid.isdigit():
                        continue
                    found += 1
                    time_el = li.css("time").first
                    cards[jid] = {
                        "title": _text(li.css("h3").first),
                        "company": _text(li.css("h4").first),
                        "location": _text(li.css(".job-search-card__location").first),
                        "url": (li.css("a.base-card__full-link").first or li.css("a").first).attrib.get("href", "").split("?")[0],
                        "posted": parse_relative(_text(time_el), now) if time_el else None,
                        "date": time_el.attrib.get("datetime") if time_el else None,
                    }
                if found < 10:
                    return

        for kw in self.keywords:
            await asyncio.gather(*(search(kw, loc) for loc in self.locations))
        if not cards and throttled:
            raise SourceError("LinkedIn throttled the guest API (429/999)")

        out.seen_ids = set(cards)
        detail_blocked = False  # search and detail endpoints are throttled independently

        async def detail(jid: str, c: dict) -> RawJob | None:
            nonlocal detail_blocked
            if skipped := self.known(jid, c["title"], c["url"], c["company"]):
                return skipped
            description, criteria = "", ""
            if not detail_blocked:
                try:
                    resp = await http.get(DETAIL.format(id=jid), attempts=2)
                    if resp.status == 200:
                        description = (resp.css(".show-more-less-html__markup").first or resp).get_all_text(separator="\n")
                        criteria = " ".join(t.strip() for t in resp.css(".description__job-criteria-text::text").getall())
                    elif resp.status in (429, 999):
                        detail_blocked = True
                except SourceError:
                    detail_blocked = True  # stored without description; retried next run
            posted = c["posted"]
            if posted is None and c["date"]:
                posted = datetime.fromisoformat(c["date"]).replace(tzinfo=timezone.utc)
            return RawJob(
                source_job_id=jid, title=c["title"], company=c["company"],
                url=c["url"] or f"https://www.linkedin.com/jobs/view/{jid}",
                description=f"{description}\n{criteria}".strip(), location=c["location"], posted_at=posted,
            )

        wanted = [(jid, c) for jid, c in cards.items() if c["title"] and title_candidate(c["title"])]
        out.jobs = [r for r in await asyncio.gather(*(detail(j, c) for j, c in wanted)) if r]
        return out


def _text(el) -> str:
    if el is None:
        return ""
    return " ".join(el.get_all_text().split())


__all__ = ["LinkedInGuest", "Selector"]

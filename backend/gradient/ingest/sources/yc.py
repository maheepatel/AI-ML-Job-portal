"""Y Combinator startups, a main source.

All public and logged out:
- `YCJobBoard`: YC's own job board on ycombinator.com (Work at a Startup postings). Each run
  reads a few role pages plus a rotating slice of AI/ML-tagged hiring companies' jobs pages.
  ycombinator.com answers HTTP 429 after roughly 25 page loads in a burst, so the source stays
  near that budget, spaces its requests, and stops at the first 429, keeping what it has.
  Listings carry title, location, salary, minimum experience and skills, which is enough to
  classify, so no per-job detail page is loaded. Searched, so not authoritative: closures
  come from liveness checks and expiry.
- `yc_directory()`: the yc-oss mirror of the YC directory (GitHub Pages JSON): hiring
  companies, plus AI/ML-tagged ones.
- `crawl_yc_websites()`: visits a rotating slice of YC company websites and their careers
  page, and turns every ATS link found there (Ashby, Greenhouse, Lever, …) into a board with
  origin `yc`. Those boards then sweep like any other ATS board, on the ATS's own API.
"""

import asyncio
import re
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

from ...domain.classify import title_candidate
from ...domain.normalize import parse_relative
from ..base import FetchResult, Http, RawJob, Source, SourceError
from ..discovery import board_from_url
from ._html import inertia_props

YC = "https://www.ycombinator.com"
DIRECTORY = {
    "hiring": "https://yc-oss.github.io/api/companies/hiring.json",
    "ai": [
        "https://yc-oss.github.io/api/tags/artificial-intelligence.json",
        "https://yc-oss.github.io/api/tags/generative-ai.json",
        "https://yc-oss.github.io/api/tags/machine-learning.json",
    ],
}
_EXPERIENCE = re.compile(r"(\d+)\+?\s*years?", re.I)


ROLE_PAGES = ["/jobs/role/software-engineer/machine-learning", "/jobs/role/science", "/jobs/role/software-engineer/remote",
              "/jobs/role/software-engineer/india", "/jobs/role/software-engineer/san-francisco", "/jobs/role/software-engineer/new-york"]
_AI_TAG = re.compile(r"\b(ai|artificial intelligence|machine learning|generative ai|deep learning|computer vision|nlp|ml|llm|robotics)\b", re.I)


def ai_hiring(hiring: list[dict]) -> list[dict]:
    """Hiring YC companies tagged or described as AI/ML, in a stable order for rotation."""
    out = [c for c in hiring if c.get("slug") and _AI_TAG.search(" ".join(c.get("tags") or []) + " " + (c.get("one_liner") or ""))]
    return sorted(out, key=lambda c: c["slug"])


class YCJobBoard(Source):
    name = "yc"
    kind = "ats"  # the employer's own posting on YC's job board
    priority = 80  # the same job on the company's own ATS wins
    BUDGET = 22  # page loads per run on ycombinator.com
    PAUSE_S = 1.5

    def __init__(self, companies: list[dict] | None = None, run_id: int = 0):
        super().__init__("waas", "Y Combinator")
        self.companies = companies or []
        self.run_id = run_id

    def pages(self) -> list[str]:
        n = max(0, self.BUDGET - len(ROLE_PAGES))
        slice_ = []
        if self.companies and n:
            start = (self.run_id * n) % len(self.companies)
            slice_ = (self.companies * 2)[start: start + min(n, len(self.companies))]
        return ROLE_PAGES + [f"/companies/{c['slug']}/jobs" for c in slice_]

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        loaded = 0
        for path in self.pages():
            try:
                props = inertia_props(await http.get_text(YC + path, attempts=1))
            except SourceError:
                break  # 429 (or an outage): stop here, keep what this run already read
            loaded += 1
            company = props.get("company") or {}
            for p in props.get("jobPostings") or []:
                jid = str(p["id"])
                if jid in out.seen_ids:
                    continue
                out.seen_ids.add(jid)
                if title_candidate(p.get("title", "")):
                    out.jobs.append(self.to_raw(p, company))
            await asyncio.sleep(self.PAUSE_S)
        if not loaded:
            raise SourceError("ycombinator.com answered no pages this run (rate limited)")
        return out

    def to_raw(self, p: dict, company: dict) -> RawJob:
        facts = [p.get("companyOneLiner") or company.get("one_liner") or ""]
        exp = p.get("minExperience") or ""
        if exp:
            # "Any (new grads ok)" / "3+ years": phrased so the experience extractor reads it.
            facts.append(f"Experience: {exp}" + (" of experience" if _EXPERIENCE.search(exp) else ""))
        if p.get("roleSpecificType") or p.get("prettyRole"):
            facts.append(f"Role: {p.get('prettyRole') or ''} {p.get('roleSpecificType') or ''}".strip())
        if p.get("skills"):
            facts.append("Skills: " + ", ".join(p["skills"]))
        if p.get("visa"):
            facts.append(f"Visa: {p['visa']}")
        if p.get("equityRange"):
            facts.append(f"Equity: {p['equityRange']}")
        location = p.get("location") or ""
        name = p.get("companyName") or company.get("name") or ""
        batch = p.get("companyBatchName") or company.get("batch_name")
        return RawJob(
            source_job_id=str(p["id"]),
            title=" ".join((p.get("title") or "").split()),
            company=name,
            url=urljoin(YC, p.get("url") or ""),
            description="".join(f"<p>{f}</p>" for f in facts if f) + (f"<p>Y Combinator {batch}</p>" if batch else ""),
            location=location,
            remote=("remote" in location.lower()) or None,
            posted_at=parse_relative(f"{p['createdAt']} ago", datetime.now(timezone.utc)) if p.get("createdAt") else None,
            employment_type=p.get("type"),
            salary_text=p.get("salaryRange") or "",
            company_domain=urlparse(company.get("website") or "").hostname,
        )


async def yc_directory(http: Http) -> tuple[list[dict], list[dict]]:
    """(hiring companies, wider crawl list: hiring first, then active AI companies)."""
    hiring = await http.get_json(DIRECTORY["hiring"], timeout=60)
    crawl = {c["slug"]: c for c in hiring if c.get("slug")}
    for url in DIRECTORY["ai"]:
        try:
            for c in await http.get_json(url, timeout=60):
                if c.get("slug") and c.get("status") in (None, "Active") and c.get("website"):
                    crawl.setdefault(c["slug"], c)
        except Exception:
            continue  # the hiring list alone is still a useful run
    return hiring, list(crawl.values())


_CAREERS_LINK = re.compile(r'href="([^"#]*?(?:careers?|jobs|join|hiring|work-with-us)[^"#]*)"', re.I)
_HREF = re.compile(r'(?:href|src)="([^"]+)"', re.I)


def ats_links(page: str, base: str) -> tuple[set[tuple[str, str]], str | None]:
    """ATS boards linked from a page, plus the page's own careers link (same site) if any."""
    found = set()
    for href in _HREF.findall(page or ""):
        if b := board_from_url(urljoin(base, href.replace("&amp;", "&"))):
            found.add(b)
    careers = None
    host = urlparse(base).hostname or ""
    for href in _CAREERS_LINK.findall(page or ""):
        url = urljoin(base, href)
        if (urlparse(url).hostname or "").removeprefix("www.") == host.removeprefix("www."):
            careers = url
            break
    return found, careers


async def crawl_yc_websites(http: Http, companies: list[dict], run_id: int, per_run: int = 600) -> dict[tuple[str, str], str]:
    """Visit this run's slice of company websites (+ one careers page each) and collect ATS boards."""
    if not companies:
        return {}
    companies = sorted(companies, key=lambda c: c["slug"])
    start = (run_id * per_run) % len(companies)
    batch = (companies + companies)[start: start + min(per_run, len(companies))]
    found: dict[tuple[str, str], str] = {}

    async def one(c: dict) -> None:
        site = c.get("website") or ""
        if not site.startswith("http"):
            return
        try:
            boards, careers = ats_links(await http.get_text(site, attempts=1, timeout=12), site)
            if not boards and careers:
                boards, _ = ats_links(await http.get_text(careers, attempts=1, timeout=12), careers)
        except Exception:
            return
        for b in boards:
            if b[0] != "yc":
                found.setdefault(b, c.get("name") or c["slug"])

    await asyncio.gather(*(one(c) for c in batch))
    return found

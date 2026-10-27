"""Large employers with their own careers APIs. These are searched by keyword, so they are
not authoritative; closures are confirmed by liveness checks against each job's own endpoint."""

import asyncio
from datetime import datetime, timezone

from ...domain.classify import title_candidate
from ...domain.normalize import parse_dt, parse_relative
from ..base import FetchResult, Http, RawJob, Source, SourceError

SEARCH_TERMS = ["machine learning", "data scientist", "artificial intelligence", "deep learning", "applied scientist", "AI engineer"]


class Workday(Source):
    """Any company on Workday: https://{tenant}.{wd}.myworkdayjobs.com/{site}."""

    name = "workday"
    kind = "bigtech"
    priority = 85

    def __init__(self, tenant: str, wd: str, site: str, company: str, domain: str | None = None, terms: list[str] | None = None):
        super().__init__(f"{tenant}", company, domain)
        self.host = f"https://{tenant}.{wd}.myworkdayjobs.com"
        self.api = f"{self.host}/wday/cxs/{tenant}/{site}"
        self.site = site
        self.terms = terms or SEARCH_TERMS[:3]

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        postings: dict[str, dict] = {}
        for term in self.terms:
            for offset in range(0, 100, 20):  # newest 100 per keyword; known jobs skip detail calls
                page = await http.post_json(
                    f"{self.api}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": term}
                )
                items = page.get("jobPostings", [])
                for p in items:
                    if p.get("externalPath"):
                        postings[p["externalPath"]] = p
                if len(items) < 20 or offset + 20 >= page.get("total", 0):
                    break
        now = datetime.now(timezone.utc)
        out.seen_ids = set(postings)

        async def detail(path: str, p: dict) -> RawJob | None:
            if skipped := self.known(path, p.get("title", ""), ""):
                return skipped
            try:
                info = (await http.get_json(f"{self.api}{path}")).get("jobPostingInfo", {})
            except Exception:
                return None
            return RawJob(
                source_job_id=path,
                title=info.get("title") or p.get("title", ""),
                company=self.company,
                url=info.get("externalUrl") or f"{self.host}/{self.site}{path}",
                description=info.get("jobDescription", ""),
                location=info.get("location") or p.get("locationsText", ""),
                remote=("remote" in (info.get("remoteType") or "").lower()) or None,
                posted_at=parse_dt(info.get("startDate")) or parse_relative(p.get("postedOn", ""), now),
                employment_type=info.get("timeType"),
                company_domain=self.domain,
            )

        wanted = [(path, p) for path, p in postings.items() if title_candidate(p.get("title", ""))]
        out.jobs = [r for r in await asyncio.gather(*(detail(path, p) for path, p in wanted)) if r]
        return out


class Amazon(Source):
    name = "amazon"
    kind = "bigtech"
    priority = 85

    def __init__(self):
        super().__init__("jobs", "Amazon", "amazon.jobs")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        seen: dict[str, dict] = {}
        for term in ["machine learning", "applied scientist", "data scientist", "generative ai", "deep learning"]:
            for offset in range(0, 300, 100):
                data = await http.get_json(
                    "https://www.amazon.jobs/en/search.json",
                    params={"base_query": term, "result_limit": 100, "offset": offset, "sort": "recent"},
                )
                jobs = data.get("jobs", [])
                for j in jobs:
                    seen[j["id_icims"]] = j
                if len(jobs) < 100:
                    break
        out.seen_ids = set(seen)
        for jid, j in seen.items():
            desc = "\n\n".join(filter(None, [
                j.get("description", ""),
                "Basic qualifications\n" + (j.get("basic_qualifications") or ""),
                "Preferred qualifications\n" + (j.get("preferred_qualifications") or ""),
            ]))
            posted = None
            try:
                posted = datetime.strptime(j.get("posted_date", ""), "%B %d, %Y").replace(tzinfo=timezone.utc)
            except ValueError:
                pass
            out.jobs.append(RawJob(
                source_job_id=jid,
                title=j.get("title", ""),
                company="Amazon" if "aws" not in (j.get("company_name") or "").lower() else "Amazon Web Services",
                url="https://www.amazon.jobs" + j.get("job_path", ""),
                description=desc,
                location=j.get("normalized_location") or j.get("location", ""),
                posted_at=posted,
                employment_type=j.get("job_schedule_type"),
                company_domain="amazon.jobs",
            ))
        return out


class Microsoft(Source):
    name = "microsoft"
    kind = "bigtech"
    priority = 85
    base = "https://apply.careers.microsoft.com"

    def __init__(self):
        super().__init__("careers", "Microsoft", "microsoft.com")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        positions: dict[str, dict] = {}
        for term in ["machine learning", "data scientist", "applied scientist"]:
            for start in range(0, 100, 10):
                await asyncio.sleep(0.6)  # Microsoft rate-limits bursts with 429s
                try:
                    data = await http.get_json(
                        f"{self.base}/api/pcsx/search",
                        params={"domain": "microsoft.com", "query": term, "start": start, "sort_by": "timestamp"},
                    )
                except SourceError:
                    if not positions:
                        raise
                    break  # throttled mid-way: keep what we have (search sources never close jobs by absence)
                items = (data.get("data") or {}).get("positions", [])
                for p in items:
                    positions[str(p["id"])] = p
                if len(items) < 10:
                    break
        out.seen_ids = set(positions)

        async def detail(pid: str, p: dict) -> RawJob | None:
            if skipped := self.known(pid, p.get("name", ""), ""):
                return skipped
            try:
                d = (await http.get_json(
                    f"{self.base}/api/pcsx/position_details", params={"position_id": pid, "domain": "microsoft.com"}
                )).get("data", {})
            except Exception:
                return None
            return RawJob(
                source_job_id=pid,
                title=d.get("name") or p.get("name", ""),
                company="Microsoft",
                url=f"{self.base}{p.get('positionUrl') or '/careers/job/' + pid}",
                description=d.get("jobDescription", ""),
                location=" / ".join(p.get("locations") or []),
                remote=(p.get("workLocationOption") == "remote") or None,
                posted_at=parse_dt(p.get("postedTs") or p.get("creationTs")),
                company_domain="microsoft.com",
            )

        wanted = [(pid, p) for pid, p in positions.items() if title_candidate(p.get("name", ""))]
        out.jobs = [r for r in await asyncio.gather(*(detail(pid, p) for pid, p in wanted)) if r]
        return out

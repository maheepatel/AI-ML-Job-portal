"""Employer applicant-tracking systems. These return a company's complete public listing,
so they are authoritative: a job that disappears here has really been taken down."""

import asyncio

from ...domain.classify import title_candidate
from ...domain.normalize import parse_dt
from ..base import FetchResult, Http, RawJob, Source


class AtsSource(Source):
    kind = "ats"
    authoritative = True
    priority = 90

    def __init__(self, slug: str, company: str | None = None, domain: str | None = None):
        super().__init__(slug, company or slug.replace("-", " ").title(), domain)
        self.slug = slug


class Greenhouse(AtsSource):
    name = "greenhouse"

    async def fetch(self, http: Http) -> FetchResult:
        data = await http.get_json(f"https://boards-api.greenhouse.io/v1/boards/{self.slug}/jobs?content=true", timeout=90)  # some boards are 10MB+
        out = FetchResult()
        for j in data.get("jobs", []):
            jid = str(j["id"])
            out.seen_ids.add(jid)
            out.jobs.append(RawJob(
                source_job_id=jid,
                title=j.get("title", ""),
                company=j.get("company_name") or self.company,
                url=j.get("absolute_url", ""),
                description=j.get("content", ""),
                location=(j.get("location") or {}).get("name", ""),
                posted_at=parse_dt(j.get("first_published") or j.get("updated_at")),
                deadline_at=parse_dt(j.get("application_deadline")),
                company_domain=self.domain,
            ))
        return out


class Lever(AtsSource):
    name = "lever"

    async def fetch(self, http: Http) -> FetchResult:
        data = await http.get_json(f"https://api.lever.co/v0/postings/{self.slug}?mode=json")
        out = FetchResult()
        for j in data:
            out.seen_ids.add(j["id"])
            cats = j.get("categories") or {}
            sal = j.get("salaryRange") or {}
            lists = "\n".join(f"{x.get('text', '')}\n{x.get('content', '')}" for x in j.get("lists", []))
            out.jobs.append(RawJob(
                source_job_id=j["id"],
                title=j.get("text", ""),
                company=self.company,
                url=j.get("hostedUrl", ""),
                description=f"{j.get('description', '')}\n{lists}\n{j.get('additional', '')}",
                location=" / ".join(cats.get("allLocations") or [cats.get("location") or ""]),
                remote=j.get("workplaceType") == "remote" or None,
                posted_at=parse_dt(j.get("createdAt")),
                employment_type=cats.get("commitment"),
                salary_min=sal.get("min"), salary_max=sal.get("max"),
                salary_currency=sal.get("currency"), salary_period="year" if sal else None,
                company_domain=self.domain,
            ))
        return out


class Ashby(AtsSource):
    name = "ashby"

    async def fetch(self, http: Http) -> FetchResult:
        data = await http.get_json(f"https://api.ashbyhq.com/posting-api/job-board/{self.slug}?includeCompensation=true")
        out = FetchResult()
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            out.seen_ids.add(j["id"])
            comp = next(
                (c for t in (j.get("compensation") or {}).get("compensationTiers", []) for c in t.get("components", [])
                 if c.get("compensationType") == "Salary"),
                {},
            )
            locs = [j.get("location") or ""] + [s.get("location", "") for s in j.get("secondaryLocations", [])]
            out.jobs.append(RawJob(
                source_job_id=j["id"],
                title=j.get("title", ""),
                company=self.company,
                url=j.get("jobUrl", ""),
                description=j.get("descriptionHtml") or j.get("descriptionPlain", ""),
                location=" / ".join(filter(None, locs)),
                remote=bool(j.get("isRemote")) or j.get("workplaceType") == "Remote" or None,
                posted_at=parse_dt(j.get("publishedAt")),
                employment_type=j.get("employmentType"),
                salary_min=comp.get("minValue"), salary_max=comp.get("maxValue"),
                salary_currency=comp.get("currencyCode"),
                salary_period="year" if "YEAR" in str(comp.get("interval", "")) else ("hour" if comp else None),
                company_domain=self.domain,
            ))
        return out


class Workable(AtsSource):
    name = "workable"

    async def fetch(self, http: Http) -> FetchResult:
        data = await http.get_json(f"https://apply.workable.com/api/v1/widget/accounts/{self.slug}?details=true")
        out = FetchResult()
        company = data.get("name") or self.company
        for j in data.get("jobs", []):
            jid = j.get("shortcode")
            out.seen_ids.add(jid)
            loc = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
            out.jobs.append(RawJob(
                source_job_id=jid,
                title=j.get("title", ""),
                company=company,
                url=j.get("url") or f"https://apply.workable.com/j/{jid}",
                description=j.get("description", ""),
                location=loc,
                remote=bool(j.get("telecommuting")) or None,
                posted_at=parse_dt(j.get("published_on") or j.get("created_at")),
                employment_type=j.get("employment_type"),
                company_domain=self.domain,
            ))
        return out


class Recruitee(AtsSource):
    name = "recruitee"

    async def fetch(self, http: Http) -> FetchResult:
        data = await http.get_json(f"https://{self.slug}.recruitee.com/api/offers/")
        out = FetchResult()
        for j in data.get("offers", []):
            jid = str(j["id"])
            out.seen_ids.add(jid)
            sal = j.get("salary") or {}
            out.jobs.append(RawJob(
                source_job_id=jid,
                title=j.get("title", ""),
                company=j.get("company_name") or self.company,
                url=j.get("careers_url") or j.get("careers_apply_url", ""),
                description=f"{j.get('description', '')}\n{j.get('requirements', '')}",
                location=j.get("location", ""),
                remote=bool(j.get("remote")) or None,
                posted_at=parse_dt(j.get("published_at")),
                deadline_at=parse_dt(j.get("close_at")),
                employment_type=j.get("employment_type_code"),
                salary_min=_num(sal.get("min")), salary_max=_num(sal.get("max")),
                salary_currency=sal.get("currency"), salary_period=sal.get("period"),
                company_domain=self.domain,
            ))
        return out


class SmartRecruiters(AtsSource):
    name = "smartrecruiters"

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        listing: list[dict] = []
        offset = 0
        while offset < 3000:
            page = await http.get_json(
                f"https://api.smartrecruiters.com/v1/companies/{self.slug}/postings?limit=100&offset={offset}"
            )
            content = page.get("content", [])
            listing += content
            offset += 100
            if not content or offset >= page.get("totalFound", 0):
                break

        wanted = []
        for j in listing:
            out.seen_ids.add(j["id"])
            if title_candidate(j.get("name", "")):
                wanted.append(j)

        async def detail(j: dict) -> RawJob | None:
            if skipped := self.known(j["id"], j.get("name", ""), ""):
                return skipped
            try:
                d = await http.get_json(f"https://api.smartrecruiters.com/v1/companies/{self.slug}/postings/{j['id']}")
            except Exception:
                return None
            sections = (d.get("jobAd") or {}).get("sections") or {}
            text = "\n".join((sections.get(k) or {}).get("text", "") for k in ("jobDescription", "qualifications", "additionalInformation"))
            loc = d.get("location") or {}
            return RawJob(
                source_job_id=j["id"],
                title=d.get("name", j.get("name", "")),
                company=(d.get("company") or {}).get("name") or self.company,
                url=d.get("postingUrl") or f"https://jobs.smartrecruiters.com/{self.slug}/{j['id']}",
                description=text,
                location=", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country", "").upper()])),
                remote=bool(loc.get("remote")) or None,
                posted_at=parse_dt(d.get("releasedDate")),
                employment_type=(d.get("typeOfEmployment") or {}).get("label"),
                company_domain=self.domain,
            )

        out.jobs = [r for r in await asyncio.gather(*(detail(j) for j in wanted)) if r]
        return out


def _num(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


ATS_TYPES: dict[str, type[AtsSource]] = {
    cls.name: cls for cls in (Greenhouse, Lever, Ashby, Workable, Recruitee, SmartRecruiters)
}

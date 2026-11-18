"""Regional public job APIs (no login, allowed by each site's robots.txt):

- MyCareersFuture (Singapore, government job bank): api.mycareersfuture.gov.sg
- Get on Board (Chile, LatAm, remote Spanish/Portuguese tech): getonbrd.com/api/v0
- Habr Career (Russia / CIS tech jobs): career.habr.com frontend API
- Working Nomads (remote, worldwide): workingnomads.com/api/exposed_jobs

Checked and left out on purpose: hh.ru (anonymous API now answers 403, it needs a registered
OAuth app), Bundesagentur für Arbeit (403), jobs.ch, landing.jobs and justjoin.it (their
robots.txt disallows /api/), Seek/Naukri (bot walls).
"""

import asyncio
from urllib.parse import quote

from ...domain.classify import title_candidate
from ...domain.normalize import parse_dt
from ..base import FetchResult, Http, RawJob
from ._html import jsonld_jobposting
from .boards import BoardSource

TERMS = ["machine learning", "data scientist", "artificial intelligence", "AI engineer", "deep learning", "computer vision", "NLP"]


class MyCareersFuture(BoardSource):
    name = "mycareersfuture"
    priority = 50  # employer-posted to a government portal (UEN-registered companies)

    def __init__(self):
        super().__init__("sg", "MyCareersFuture")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()

        async def search(term: str, page: int):
            url = f"https://api.mycareersfuture.gov.sg/v2/jobs?search={quote(term)}&limit=100&page={page}&sortBy=new_posting_date"
            try:
                return (await http.get_json(url)).get("results", [])
            except Exception:
                return []

        pages = await asyncio.gather(*(search(t, p) for t in TERMS[:5] for p in range(2)))
        for results in pages:
            for j in results:
                if j["uuid"] in out.seen_ids:
                    continue
                out.seen_ids.add(j["uuid"])
                out.jobs.append(self.to_raw(j))
        return out

    @staticmethod
    def to_raw(j: dict) -> RawJob:
        meta = j.get("metadata") or {}
        sal = j.get("salary") or {}
        company = (j.get("hiringCompany") or {}).get("name") or (j.get("postedCompany") or {}).get("name", "")
        years = j.get("minimumYearsExperience")
        desc = j.get("description", "")
        if years not in (None, ""):
            desc += f"<p>Minimum {years} years of experience</p>"
        levels = ", ".join(p.get("position", "") for p in j.get("positionLevels") or [])
        address = j.get("address") or {}
        location = "Singapore" if not address.get("isOverseas") else (address.get("overseasCountry") or "")
        return RawJob(
            source_job_id=j["uuid"],
            title=j.get("title", ""),
            company=company.title() if company.isupper() else company,
            url=meta.get("jobDetailsUrl") or f"https://www.mycareersfuture.gov.sg/job/{j['uuid']}",
            description=desc + (f"<p>Level: {levels}</p>" if levels else ""),
            location=location,
            posted_at=parse_dt(meta.get("newPostingDate") or meta.get("createdAt")),
            deadline_at=parse_dt(meta.get("expiryDate")),
            employment_type=", ".join(e.get("employmentType", "") for e in j.get("employmentTypes") or []) or None,
            salary_min=sal.get("minimum"), salary_max=sal.get("maximum"), salary_currency="SGD" if sal else None,
            salary_period="month" if (sal.get("type") or {}).get("salaryType") == "Monthly" else ("year" if sal else None),
        )


# Get on Board seniority ids: 1 no experience, 2 junior, 3 semi senior, 4 senior, 5 expert.
_GOB_SENIORITY = {1: "No experience required", 2: "Junior", 3: "Semi senior (2-4 years of experience)", 4: "Senior", 5: "Expert"}


class GetOnBoard(BoardSource):
    name = "getonbrd"

    def __init__(self):
        super().__init__("latam", "Get on Board")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()

        async def search(term: str):
            url = f"https://www.getonbrd.com/api/v0/search/jobs?query={quote(term)}&per_page=100&expand=%5B%22company%22%5D"
            try:
                return await http.get_json(url)
            except Exception:
                return {}

        for data in await asyncio.gather(*(search(t) for t in TERMS[:5])):
            companies = {c["id"]: c.get("attributes", {}) for c in data.get("included", []) if c.get("type") == "company"}
            for j in data.get("data", []):
                if j["id"] in out.seen_ids:
                    continue
                out.seen_ids.add(j["id"])
                out.jobs.append(self.to_raw(j, companies))
        return out

    @staticmethod
    def to_raw(j: dict, companies: dict) -> RawJob:
        a = j.get("attributes") or {}
        company_ref = ((a.get("company") or {}).get("data") or {})
        company = companies.get(company_ref.get("id"), {}).get("name") or ((a.get("company") or {}).get("data") or {}).get("attributes", {}).get("name", "")
        seniority = _GOB_SENIORITY.get(((a.get("seniority") or {}).get("data") or {}).get("id"), "")
        sections = [a.get("description"), a.get("functions"), a.get("desirable"), a.get("benefits")]
        remote = bool(a.get("remote")) or a.get("remote_modality") == "fully_remote"
        return RawJob(
            source_job_id=j["id"],
            title=a.get("title", ""),
            company=company or "",
            url=(j.get("links") or {}).get("public_url") or f"https://www.getonbrd.com/jobs/{j['id']}",
            description="\n".join(filter(None, sections)) + (f"<p>Seniority: {seniority}</p>" if seniority else ""),
            location=", ".join(a.get("countries") or []) or ("Remote" if remote else ""),
            remote=remote or None,
            posted_at=parse_dt(a.get("published_at")),
            salary_min=a.get("min_salary"), salary_max=a.get("max_salary"),
            salary_currency="USD" if a.get("min_salary") else None, salary_period="month" if a.get("min_salary") else None,
        )


class HabrCareer(BoardSource):
    name = "habr"

    def __init__(self):
        super().__init__("ru", "Habr Career")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        cards: dict[str, dict] = {}
        for term in ("machine learning", "data scientist", "ML engineer", "AI engineer", "computer vision", "NLP"):
            for page in (1, 2):
                try:
                    data = await http.get_json(f"https://career.habr.com/api/frontend/vacancies?q={quote(term)}&page={page}")
                except Exception:
                    break
                for v in data.get("list", []):
                    cards.setdefault(str(v["id"]), v)
                if page >= (data.get("meta") or {}).get("totalPages", 1):
                    break
        out.seen_ids = set(cards)

        async def detail(jid: str, v: dict) -> RawJob | None:
            url = f"https://career.habr.com/vacancies/{jid}"
            if skipped := self.known(jid, v.get("title", ""), url, (v.get("company") or {}).get("title")):
                return skipped
            try:
                ld = jsonld_jobposting(await http.get_text(url)) or {}
            except Exception:
                ld = {}
            return self.to_raw(v, ld)

        wanted = [(jid, v) for jid, v in cards.items()
                  if v.get("qualification") not in ("Senior", "Lead") and not v.get("archived") and title_candidate(v.get("title", ""))]
        out.jobs = [r for r in await asyncio.gather(*(detail(j, v) for j, v in wanted)) if r]
        return out

    @staticmethod
    def to_raw(v: dict, ld: dict) -> RawJob:
        jid = str(v["id"])
        sal = v.get("salary") or {}
        skills = ", ".join(s.get("title", "") for s in v.get("skills") or [])
        locs = [loc.get("title", "") for loc in v.get("locations") or []]
        desc = ld.get("description") or ""
        if skills:
            desc += f"<p>Skills: {skills}</p>"
        if v.get("qualification"):
            desc += f"<p>Level: {v['qualification']}</p>"
        return RawJob(
            source_job_id=jid,
            title=v.get("title", ""),
            company=(v.get("company") or {}).get("title", ""),
            url=f"https://career.habr.com/vacancies/{jid}",
            description=desc,
            location=" / ".join(filter(None, locs)) or ("Remote" if v.get("remoteWork") else "Russia"),
            remote=bool(v.get("remoteWork")) or None,
            posted_at=parse_dt((v.get("publishedDate") or {}).get("date") or ld.get("datePosted")),
            employment_type=v.get("employment"),
            salary_min=sal.get("from"), salary_max=sal.get("to"),
            salary_currency="RUB" if (sal.get("currency") or "").lower() in ("rur", "rub") else (sal.get("currency") or "").upper() or None,
            salary_period="month" if sal.get("from") or sal.get("to") else None,
        )


class WorkingNomads(BoardSource):
    name = "workingnomads"

    def __init__(self):
        super().__init__("remote", "Working Nomads")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        for j in await http.get_json("https://www.workingnomads.com/api/exposed_jobs/"):
            jid = j.get("url", "")
            if not jid or jid in out.seen_ids:
                continue
            out.seen_ids.add(jid)
            out.jobs.append(RawJob(
                source_job_id=jid, title=j.get("title", ""), company=j.get("company_name", ""), url=jid,
                description=j.get("description", "") + (f"<p>Tags: {j['tags']}</p>" if j.get("tags") else ""),
                location=j.get("location") or "Remote", remote=True, posted_at=parse_dt(j.get("pub_date")),
            ))
        return out


REGIONAL_SOURCES = [MyCareersFuture, GetOnBoard, HabrCareer, WorkingNomads]

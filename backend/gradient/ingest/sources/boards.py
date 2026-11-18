"""Public job boards with open APIs, and Hacker News 'Who is hiring?'."""

import re

from ...domain.normalize import html_to_text, parse_dt
from ..base import FetchResult, Http, RawJob, Source


class BoardSource(Source):
    kind = "board"
    priority = 40


class Remotive(BoardSource):
    name = "remotive"
    min_interval_hours = 12  # Remotive asks API users to keep to a few calls a day

    def __init__(self):
        super().__init__("remote", "Remotive")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        for params in ({"category": "data"}, {"search": "machine learning"}):
            data = await http.get_json("https://remotive.com/api/remote-jobs", params=params)
            for j in data.get("jobs", []):
                jid = str(j["id"])
                if jid in out.seen_ids:
                    continue
                out.seen_ids.add(jid)
                out.jobs.append(RawJob(
                    source_job_id=jid, title=j.get("title", ""), company=j.get("company_name", ""),
                    url=j.get("url", ""), description=j.get("description", ""),
                    location=j.get("candidate_required_location", ""), remote=True,
                    posted_at=parse_dt(j.get("publication_date")), employment_type=j.get("job_type"),
                    salary_text=j.get("salary") or "",
                ))
        return out


class RemoteOK(BoardSource):
    name = "remoteok"

    def __init__(self):
        super().__init__("remote", "RemoteOK")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        for tag in ("machine-learning", "ai", "data-science"):
            data = await http.get_json(f"https://remoteok.com/api?tag={tag}")
            for j in data[1:] if isinstance(data, list) else []:  # item 0 is the legal notice
                jid = str(j.get("id"))
                if jid in out.seen_ids:
                    continue
                out.seen_ids.add(jid)
                out.jobs.append(RawJob(
                    source_job_id=jid, title=j.get("position", ""), company=j.get("company", ""),
                    url=j.get("url", ""), description=j.get("description", ""),
                    location=j.get("location") or "Remote", remote=True,
                    posted_at=parse_dt(j.get("epoch") or j.get("date")),
                    salary_min=j.get("salary_min") or None, salary_max=j.get("salary_max") or None,
                    salary_currency="USD" if j.get("salary_min") else None, salary_period="year" if j.get("salary_min") else None,
                ))
        return out


class Arbeitnow(BoardSource):
    name = "arbeitnow"

    def __init__(self):
        super().__init__("eu", "Arbeitnow")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        for page in range(1, 6):
            data = await http.get_json("https://www.arbeitnow.com/api/job-board-api", params={"page": page})
            for j in data.get("data", []):
                out.seen_ids.add(j["slug"])
                out.jobs.append(RawJob(
                    source_job_id=j["slug"], title=j.get("title", ""), company=j.get("company_name", ""),
                    url=j.get("url", ""), description=j.get("description", ""), location=j.get("location", ""),
                    remote=bool(j.get("remote")) or None, posted_at=parse_dt(j.get("created_at")),
                    employment_type=", ".join(j.get("job_types") or []) or None,
                ))
            if not data.get("links", {}).get("next"):
                break
        return out


class Himalayas(BoardSource):
    name = "himalayas"

    def __init__(self):
        super().__init__("remote", "Himalayas")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        for q in ("machine learning", "data scientist", "AI engineer"):
            data = await http.get_json("https://himalayas.app/jobs/api/search", params={"q": q, "limit": 20})
            for j in data.get("jobs", []):
                jid = j.get("guid") or j.get("applicationLink")
                if not jid or jid in out.seen_ids:
                    continue
                out.seen_ids.add(jid)
                period = j.get("salaryPeriod")
                out.jobs.append(RawJob(
                    source_job_id=jid, title=j.get("title", ""), company=j.get("companyName", ""),
                    url=j.get("applicationLink") or jid, description=j.get("description", ""),
                    location=", ".join(j.get("locationRestrictions") or []) or "Remote", remote=True,
                    posted_at=parse_dt(j.get("pubDate")), deadline_at=parse_dt(j.get("expiryDate")),
                    employment_type=j.get("employmentType"),
                    salary_min=j.get("minSalary"), salary_max=j.get("maxSalary"), salary_currency=j.get("currency"),
                    salary_period="year" if period == "annual" else period,
                ))
        return out


class Jobicy(BoardSource):
    name = "jobicy"

    def __init__(self):
        super().__init__("remote", "Jobicy")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        for tag in ("machine-learning", "data-science", "ai", "python"):
            try:
                data = await http.get_json("https://jobicy.com/api/v2/remote-jobs", params={"count": 50, "tag": tag})
            except Exception:
                continue  # Jobicy rejects tags it doesn't know with HTTP 400
            for j in data.get("jobs", []):
                jid = str(j["id"])
                if jid in out.seen_ids:
                    continue
                out.seen_ids.add(jid)
                out.jobs.append(RawJob(
                    source_job_id=jid, title=html_to_text(j.get("jobTitle", "")), company=j.get("companyName", ""),
                    url=j.get("url", ""), description=j.get("jobDescription", ""), location=j.get("jobGeo") or "Remote",
                    remote=True, posted_at=parse_dt(j.get("pubDate")),
                    employment_type=", ".join(j.get("jobType") or []) or None,
                    salary_min=j.get("salaryMin") or j.get("annualSalaryMin"), salary_max=j.get("salaryMax") or j.get("annualSalaryMax"),
                    salary_currency=j.get("salaryCurrency"), salary_period="year" if j.get("annualSalaryMin") else None,
                ))
        return out


_HN_ROLE = re.compile(
    r"(machine learning|ml|ai|data scien|applied scien|research (engineer|scientist)|llm|nlp|computer vision|mlops|deep learning|data engineer|data analyst)",
    re.I,
)


class HackerNewsHiring(Source):
    """Monthly 'Ask HN: Who is hiring?' thread; each top-level comment is one employer post."""

    name = "hn"
    kind = "community"
    priority = 45

    def __init__(self):
        super().__init__("whoishiring", "Hacker News")

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        stories = await http.get_json(
            "https://hn.algolia.com/api/v1/search_by_date", params={"tags": "story,author_whoishiring", "hitsPerPage": 6}
        )
        thread = next((h for h in stories.get("hits", []) if "who is hiring" in h.get("title", "").lower()), None)
        if not thread:
            return out
        item = await http.get_json(f"https://hn.algolia.com/api/v1/items/{thread['objectID']}")
        for c in item.get("children", []):
            text = html_to_text(c.get("text") or "")
            if not text or not _HN_ROLE.search(text[:400]):
                continue
            first = text.split("\n", 1)[0]
            parts = [p.strip() for p in re.split(r"\s[|•·]\s|\s[-–]\s", first) if p.strip()]
            if len(parts) < 2:
                continue
            company = re.sub(r"\(.*?\)", "", parts[0]).strip()[:120]
            role = next((p for p in parts[1:] if _HN_ROLE.search(p)), None)
            if not role:
                continue
            # "Junior SWE ($300k…), Research Engineer (…)" -> keep the first AI/ML role only
            pieces = [x.strip() for x in re.split(r",\s*(?![^()]*\))|\s/\s|;", role) if x.strip()]
            role = re.sub(r"\s*\(.*?\)", "", next((x for x in pieces if _HN_ROLE.search(x)), pieces[0])).strip() or role
            location = next((p for p in parts[1:] if re.search(r"remote|onsite|hybrid|,|\b[A-Z]{2}\b|india|london|york|francisco", p, re.I) and p != role), "")
            cid = str(c["id"])
            out.seen_ids.add(cid)
            out.jobs.append(RawJob(
                source_job_id=cid, title=role[:200], company=company, url=f"https://news.ycombinator.com/item?id={cid}",
                description=text, location=location, remote=("remote" in first.lower()) or None,
                posted_at=parse_dt(c.get("created_at")), salary_text=first,
            ))
        return out


# The Muse was dropped in Nov 2026: its public API now answers 404 for every request.
BOARD_SOURCES = [Remotive, RemoteOK, Arbeitnow, Himalayas, Jobicy, HackerNewsHiring]

"""SimplifyJobs community-maintained new-grad and internship listings (GitHub). Thousands of
early-career roles with direct employer ATS links and an `active` flag, so the listing is
authoritative: a role flipped to inactive or removed is closed."""

from ...domain.normalize import parse_dt
from ..base import FetchResult, Http, RawJob, Source

REPOS = {
    "newgrad": "https://raw.githubusercontent.com/SimplifyJobs/New-Grad-Positions/dev/.github/scripts/listings.json",
    "internships": "https://raw.githubusercontent.com/SimplifyJobs/Summer2026-Internships/dev/.github/scripts/listings.json",
}


class Simplify(Source):
    name = "simplify"
    kind = "board"
    authoritative = True
    priority = 55

    def __init__(self, repo: str):
        super().__init__(repo, "Simplify")
        self.repo = repo

    async def fetch(self, http: Http) -> FetchResult:
        data = await http.get_json(REPOS[self.repo], timeout=90)
        out = FetchResult()
        for j in data:
            if not j.get("active") or not j.get("is_visible", True):
                continue
            jid = j["id"]
            out.seen_ids.add(jid)
            terms = ", ".join(j.get("terms") or [])
            title = j.get("title", "")
            if self.repo == "internships" and "intern" not in title.lower():
                title = f"{title} Intern"
            out.jobs.append(RawJob(
                source_job_id=jid,
                title=title,
                company=j.get("company_name", ""),
                url=j.get("url", ""),
                description=f"{j.get('category', '')} role. {('Terms: ' + terms + '. ') if terms else ''}"
                            f"Degrees: {', '.join(j.get('degrees') or [])}. Sponsorship: {j.get('sponsorship', 'n/a')}.",
                location=" / ".join(j.get("locations") or []),
                posted_at=parse_dt(j.get("date_posted")),
                employment_type="Internship" if self.repo == "internships" else "Full-time",
            ))
        return out

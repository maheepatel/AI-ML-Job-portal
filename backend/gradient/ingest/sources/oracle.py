"""Oracle Recruiting Cloud (Candidate Experience) career sites: JPMorgan, EXL, many banks,
telcos and manufacturers. The public REST API behind the site needs no login. Searched by
keyword, so it is not authoritative (like Workday): closures come from liveness checks."""

import asyncio
from urllib.parse import quote

from ...domain.classify import title_candidate
from ...domain.normalize import parse_dt
from ..base import FetchResult, Http, RawJob, Source

TERMS = ["machine learning", "data scientist", "artificial intelligence"]
_LIST = ("{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitions?onlyData=true"
         "&expand=requisitionList.secondaryLocations"
         "&finder=findReqs;siteNumber={site},keyword=%22{kw}%22,limit=50,offset={offset},sortBy=POSTING_DATES_DESC")
_DETAIL = ("{base}/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails?expand=all&onlyData=true"
           "&finder=ById;Id=%22{id}%22,siteNumber={site}")


class OracleHCM(Source):
    """Board ident: "{host}|{siteNumber}", e.g. "jpmc.fa.oraclecloud.com|CX_1001"."""

    name = "oracle"
    kind = "bigtech"
    priority = 85

    def __init__(self, host: str, site: str, company: str | None = None, terms: list[str] | None = None):
        super().__init__(f"{host.split('.')[0]}-{site}", company or host.split(".")[0].upper(), None)
        self.base = f"https://{host}"
        self.site = site
        self.terms = terms or TERMS

    def job_url(self, jid: str) -> str:
        return f"{self.base}/hcmUI/CandidateExperience/en/sites/{self.site}/job/{jid}"

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        reqs: dict[str, dict] = {}
        for term in self.terms:
            for offset in (0, 50):
                data = await http.get_json(_LIST.format(base=self.base, site=self.site, kw=quote(term), offset=offset),
                                           headers={"Accept": "application/json"})
                block = (data.get("items") or [{}])[0]
                items = block.get("requisitionList") or []
                for r in items:
                    reqs.setdefault(str(r["Id"]), r)
                if len(items) < 50 or offset + 50 >= (block.get("TotalJobsCount") or 0):
                    break
        out.seen_ids = set(reqs)

        async def detail(jid: str, r: dict) -> RawJob | None:
            if skipped := self.known(jid, r.get("Title", ""), self.job_url(jid)):
                return skipped
            try:
                d = ((await http.get_json(_DETAIL.format(base=self.base, site=self.site, id=jid),
                                          headers={"Accept": "application/json"})).get("items") or [{}])[0]
            except Exception:
                d = {}
            return self.to_raw(jid, r, d)

        wanted = [(jid, r) for jid, r in reqs.items() if title_candidate(r.get("Title", ""))]
        out.jobs = [x for x in await asyncio.gather(*(detail(j, r) for j, r in wanted)) if x]
        return out

    def to_raw(self, jid: str, r: dict, d: dict) -> RawJob:
        locs = [r.get("PrimaryLocation") or d.get("PrimaryLocation") or ""]
        locs += [s.get("Name", "") for s in r.get("secondaryLocations") or [] if isinstance(s, dict)]
        desc = "\n".join(filter(None, [d.get("ExternalDescriptionStr"), d.get("ExternalResponsibilitiesStr"),
                                       d.get("ExternalQualificationsStr")])) or r.get("ShortDescriptionStr", "")
        return RawJob(
            source_job_id=jid,
            title=d.get("Title") or r.get("Title", ""),
            company=self.company,
            url=self.job_url(jid),
            description=desc,
            location=" / ".join(dict.fromkeys(filter(None, locs))),
            remote=("remote" in str(r.get("WorkplaceType") or d.get("WorkplaceType") or "").lower()) or None,
            posted_at=parse_dt(d.get("ExternalPostedStartDate") or r.get("PostedDate")),
            deadline_at=parse_dt(d.get("ExternalPostedEndDate") or r.get("PostingEndDate")),
            employment_type=d.get("JobSchedule"),
        )

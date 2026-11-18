"""More employer ATSes with public, no-login feeds: Personio (EU), Teamtailor (Nordics/EU),
BambooHR and Breezy (SMBs), JazzHR (US) and Rippling (US startups). Each board is the
employer's complete listing, so these are authoritative like the core ATS sources."""

import asyncio
import re
import xml.etree.ElementTree as ET

from scrapling.parser import Selector

from ...domain.classify import title_candidate
from ...domain.normalize import parse_dt
from ..base import FetchResult, Http, RawJob, SourceError
from ._html import jsonld_jobposting, jsonld_location
from .ats import AtsSource

DETAIL_CAP = 150
_TT_NS = {"tt": "https://teamtailor.com/locations"}  # detail requests per board per run; known jobs never cost one


def _text(el, path: str) -> str:
    node = el.find(path, _TT_NS)
    return (node.text or "").strip() if node is not None and node.text else ""


async def _gather_details(coros) -> list[RawJob]:
    return [r for r in await asyncio.gather(*coros) if r]


class Personio(AtsSource):
    """https://{slug}.jobs.personio.de/xml (also served from .jobs.personio.com)."""

    name = "personio"

    async def fetch(self, http: Http) -> FetchResult:
        last: Exception | None = None
        for tld in ("de", "com"):
            try:
                return self.parse(await http.get_text(f"https://{self.slug}.jobs.personio.{tld}/xml?language=en"), tld)
            except SourceError as exc:
                last = exc
        raise last or SourceError("personio feed unavailable")

    def parse(self, xml: str, tld: str = "de") -> FetchResult:
        out = FetchResult()
        root = ET.fromstring(xml.encode("utf-8"))
        for pos in root.iter("position"):
            jid = _text(pos, "id")
            if not jid:
                continue
            out.seen_ids.add(jid)
            parts = []
            for d in pos.iter("jobDescription"):
                parts.append(f"<h3>{_text(d, 'name')}</h3>{_text(d, 'value')}")
            years = _text(pos, "yearsOfExperience")
            if years:
                parts.append(f"<p>Experience: {years.replace('-', ' to ')} years</p>")
            offices = [_text(pos, "office")] + [(o.text or "").strip() for o in pos.findall("additionalOffices/office")]
            out.jobs.append(RawJob(
                source_job_id=jid,
                title=_text(pos, "name"),
                company=_text(pos, "subcompany") or self.company,
                url=f"https://{self.slug}.jobs.personio.{tld}/job/{jid}",
                description="\n".join(parts),
                location=" / ".join(dict.fromkeys(filter(None, offices))),
                posted_at=parse_dt(_text(pos, "createdAt")),
                employment_type=_text(pos, "schedule") or _text(pos, "employmentType") or None,
                company_domain=self.domain,
            ))
        return out


_TT_ID = re.compile(r"/jobs/(\d+)")


class Teamtailor(AtsSource):
    """https://{slug}.teamtailor.com/jobs.rss — full descriptions in one request."""

    name = "teamtailor"

    async def fetch(self, http: Http) -> FetchResult:
        host = self.slug if "." in self.slug else f"{self.slug}.teamtailor.com"
        return self.parse(await http.get_text(f"https://{host}/jobs.rss"))

    def parse(self, xml: str) -> FetchResult:
        out = FetchResult()
        channel = ET.fromstring(xml.encode("utf-8")).find("channel")
        for item in channel.iter("item") if channel is not None else []:
            link = _text(item, "link")
            m = _TT_ID.search(link)
            jid = m.group(1) if m else _text(item, "guid")
            if not jid:
                continue
            out.seen_ids.add(jid)
            locs = [_text(loc, "tt:name") or ", ".join(filter(None, [_text(loc, "tt:city"), _text(loc, "tt:country")]))
                    for loc in item.findall("tt:locations/tt:location", _TT_NS)]
            remote = _text(item, "remoteStatus").lower()
            out.jobs.append(RawJob(
                source_job_id=jid,
                title=_text(item, "title"),
                company=_text(item, "company_name") or self.company,
                url=link,
                description=_text(item, "description"),
                location=" / ".join(filter(None, locs)) or ("Remote" if remote == "fully" else ""),
                remote=True if remote == "fully" else None,
                posted_at=parse_dt(_text(item, "pubDate")),
                company_domain=self.domain,
            ))
        return out


class BambooHR(AtsSource):
    """https://{slug}.bamboohr.com/careers/list (+ /careers/{id}/detail for AI/ML titles)."""

    name = "bamboohr"

    async def fetch(self, http: Http) -> FetchResult:
        base = f"https://{self.slug}.bamboohr.com/careers"
        data = await http.get_json(f"{base}/list")
        out = FetchResult()
        wanted = []
        for j in data.get("result") or []:
            jid = str(j.get("id"))
            out.seen_ids.add(jid)
            if title_candidate(j.get("jobOpeningName", "")):
                wanted.append(j)

        async def detail(j: dict) -> RawJob | None:
            jid, title = str(j["id"]), j.get("jobOpeningName", "")
            if skipped := self.known(jid, title, f"{base}/{jid}"):
                return skipped
            try:
                d = (await http.get_json(f"{base}/{jid}/detail")).get("result", {}).get("jobOpening", {})
            except Exception:
                d = {}
            return self.to_raw(j, d)

        out.jobs = await _gather_details(detail(j) for j in wanted[:DETAIL_CAP])
        return out

    def to_raw(self, j: dict, d: dict) -> RawJob:
        jid = str(j["id"])
        loc = d.get("location") or j.get("location") or {}
        ats = d.get("atsLocation") or j.get("atsLocation") or {}
        place = ", ".join(filter(None, [loc.get("city") or ats.get("city"), loc.get("state") or ats.get("state"),
                                        loc.get("addressCountry") or ats.get("country")]))
        remote = bool(j.get("isRemote") or d.get("isRemote")) or str(d.get("locationType") or j.get("locationType")) == "1"
        desc = d.get("description") or ""
        if d.get("minimumExperience"):
            desc += f"\n<p>Experience level: {d['minimumExperience']}</p>"
        return RawJob(
            source_job_id=jid,
            title=d.get("jobOpeningName") or j.get("jobOpeningName", ""),
            company=self.company,
            url=d.get("jobOpeningShareUrl") or f"https://{self.slug}.bamboohr.com/careers/{jid}",
            description=desc,
            location=place or ("Remote" if remote else ""),
            remote=remote or None,
            posted_at=parse_dt(d.get("datePosted")),
            employment_type=d.get("employmentStatusLabel") or j.get("employmentStatusLabel"),
            salary_text=d.get("compensation") or "",
            company_domain=self.domain,
        )


class Breezy(AtsSource):
    """https://{slug}.breezy.hr/json (+ the posting page's JSON-LD for AI/ML titles)."""

    name = "breezy"

    async def fetch(self, http: Http) -> FetchResult:
        listing = await http.get_json(f"https://{self.slug}.breezy.hr/json")
        out = FetchResult()
        wanted = []
        for j in listing if isinstance(listing, list) else []:
            out.seen_ids.add(j["id"])
            if title_candidate(j.get("name", "")):
                wanted.append(j)

        async def detail(j: dict) -> RawJob | None:
            if skipped := self.known(j["id"], j.get("name", ""), j.get("url", "")):
                return skipped
            try:
                posting = jsonld_jobposting(await http.get_text(j["url"])) or {}
            except Exception:
                posting = {}
            return self.to_raw(j, posting)

        out.jobs = await _gather_details(detail(j) for j in wanted[:DETAIL_CAP])
        return out

    def to_raw(self, j: dict, posting: dict) -> RawJob:
        loc = j.get("location") or {}
        locs = [x.get("name", "") for x in j.get("locations") or []] or [loc.get("name", "")]
        return RawJob(
            source_job_id=j["id"],
            title=j.get("name", ""),
            company=(j.get("company") or {}).get("name") or self.company,
            url=j.get("url", ""),
            description=posting.get("description", ""),
            location=" / ".join(filter(None, locs)),
            remote=bool(loc.get("is_remote")) or None,
            posted_at=parse_dt(j.get("published_date")),
            employment_type=(j.get("type") or {}).get("name"),
            salary_text=j.get("salary") or "",
            company_domain=self.domain,
        )


class JazzHR(AtsSource):
    """https://{slug}.applytojob.com/apply — server-rendered list, description on each job page."""

    name = "jazzhr"

    async def fetch(self, http: Http) -> FetchResult:
        out = FetchResult()
        cards = self.parse_list(await http.get_text(f"https://{self.slug}.applytojob.com/apply"))
        out.seen_ids = {c["id"] for c in cards}

        async def detail(c: dict) -> RawJob | None:
            if skipped := self.known(c["id"], c["title"], c["url"]):
                return skipped
            try:
                page = Selector(await http.get_text(c["url"]))
                el = page.css("#job-description").first
                desc = el.html_content if el is not None else ""
            except Exception:
                desc = ""
            return RawJob(source_job_id=c["id"], title=c["title"], company=self.company, url=c["url"],
                          description=desc, location=c["location"], remote=("remote" in c["location"].lower()) or None,
                          company_domain=self.domain)

        out.jobs = await _gather_details(detail(c) for c in cards if title_candidate(c["title"]))
        return out

    def parse_list(self, page: str) -> list[dict]:
        cards = []
        for li in Selector(page).css("li.list-group-item"):
            a = li.css("h3.list-group-item-heading a").first or li.css("a").first
            if a is None:
                continue
            url = a.attrib.get("href", "")
            m = re.search(r"/apply/([A-Za-z0-9]+)/", url)
            if not m:
                continue
            marker = li.css("ul.list-group-item-text li").first
            cards.append({"id": m.group(1), "url": url, "title": " ".join(a.get_all_text().split()),
                          "location": " ".join(marker.get_all_text().split()) if marker is not None else ""})
        return cards


class Rippling(AtsSource):
    """https://ats.rippling.com/{slug}/jobs via the public board API used by the page itself."""

    name = "rippling"
    API = "https://api.rippling.com/platform/api/ats/v1/board/{slug}/jobs"

    async def fetch(self, http: Http) -> FetchResult:
        api = self.API.format(slug=self.slug)
        listing = await http.get_json(api)
        out = FetchResult()
        wanted = []
        for j in listing if isinstance(listing, list) else []:
            out.seen_ids.add(j["uuid"])
            if title_candidate(j.get("name", "")):
                wanted.append(j)

        async def detail(j: dict) -> RawJob | None:
            if skipped := self.known(j["uuid"], j.get("name", ""), j.get("url", "")):
                return skipped
            try:
                d = await http.get_json(f"{api}/{j['uuid']}")
            except Exception:
                d = {}
            return self.to_raw(j, d)

        out.jobs = await _gather_details(detail(j) for j in wanted[:DETAIL_CAP])
        return out

    def to_raw(self, j: dict, d: dict) -> RawJob:
        desc = d.get("description") or {}
        text = "\n".join(desc.values()) if isinstance(desc, dict) else str(desc)
        locs = d.get("workLocations") or [(j.get("workLocation") or {}).get("label", "")]
        pay = (d.get("payRangeDetails") or [{}])[0] if d.get("payRangeDetails") else {}
        return RawJob(
            source_job_id=j["uuid"],
            title=d.get("name") or j.get("name", ""),
            company=d.get("companyName") or self.company,
            url=d.get("url") or j.get("url", ""),
            description=text,
            location=" / ".join(filter(None, locs)),
            remote=any("remote" in str(x).lower() for x in locs) or None,
            posted_at=parse_dt(d.get("createdOn")),
            employment_type=(d.get("employmentType") or {}).get("id"),
            salary_min=pay.get("rangeStart"), salary_max=pay.get("rangeEnd"), salary_currency=pay.get("currency"),
            salary_period="year" if pay else None,
            company_domain=self.domain,
        )


EXTRA_ATS: dict[str, type[AtsSource]] = {cls.name: cls for cls in (Personio, Teamtailor, BambooHR, Breezy, JazzHR, Rippling)}

__all__ = ["EXTRA_ATS", "jsonld_location"]

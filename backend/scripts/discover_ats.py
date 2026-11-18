"""Find which ATS a company uses by probing every supported board API for each slug.

    python scripts/discover_ats.py anthropic celonis razorpay ...
    python scripts/discover_ats.py --file scripts/candidates.txt --merge

Prints YAML entries; --merge appends new ones to data/companies.yaml.
"""

import argparse
import asyncio
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gradient.config import settings  # noqa: E402
from gradient.ingest.base import Http  # noqa: E402

PROBES = {
    "greenhouse": ("https://boards-api.greenhouse.io/v1/boards/{s}/jobs", lambda j: len(j.get("jobs", []))),
    "lever": ("https://api.lever.co/v0/postings/{s}?mode=json", lambda j: len(j) if isinstance(j, list) else 0),
    "ashby": ("https://api.ashbyhq.com/posting-api/job-board/{s}", lambda j: len(j.get("jobs", []))),
    "workable": ("https://apply.workable.com/api/v1/widget/accounts/{s}", lambda j: len(j.get("jobs", []))),
    "recruitee": ("https://{s}.recruitee.com/api/offers/", lambda j: len(j.get("offers", []))),
    "smartrecruiters": ("https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1", lambda j: j.get("totalFound", 0)),
    "personio": ("https://{s}.jobs.personio.de/xml", lambda t: t.count("<position>")),
    "teamtailor": ("https://{s}.teamtailor.com/jobs.rss", lambda t: t.count("<item>")),
    "bamboohr": ("https://{s}.bamboohr.com/careers/list", lambda j: len(j.get("result") or [])),
    "breezy": ("https://{s}.breezy.hr/json", lambda j: len(j) if isinstance(j, list) else 0),
    "rippling": ("https://api.rippling.com/platform/api/ats/v1/board/{s}/jobs", lambda j: len(j) if isinstance(j, list) else 0),
}
TEXT_FEEDS = {"personio", "teamtailor"}


async def probe(http: Http, slug: str, only: set[str] | None = None) -> list[dict]:
    async def one(ats: str):
        url, count = PROBES[ats]
        try:
            resp = await http.get(url.format(s=slug), attempts=1, timeout=15)
            if resp.status != 200:
                return None
            if ats in TEXT_FEEDS:
                body = resp.body.decode("utf-8", "replace") if isinstance(resp.body, bytes) else str(resp.body)
                n = count(body) if body.lstrip().startswith("<?xml") or "<rss" in body[:200] else 0
            else:
                n = count(resp.json())
            return {"ats": ats, "slug": slug, "jobs": n} if n else None
        except Exception:
            return None

    found = await asyncio.gather(*(one(a) for a in PROBES if not only or a in only))
    return [f for f in found if f]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--file")
    ap.add_argument("--merge", action="store_true")
    args = ap.parse_args()

    slugs = list(args.slugs)
    if args.file:
        for line in Path(args.file).read_text().splitlines():
            if not line.lstrip().startswith("#"):
                slugs += line.split()
    slugs = list(dict.fromkeys(slugs))

    http = Http(max_concurrency=48, per_host=8)
    results = await asyncio.gather(*(probe(http, s) for s in slugs))
    hits = [h for group in results for h in group]
    misses = [s for s, group in zip(slugs, results) if not group]

    for h in sorted(hits, key=lambda x: -x["jobs"]):
        print(f"  {h['ats']:16} {h['slug']:28} {h['jobs']} jobs")
    print(f"\n{len(hits)} boards found, {len(misses)} slugs with no board: {' '.join(misses)}", file=sys.stderr)

    if args.merge:
        path = settings.companies_file
        path.parent.mkdir(parents=True, exist_ok=True)
        data = yaml.safe_load(path.read_text()) if path.exists() else {}
        data = data or {}
        for h in hits:
            entries = data.setdefault(h["ats"], [])
            if not any((e if isinstance(e, str) else e.get("slug")) == h["slug"] for e in entries):
                entries.append(h["slug"])
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        print(f"merged into {path}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())

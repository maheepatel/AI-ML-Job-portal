"""Bulk-grow the boards table from public company datasets.

    python scripts/expand_registry.py            # YC hiring + AI-tagged companies
    python scripts/expand_registry.py --limit 300

For each company, slug variants (yc slug, dashless slug, website domain stem) are probed
against every supported ATS; boards that answer with jobs are registered (origin='yc').
Day-to-day growth needs no script: every run auto-registers boards seen in apply links.
"""

import argparse
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from discover_ats import probe  # noqa: E402
from gradient.db import init_db, session_scope  # noqa: E402
from gradient.ingest.base import Http  # noqa: E402
from gradient.ingest.registry import add_boards  # noqa: E402

DATASETS = [
    "https://yc-oss.github.io/api/companies/hiring.json",
    "https://yc-oss.github.io/api/tags/artificial-intelligence.json",
    "https://yc-oss.github.io/api/tags/generative-ai.json",
    "https://yc-oss.github.io/api/tags/machine-learning.json",
]


def variants(company: dict) -> set[str]:
    out = set()
    slug = (company.get("slug") or "").lower()
    if slug:
        out |= {slug, slug.replace("-", "")}
    host = (urlparse(company.get("website") or "").hostname or "").removeprefix("www.")
    if host:
        stem = host.split(".")[0]
        if len(stem) > 2:
            out.add(stem)
    return {v for v in out if re.fullmatch(r"[a-z0-9-]{2,60}", v)}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    init_db()
    http = Http(max_concurrency=64, per_host=12)
    companies: dict[str, dict] = {}
    for url in DATASETS:
        try:
            for c in await http.get_json(url, timeout=60):
                companies.setdefault(c.get("slug") or c.get("name"), c)
        except Exception as exc:
            print(f"skip {url}: {exc}", file=sys.stderr)
    items = list(companies.values())[: args.limit or None]
    print(f"{len(items)} companies to probe", file=sys.stderr)

    found: dict[tuple[str, str], str] = {}
    sem = asyncio.Semaphore(40)

    async def one(c: dict):
        async with sem:
            for slug in variants(c):
                for hit in await probe(http, slug):
                    found.setdefault((hit["ats"], hit["slug"]), c.get("name"))

    await asyncio.gather(*(one(c) for c in items))
    with session_scope() as s:
        added = add_boards(s, set(found), "yc", found)
    print(f"{len(found)} boards found, {added} new boards registered", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())

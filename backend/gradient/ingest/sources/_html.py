"""Small helpers for career pages that embed their data: JSON-LD JobPosting and Inertia data-page."""

import html as _html
import json
import re

_LD = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S | re.I)
_DATA_PAGE = re.compile(r'data-page="([^"]+)"')


def jsonld_jobposting(page: str) -> dict | None:
    """First schema.org JobPosting embedded in a page, or None."""
    for block in _LD.findall(page or ""):
        try:
            data = json.loads(block.strip())
        except ValueError:
            continue
        for item in data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                return item
    return None


def jsonld_location(posting: dict) -> str:
    locs = posting.get("jobLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    out = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            out.append(addr)
            continue
        country = addr.get("addressCountry")
        if isinstance(country, dict):
            country = country.get("name")
        out.append(", ".join(filter(None, [addr.get("addressLocality"), addr.get("addressRegion"), country])))
    return " / ".join(filter(None, out))


def inertia_props(page: str) -> dict:
    """Props of an Inertia.js page (ycombinator.com renders every page this way)."""
    m = _DATA_PAGE.search(page or "")
    if not m:
        return {}
    try:
        return json.loads(_html.unescape(m.group(1))).get("props") or {}
    except ValueError:
        return {}

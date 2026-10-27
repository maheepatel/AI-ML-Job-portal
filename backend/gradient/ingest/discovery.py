"""Recognise employer job boards from any URL, so every apply link we see can grow the registry."""

import re
from urllib.parse import parse_qs, urlparse

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"^(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_app\?for=)?([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"^jobs\.lever\.co/([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"^jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("workable", re.compile(r"^apply\.workable\.com/([A-Za-z0-9_-]+)")),
    ("smartrecruiters", re.compile(r"^(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
    ("recruitee", re.compile(r"^([a-z0-9-]+)\.recruitee\.com")),
]
_WORKDAY = re.compile(r"^([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")
_RESERVED = {"embed", "api", "v1", "jobs", "j", "o", "en-us", "careers", "search", "login", "wday"}


def board_from_url(url: str | None) -> tuple[str, str] | None:
    """'https://jobs.lever.co/zoox/123' -> ('lever', 'zoox'); workday -> ('workday', 'tenant|wd5|Site')."""
    if not url:
        return None
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    path = parsed.path or "/"
    target = f"{host}{path}"

    if host.endswith("greenhouse.io"):
        qs = parse_qs(parsed.query)
        if "for" in qs:
            return ("greenhouse", qs["for"][0].lower())
    m = _WORKDAY.match(target)
    if m:
        tenant, wd, site = m.groups()
        if site.lower() not in _RESERVED:
            return ("workday", f"{tenant}|{wd}|{site}")
        return None
    for ats, rx in _PATTERNS:
        m = rx.match(target)
        if m:
            slug = m.group(1)
            if slug.lower() in _RESERVED:
                return None
            return (ats, slug if ats in ("smartrecruiters", "ashby") else slug.lower())
    return None


def is_ats_url(url: str | None) -> bool:
    return board_from_url(url) is not None

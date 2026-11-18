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
    ("personio", re.compile(r"^([a-z0-9-]+)\.jobs\.personio\.(?:de|com)")),
    ("teamtailor", re.compile(r"^([a-z0-9-]+)\.teamtailor\.com")),
    ("bamboohr", re.compile(r"^([a-z0-9-]+)\.bamboohr\.com/(?:careers|jobs)")),
    ("breezy", re.compile(r"^([a-z0-9-]+)\.breezy\.hr")),
    ("jazzhr", re.compile(r"^([a-z0-9-]+)\.applytojob\.com")),
    ("rippling", re.compile(r"^ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
]
# Oracle Recruiting Cloud: https://{host}/hcmUI/CandidateExperience/{lang}/sites/{site}/...
_ORACLE = re.compile(r"^([a-z0-9-]+(?:\.[a-z0-9-]+)*\.oraclecloud\.com)/hcmUI/CandidateExperience/[a-z-]+/sites/([A-Za-z0-9_]+)", re.I)
_WORKDAY = re.compile(r"^([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")
_RESERVED = {"embed", "api", "v1", "jobs", "j", "o", "en-us", "careers", "search", "login", "wday", "www", "app", "help",
             "support", "status", "blog", "career", "apply"}
_CASE_KEPT = ("smartrecruiters", "ashby", "rippling")


def board_from_url(url: str | None) -> tuple[str, str] | None:
    """'https://jobs.lever.co/zoox/123' -> ('lever', 'zoox'); workday -> ('workday', 'tenant|wd5|Site');
    oracle -> ('oracle', 'host|CX_1')."""
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
    m = _ORACLE.match(target)
    if m:
        return ("oracle", f"{m.group(1).lower()}|{m.group(2)}")
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
            return (ats, slug if ats in _CASE_KEPT else slug.lower())
    return None


def is_ats_url(url: str | None) -> bool:
    return board_from_url(url) is not None

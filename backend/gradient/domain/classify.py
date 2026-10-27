"""AI/ML relevance, role family, seniority and experience extraction."""

import re
from dataclasses import dataclass

from .taxonomy import (
    PREFILTERED_SKILLS,
    DESC_SIGNALS,
    ENTRY_TITLE,
    INTERN_TITLE,
    MID_TITLE,
    Prefiltered,
    ROLE_FAMILIES,
    SENIOR_TITLE,
    TITLE_SIGNALS,
)

_TITLE_RX = [(re.compile(rx, re.I), w) for rx, w in TITLE_SIGNALS]
_DESC_RX = [Prefiltered(rx) for rx in DESC_SIGNALS]
_FAMILY_RX = [(name, re.compile(rx, re.I)) for name, rx in ROLE_FAMILIES]

# Roles that mention AI in the title but are not AI/ML practitioner jobs.
_NON_PRACTITIONER = re.compile(
    r"\b(sales|account (executive|manager)|recruit|talent|marketing|legal|counsel|finance|accountant|"
    r"customer success|support|office|executive assistant|hr\b|people partner|designer|writer|"
    r"tutor|annotator|rater|evaluator|trainer\b|content)\b",
    re.I,
)
# Engineering titles that qualify when the description is AI-heavy.
_ENGINEERING = re.compile(r"\b(engineer|developer|scientist|swe|programmer|analyst)\b", re.I)

_YEARS = re.compile(
    r"(?P<a>\d{1,2})(?:\.\d)?\s*(?:\+|plus)?\s*(?:(?:-|–|to)\s*(?P<b>\d{1,2})\s*\+?)?\s*(?:years?|yrs?)",
    re.I,
)
_EXP_CONTEXT = re.compile(r"experience|exp\b|industry|professional|working|hands-on|background", re.I)


@dataclass
class Classification:
    relevant: bool
    ai_score: float
    role_family: str
    seniority: str  # intern | entry | junior | mid | senior | unknown
    exp_min: float | None
    exp_max: float | None
    in_scope: bool
    skills: list[str]
    reject_reason: str | None = None


def ai_relevance(title: str, description: str) -> float:
    title_score = max((w for rx, w in _TITLE_RX if rx.search(title)), default=0.0)
    low = description.lower()
    hits = sum(1 for rx in _DESC_RX if rx.search(description, low))
    desc_score = min(hits / 6, 1.0)  # 6+ distinct AI concepts = fully AI-heavy description
    if title_score:
        return round(min(1.0, title_score * 0.8 + desc_score * 0.2 + (0.1 if hits >= 2 else 0)), 3)
    if _ENGINEERING.search(title) and hits >= 4:
        return round(0.4 + desc_score * 0.3, 3)  # "AI Product Engineering"
    return round(desc_score * 0.3, 3)


def role_family(title: str, ai_score: float) -> str:
    for name, rx in _FAMILY_RX:
        if name == "AI Product Engineering":
            return name
        if rx.search(title):
            return name
    return "AI Product Engineering"


def seniority(title: str) -> str:
    if INTERN_TITLE.search(title):
        return "intern"
    if SENIOR_TITLE.search(title):
        if re.search(r"\b(associate|junior|jr)\b", title, re.I) and not re.search(r"\b(director|principal|staff)\b", title, re.I):
            return "entry"  # "Associate Product Manager", "Junior Lead…"
        return "senior"
    if MID_TITLE.search(title):
        return "mid"
    if ENTRY_TITLE.search(title):
        return "entry"
    return "unknown"


def experience_years(description: str) -> tuple[float | None, float | None]:
    """Smallest stated experience requirement, e.g. '2-4 years of experience' → (2, 4)."""
    best: tuple[float, float | None] | None = None
    for m in _YEARS.finditer(description[:12000]):
        window = description[max(0, m.start() - 60): m.end() + 60]
        if not _EXP_CONTEXT.search(window):
            continue
        lo = float(m["a"])
        hi = float(m["b"]) if m["b"] else None
        if lo > 25 or (hi is not None and hi < lo):
            continue
        if best is None or lo < best[0]:
            best = (lo, hi)
    return best if best else (None, None)


def extract_skills(text: str) -> list[str]:
    low = text.lower()
    return [name for name, rx in PREFILTERED_SKILLS.items() if rx.search(text, low)]


def title_candidate(title: str) -> bool:
    """Cheap pre-filter for sources where descriptions cost one extra request per job."""
    if seniority(title) == "senior" or _NON_PRACTITIONER.search(title):
        return False
    return max((w for rx, w in _TITLE_RX if rx.search(title)), default=0.0) >= 0.45


def classify(title: str, description: str, max_years: int = 4) -> Classification:
    score = ai_relevance(title, description)
    if score < 0.4:  # most fetched jobs: bail out before the expensive skills/experience scans
        return Classification(False, score, "AI Product Engineering", "unknown", None, None, False, [], "not_ai_ml")
    level = seniority(title)
    exp_min, exp_max = experience_years(description)
    skills = extract_skills(f"{title}\n{description}")
    family = role_family(title, score)

    reject = None
    if score < 0.4:
        reject = "not_ai_ml"
    elif _NON_PRACTITIONER.search(title) and not re.search(r"engineer|scientist|developer", title, re.I):
        reject = "non_practitioner"
    elif level == "senior":
        reject = "senior_title"
    elif exp_min is not None and exp_min > max_years:
        reject = "too_much_experience"

    if level == "unknown" and exp_min is not None:
        level = "entry" if exp_min <= 1 else "junior" if exp_min <= 2 else "mid"

    return Classification(
        relevant=score >= 0.4,
        ai_score=score,
        role_family=family,
        seniority=level,
        exp_min=exp_min,
        exp_max=exp_max,
        in_scope=reject is None,
        skills=skills,
        reject_reason=reject,
    )

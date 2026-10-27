"""Explainable trust scoring: is this a genuine opening or a scam / ghost post?

Every signal adds or removes points and leaves a human-readable reason, so the UI can show
*why* a job is flagged. Base 50; clamp 0-100.

  >= 80 verified        posted on the employer's own ATS / career API
  60-79 likely_genuine
  35-59 caution
  <  35 likely_scam     hidden from listings by default
"""

import re
from dataclasses import dataclass
from urllib.parse import urlparse

from .normalize import norm_company

SOURCE_BASE = {
    "ats": (32, "Posted on the employer's own applicant tracking system"),
    "bigtech": (35, "Posted on the company's official careers API"),
    "linkedin": (8, "Listed on LinkedIn (company page)"),
    "community": (5, "Posted by the hiring team on Hacker News 'Who is hiring'"),
    "board": (8, "Listed on a curated third-party job board"),
}

FEE = re.compile(
    r"\b(registration|training|joining|processing|security|application|onboarding|kit)\s+(fee|deposit|charge)s?\b|"
    r"\bpay (a|the)?\s*(fee|deposit)\b|\brefundable deposit\b|\binvest(ment)? (of|required)\b|"
    r"\b(fee|deposit) (of|is) (rs|₹|\$|inr)",
    re.I,
)
OFF_PLATFORM = re.compile(r"whats\s?app|telegram|signal app|wechat|text (us|me) (at|on)|dm (us|me)", re.I)
FREE_MAIL = re.compile(r"[\w.+-]+@(gmail|yahoo|hotmail|outlook|rediffmail|protonmail|ymail)\.com", re.I)
URGENCY = re.compile(
    r"(immediate(ly)? (joining|hiring|start)|limited (seats|slots|vacancies)|urgent(ly)? hiring|"
    r"apply (now|today) before|only \d+ (seats|positions) left|hurry)",
    re.I,
)
TOO_GOOD = re.compile(
    r"(earn|make) (up to )?(\$|₹|rs\.?)\s?\d[\d,]*\s?(k|lakh)?\s?(per|a|/)\s?(day|week)|"
    r"no experience (needed|required).{0,40}(earn|\$|₹)|work from home.{0,30}(earn|income)|"
    r"guaranteed (income|placement|job)|100% (job|placement) guarantee|be your own boss|"
    r"passive income|unlimited earning",
    re.I,
)
SENSITIVE_ASK = re.compile(
    r"(send|share|provide).{0,30}(bank (account|details)|aadhaar|pan card|ssn|social security|passport copy|credit card)",
    re.I,
)
TASK_SCAM = re.compile(r"\b(data entry|copy[- ]paste|form filling|captcha (entry|typing)|like (and|&) subscribe|rate products)\b", re.I)
SHORTENER = re.compile(r"\b(bit\.ly|tinyurl|t\.me|wa\.me|forms\.gle|goo\.gl|cutt\.ly|rb\.gy)/", re.I)


@dataclass
class TrustResult:
    score: int
    label: str
    reasons: list[dict]


# Employers routinely *warn* about fee scams ("we will never charge a registration fee") and
# tell agencies "we will not pay a fee". A red-flag phrase only counts when it isn't negated.
_NEGATION = re.compile(r"\b(never|not|no|won't|don't|doesn't|without|nor|neither|free of)\b|n't\b", re.I)


def _affirmed(rx: re.Pattern, text: str) -> bool:
    for m in rx.finditer(text):
        window = text[max(0, m.start() - 90): m.start()]
        clause = re.split(r"[.!?;:\n]", window)[-1]  # only the same sentence/clause
        if not _NEGATION.search(clause) and not re.search(r"\b(agenc|placement|recruit(er|ment) (firm|vendor)|third[- ]party)", text[m.start(): m.end() + 80], re.I):
            return True
    return False


def _domain(url: str | None) -> str:
    try:
        host = urlparse(url or "").hostname or ""
    except ValueError:
        return ""
    return host.removeprefix("www.")


def _label(score: int) -> str:
    if score >= 80:
        return "verified"
    if score >= 60:
        return "likely_genuine"
    if score >= 35:
        return "caution"
    return "likely_scam"


def score_trust(
    *,
    title: str,
    company: str,
    description: str,
    url: str,
    source_kind: str,
    company_domain: str | None = None,
    salary_max: float | None = None,
    salary_currency: str | None = None,
    salary_period: str | None = None,
    exp_min: float | None = None,
    cross_listed_on_ats: bool = False,
    apply_on_ats: bool = False,
    listing_only: bool = False,
    duplicate_text_count: int = 0,
) -> TrustResult:
    score = 50
    reasons: list[dict] = []

    def add(points: int, signal: str, detail: str) -> None:
        nonlocal score
        score += points
        reasons.append({"signal": signal, "impact": points, "detail": detail})

    base, why = SOURCE_BASE.get(source_kind, (0, "Unknown source"))
    if base:
        add(base, "source", why)

    if cross_listed_on_ats and source_kind not in ("ats", "bigtech"):
        add(25, "cross_listed", "Same role also appears on the company's own careers system")

    if apply_on_ats and source_kind not in ("ats", "bigtech"):
        add(18, "apply_on_ats", "Apply link goes straight to the employer's applicant tracking system")

    apply_domain = _domain(url)
    company_key = norm_company(company)
    if company_domain and apply_domain.endswith(company_domain.removeprefix("www.")):
        add(6, "domain_match", f"Apply link is on the company's domain ({apply_domain})")
    elif company_key and len(company_key) > 3 and company_key[:6] in apply_domain.replace("-", "").replace(".", ""):
        add(4, "domain_match", f"Apply link domain matches company name ({apply_domain})")

    text = f"{title}\n{description}"

    official = source_kind in ("ats", "bigtech")
    if _affirmed(FEE, text):
        # On the employer's own ATS the posting's provenance is proven, so fee wording is far more
        # likely product copy ("no security deposit card") than a scam: flag it, don't condemn it.
        if official:
            add(-15, "mentions_fee", "Mentions a fee or deposit — read carefully; employers never charge candidates")
        else:
            add(-60, "asks_for_fee", "Mentions a registration, training or deposit fee — genuine employers never charge candidates")
    if _affirmed(SENSITIVE_ASK, text):
        add(-40, "sensitive_data", "Asks for bank, ID or card details up front")
    if OFF_PLATFORM.search(text):
        add(-20, "off_platform_contact", "Pushes contact to WhatsApp/Telegram instead of an application form")
    if FREE_MAIL.search(text):
        add(-15, "free_email", "Recruiter contact uses a free email address (gmail/yahoo/…)")
    if SHORTENER.search(text) or SHORTENER.search(url or ""):
        add(-15, "link_shortener", "Uses link shorteners or chat links to apply")
    if TOO_GOOD.search(text):
        add(-35, "too_good_to_be_true", "Promises guaranteed or unusually easy income")
    if TASK_SCAM.search(text) and source_kind not in ("ats", "bigtech"):
        add(-20, "task_scam_pattern", "Data-entry / copy-paste style work bundled into an AI role")
    if URGENCY.search(text):
        add(-8, "pressure", "Uses pressure tactics (limited seats, immediate joining)")

    if salary_max and salary_period == "year" and (exp_min is None or exp_min <= 1):
        if (salary_currency == "INR" and salary_max > 6_000_000) or (salary_currency == "USD" and salary_max > 400_000):
            add(-15, "unrealistic_pay", "Pay is far above market for an entry-level role")

    words = len(description.split())
    if words == 0 or listing_only:
        pass  # listing-only source: the description lives on the employer page, not a red flag
    elif words < 60:
        add(-12, "thin_description", f"Very short description ({words} words) — no real responsibilities listed")
    elif words > 250:
        add(4, "detailed_description", "Detailed responsibilities and requirements")

    if duplicate_text_count >= 3:
        add(-15, "mass_posted", f"Identical text posted under {duplicate_text_count} different companies")

    if not company or company.lower() in ("confidential", "company", "hiring", "unknown", "stealth"):
        add(-10, "anonymous_company", "Employer name is hidden")

    score = max(0, min(100, score))
    return TrustResult(score=score, label=_label(score), reasons=reasons)

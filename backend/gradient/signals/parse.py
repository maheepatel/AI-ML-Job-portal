"""Pure parsing helpers (no network): hiring-intent detection and funding headlines."""

import html
import re

HIRING = re.compile(
    # A subject has to be doing the hiring: "Hiring a data scientist won't fix bad data" isn't a job post.
    r"\b(we(?:'|’)?re (?:now )?hiring|we are (?:now )?hiring|i(?:'|’)?m hiring|i am hiring|is hiring|are hiring|now hiring"
    r"|#hiring|join (?:our|my) team|open (?:role|position)s?|looking to hire|we(?:'|’)?re looking for an?)\b", re.I)
NOT_HIRING = re.compile(r"\b(open to work|looking for (?:a )?(?:job|work|role)|laid off|hire me|i(?:'|’)?m looking for)\b", re.I)
AI = re.compile(
    r"\b(ai|a\.i\.|ml|machine learning|deep learning|llms?|genai|generative ai|data scien\w*|computer vision|nlp"
    r"|mlops|applied scien\w*|research engineer|pytorch|agents?|rag)\b", re.I)


def strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>", "\n", text or "", flags=re.I)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def is_hiring_post(text: str) -> bool:
    return bool(HIRING.search(text) and AI.search(text) and not NOT_HIRING.search(text))


def is_ai(text: str) -> bool:
    return bool(AI.search(text or "") or re.search(r"[a-z](?:AI|\.ai)\b", text or ""))


ROUND_RANK = {"pre-seed": 5, "seed": 5, "angel": 4, "pre-series-a": 5, "series-a": 5, "funding": 1}


def round_rank(r: str) -> int:
    return 3 if r.startswith("yc-") else ROUND_RANK.get(r, 1)


# ---------------------------------------------------------------- funding headlines

_VERB = r"(?:raises|raised|secures|secured|bags|lands|closes|nabs|picks up|scores|gets|announces|snags)"
# Longest unit first ("million" before "m"); the unit is optional ("$500,000").
_AMOUNT = (r"(?P<amt>(?:us)?\$\s?[\d.,]*\d(?:\s?(?:million|billion|mn|bn|m|b|k)\b)?"
           r"|(?:₹|rs\.?|inr)\s?[\d.,]*\d(?:\s?(?:crore|cr|lakh|million|mn)\b)?"
           r"|[€£]\s?[\d.,]*\d(?:\s?(?:million|billion|mn|bn|m|k)\b)?)")
FUNDING = re.compile(rf"^(?P<pre>.+?)\s+{_VERB}\b\s*(?:an?\s+)?(?:{_AMOUNT})?", re.I)
ROUND = re.compile(r"\b(pre[- ]seed|seed|angel|pre[- ]series[- ]a|series[- ]a)\b", re.I)
LATER = re.compile(r"\bseries[- ][b-h]\b|\bipo\b|\bdebt\b|\bacquir", re.I)
_LEAD_JUNK = re.compile(r"^(?:exclusive|funding|breaking|report|first look)\s*[:|-]?\s*", re.I)
# Words that end a descriptor ("Space startup", "Rahul Dravid-backed"): the name starts after them.
_BREAKER = re.compile(r"^(?:startup|start-up|platform|company|firm|maker|provider|unicorn|player|venture|"
                      r"[\w.]+-(?:backed|based|led|focused|powered|born|founded))$", re.I)
# Capitalised words, Matters.AI-style names and tokens like "AI", "Labs", "42".
_NAME_TOKEN = re.compile(r"^(?:[A-Z0-9][\w.&'’+-]*|[a-z]+\.(?:ai|io|so|xyz|dev|app))$")
_GENERIC = {"AI", "Startup", "The", "A", "An", "Indian", "US", "UK", "Israeli", "European", "Bengaluru", "Delhi", "Mumbai",
            "SaaS", "B2B", "Fintech", "Healthtech", "Edtech", "Deeptech", "Agentic", "Physical", "Defense", "Defence", "Legal",
            "Riyadh", "Dubai", "Singapore", "London", "Paris", "Berlin", "Chennai", "Hyderabad", "Pune", "Gurugram",
            "Noida", "Saudi", "German", "French", "Canadian", "Australian", "Japanese", "Korean", "Chinese", "Kenyan",
            "Nigerian", "African", "Brazilian", "Mexican", "Spanish", "Dutch", "Swiss", "Swedish", "Finnish", "Danish",
            "Startup", "Start-up", "Platform", "Company", "Firm", "Exclusive"}


def company_from(pre: str) -> str | None:
    pre = _LEAD_JUNK.sub("", pre.strip().strip("'\"‘’“”"))
    tokens = pre.replace("’s", "").replace("'s", "").split()
    name: list[str] = []
    for tok in reversed(tokens):
        tok = tok.strip(",:;()")
        if _NAME_TOKEN.match(tok) and not _BREAKER.match(tok):
            name.insert(0, tok)
            if len(name) == 3:
                break
        else:
            break
    while name and name[0] in _GENERIC and len(name) > 1:
        name.pop(0)  # "AI startup X" leaves "X"; a lone "AI" means no name was found
    if not name or (len(name) == 1 and name[0] in _GENERIC) or all(t.isdigit() for t in name):
        return None
    return " ".join(name)


def _usd(amount: str | None) -> float | None:
    if not amount:
        return None
    a = amount.lower().replace(",", "").replace(" ", "")
    num = re.search(r"[\d.]+", a)
    if not num:
        return None
    try:
        v = float(num.group())
    except ValueError:
        return None
    if re.search(r"(b|bn|billion)$", a):
        v *= 1e9
    elif re.search(r"(m|mn|million)$", a):
        v *= 1e6
    elif a.endswith("k"):
        v *= 1e3
    elif re.search(r"(crore|cr)$", a):
        v *= 1e7
    elif a.endswith("lakh"):
        v *= 1e5
    if a.startswith(("₹", "rs", "inr")):
        v /= 84
    elif a.startswith("€"):
        v *= 1.08
    elif a.startswith("£"):
        v *= 1.27
    return round(v)


def parse_funding(headline: str) -> dict | None:
    """'AI startup Humyn Labs raises $47M in Series A - Business Standard' -> fields, or None."""
    title = re.sub(r"\s+[-|–]\s+[^-|–]{2,60}$", "", headline.strip())  # drop " - Publisher"
    if LATER.search(title):
        return None  # early-stage only: founders still hire directly before Series B
    m = FUNDING.search(title)
    if not m:
        return None
    company = company_from(m.group("pre"))
    if not company:
        return None
    rnd = ROUND.search(title)
    round_name = re.sub(r"[\s-]+", "-", rnd.group(1).lower()) if rnd else "funding"
    amt = (m.group("amt") or "").strip() or None
    usd = _usd(amt)
    if round_name == "funding" and (usd is None or usd > 40e6):
        return None  # unlabelled big rounds are usually late stage
    return {"company": company, "round": round_name, "amount_text": amt, "amount_usd": usd, "headline": title}


def company_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace(" labs", "").replace(" inc", "").replace(".ai", "ai"))

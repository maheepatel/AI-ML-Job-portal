import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES = re.compile(r"\n\s*\n+")
_BLOCK_TAGS = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|section)[^>]*>", re.I)


def html_to_text(raw: str | None, limit: int = 20000) -> str:
    if not raw:
        return ""
    text = html.unescape(raw)
    if "<" in text:
        text = _BLOCK_TAGS.sub("\n", text)
        text = _TAG.sub(" ", text)
        text = html.unescape(text)
    text = _WS.sub(" ", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()[:limit]


# ---------- location ----------

INDIA_CITIES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "mumbai": "Mumbai", "pune": "Pune",
    "hyderabad": "Hyderabad", "chennai": "Chennai", "delhi": "Delhi NCR", "new delhi": "Delhi NCR",
    "gurgaon": "Delhi NCR", "gurugram": "Delhi NCR", "noida": "Delhi NCR", "kolkata": "Kolkata",
    "ahmedabad": "Ahmedabad", "jaipur": "Jaipur", "kochi": "Kochi", "trivandrum": "Thiruvananthapuram",
    "coimbatore": "Coimbatore", "indore": "Indore", "chandigarh": "Chandigarh", "mysore": "Mysuru",
}
OTHER_CITIES = {
    "san francisco": ("San Francisco", "United States"), "new york": ("New York", "United States"),
    "seattle": ("Seattle", "United States"), "boston": ("Boston", "United States"),
    "austin": ("Austin", "United States"), "palo alto": ("Palo Alto", "United States"),
    "mountain view": ("Mountain View", "United States"), "los angeles": ("Los Angeles", "United States"),
    "chicago": ("Chicago", "United States"), "london": ("London", "United Kingdom"),
    "berlin": ("Berlin", "Germany"), "munich": ("Munich", "Germany"), "paris": ("Paris", "France"),
    "amsterdam": ("Amsterdam", "Netherlands"), "dublin": ("Dublin", "Ireland"), "zurich": ("Zurich", "Switzerland"),
    "toronto": ("Toronto", "Canada"), "vancouver": ("Vancouver", "Canada"), "singapore": ("Singapore", "Singapore"),
    "tel aviv": ("Tel Aviv", "Israel"), "sydney": ("Sydney", "Australia"), "tokyo": ("Tokyo", "Japan"),
    "warsaw": ("Warsaw", "Poland"), "barcelona": ("Barcelona", "Spain"), "madrid": ("Madrid", "Spain"),
    "stockholm": ("Stockholm", "Sweden"), "dubai": ("Dubai", "United Arab Emirates"),
}
COUNTRIES = {
    "india": "India", "united states": "United States", "usa": "United States", "u.s.": "United States",
    "united kingdom": "United Kingdom", "uk": "United Kingdom", "england": "United Kingdom",
    "germany": "Germany", "france": "France", "canada": "Canada", "netherlands": "Netherlands",
    "ireland": "Ireland", "spain": "Spain", "poland": "Poland", "singapore": "Singapore",
    "australia": "Australia", "japan": "Japan", "israel": "Israel", "switzerland": "Switzerland",
    "sweden": "Sweden", "portugal": "Portugal", "brazil": "Brazil", "mexico": "Mexico",
    "united arab emirates": "United Arab Emirates", "uae": "United Arab Emirates",
}
US_STATE = re.compile(r",\s*(CA|NY|WA|MA|TX|IL|CO|GA|NC|VA|PA|NJ|FL|OR|UT|MD|MI|MN|OH|AZ|DC)\b")
EU_COUNTRIES = {"Germany", "France", "Netherlands", "Ireland", "Spain", "Poland", "Sweden", "Portugal", "Switzerland"}


@dataclass
class Location:
    city: str | None
    country: str | None
    work_mode: str  # remote | hybrid | onsite | unknown


def parse_location(raw: str, remote_flag: bool | None = None, extra: str = "") -> Location:
    low = f"{raw} {extra}".lower()
    city = country = None
    for key, name in INDIA_CITIES.items():
        if re.search(rf"\b{key}\b", low):
            city, country = name, "India"
            break
    if not city:
        for key, (name, ctry) in OTHER_CITIES.items():
            if key in low:
                city, country = name, ctry
                break
    if not country:
        for key, name in COUNTRIES.items():
            if re.search(rf"(?<![a-z]){re.escape(key)}(?![a-z])", low):
                country = name
                break
    if not country and US_STATE.search(raw or ""):
        country = "United States"

    if remote_flag or re.search(r"\bremote\b|work from home|\bwfh\b|anywhere", low):
        mode = "remote"
    elif "hybrid" in low:
        mode = "hybrid"
    elif city or "on-site" in low or "onsite" in low or "office" in low:
        mode = "onsite"
    else:
        mode = "unknown"
    return Location(city, country, mode)


def region_of(country: str | None) -> str | None:
    if country == "India":
        return "India"
    if country == "United States" or country == "Canada":
        return "North America"
    if country in EU_COUNTRIES or country == "United Kingdom":
        return "Europe"
    return None


# ---------- salary ----------

_MONEY = re.compile(
    r"(?P<cur>₹|\$|€|£|inr|usd|eur|gbp|rs\.?)\s?(?P<a>\d[\d,.]*)\s?(?:(?P<ak>lpa|lakhs?|cr|k|l)(?![a-z]))?"
    r"(?:\s?(?:-|–|to)\s?(?:₹|\$|€|£|inr|usd|eur|gbp|rs\.?)?\s?(?P<b>\d[\d,.]*)\s?(?:(?P<bk>lpa|lakhs?|cr|k|l)(?![a-z]))?)?",
    re.I,
)
_CUR = {"₹": "INR", "inr": "INR", "rs": "INR", "rs.": "INR", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR", "£": "GBP", "gbp": "GBP"}


def _scale(num: str, suffix: str | None) -> float:
    value = float(num.replace(",", ""))
    s = (suffix or "").lower()
    if s == "k":
        value *= 1_000
    elif s in ("l", "lpa", "lakh", "lakhs"):
        value *= 100_000
    elif s == "cr":
        value *= 10_000_000
    return value


def parse_salary(text: str) -> tuple[float | None, float | None, str | None, str | None]:
    m = _MONEY.search(text or "")
    if not m:
        return None, None, None, None
    try:
        lo = _scale(m["a"], m["ak"] or m["bk"])
        hi = _scale(m["b"], m["bk"] or m["ak"]) if m["b"] else None
    except ValueError:
        return None, None, None, None
    cur = _CUR.get(m["cur"].lower(), m["cur"].upper())
    tail = text[m.end(): m.end() + 25].lower()
    period = "hour" if "hour" in tail or "/hr" in tail else "month" if "month" in tail else "year"
    if lo < 100 and period == "year":  # "$45 - $60" style hourly ranges with no unit
        period = "hour"
    return lo, hi, cur, period


# ---------- dates ----------

def parse_dt(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = value / 1000 if value > 10_000_000_000 else value
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    s = str(value).strip()
    if s.isdigit():
        return parse_dt(int(s))
    s = s.replace("Z", "+00:00")
    for fmt in (None, "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.fromisoformat(s) if fmt is None else datetime.strptime(s, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


_RELATIVE = re.compile(r"(\d+)\+?\s*(minute|hour|day|week|month)s?\s+ago", re.I)


def parse_relative(text: str, now: datetime) -> datetime | None:
    """Workday/LinkedIn style 'Posted 3 Days Ago', 'Posted Today', '30+ Days Ago'."""
    low = (text or "").lower()
    if "today" in low or "just now" in low:
        return now
    if "yesterday" in low:
        return now - timedelta(days=1)
    m = _RELATIVE.search(low)
    if not m:
        return None
    n, unit = int(m[1]), m[2].lower()
    delta = {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n),
             "week": timedelta(weeks=n), "month": timedelta(days=30 * n)}[unit]
    return now - delta


# ---------- identity ----------

_COMPANY_NOISE = re.compile(r"\b(inc|llc|ltd|limited|pvt|private|corp|corporation|co|gmbh|technologies|labs?)\b\.?", re.I)
_TITLE_NOISE = re.compile(r"\(.*?\)|\[.*?\]|[-–|,/].*?(remote|hybrid|onsite|india|us|uk)\b.*$", re.I)


def norm_company(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", _COMPANY_NOISE.sub("", name.lower()))


def norm_title(title: str) -> str:
    t = _TITLE_NOISE.sub("", title.lower())
    t = re.sub(r"\bsr\b", "senior", t)
    t = re.sub(r"\bjr\b", "junior", t)
    return re.sub(r"[^a-z0-9]", "", t)


def fingerprint(company: str, title: str, city: str | None) -> str:
    key = f"{norm_company(company)}|{norm_title(title)}|{(city or '').lower()}"
    return hashlib.sha1(key.encode()).hexdigest()

"""Resume → profile → ranked, explained job matches.

score = 100 × (0.35 skills + 0.20 text similarity + 0.15 experience fit + 0.12 role fit
              + 0.12 location + 0.06 freshness) × trust factor

The TF-IDF index over open jobs is rebuilt lazily whenever a new scrape run lands.
"""

import io
import re
import threading
from datetime import datetime, timezone

import numpy as np

from .classify import extract_skills
from .normalize import parse_location

WEIGHTS = {"skills": 0.35, "similarity": 0.20, "experience": 0.15, "role": 0.12, "location": 0.12, "freshness": 0.06}

# Skills that matter most for AI/ML hiring count double in the overlap score.
CORE_SKILLS = {
    "Python", "SQL", "Machine Learning", "Deep Learning", "PyTorch", "TensorFlow", "scikit-learn", "LLMs", "RAG",
    "NLP", "Computer Vision", "Generative AI", "Statistics", "Pandas", "AI Agents", "MLOps", "Spark",
}

_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_RANGE = re.compile(
    rf"({_MONTHS})[a-z]*\.?\s+(\d{{4}})\s*[-–to]+\s*(present|current|now|({_MONTHS})[a-z]*\.?\s+(\d{{4}}))", re.I
)
_MONTH_NUM = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}
_PII = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+|\+?\d[\d\s-]{8,}\d|https?://\S+")


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    # Résumés run 1-3 pages; the cap bounds how much work an uploaded PDF can cause.
    return "\n".join(page.extract_text() or "" for page in reader.pages[:6])


def years_of_experience(text: str, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    total = 0.0
    for m in _RANGE.finditer(text):
        start = datetime(int(m[2]), _MONTH_NUM[m[1][:3].lower()], 1, tzinfo=timezone.utc)
        if m[3].lower() in ("present", "current", "now"):
            end = now
        else:
            end = datetime(int(m[5]), _MONTH_NUM[m[4][:3].lower()], 1, tzinfo=timezone.utc)
        months = max(0, (end.year - start.year) * 12 + end.month - start.month)
        context = text[max(0, m.start() - 120): m.start()].lower()
        total += months * (0.5 if "intern" in context else 1.0)  # internships count half
    return round(total / 12, 1)


def profile_from_text(text: str) -> dict:
    skills = extract_skills(text)
    low = text.lower()
    targets = ["Data Scientist", "ML Engineer", "AI Engineer / LLM", "Data & Analytics", "AI Product Engineering"]
    if "Computer Vision" in skills or "yolo" in low:
        targets.append("Computer Vision")
    if "NLP" in skills:
        targets.append("NLP & Speech")
    city = parse_location(text[:400])
    return {
        "skills": skills,
        "years_experience": years_of_experience(text),
        "target_roles": targets,
        "locations": {"city": city.city or "Bengaluru", "country": city.country or "India", "remote_ok": True},
        # Contact details stripped: only the professional content feeds similarity search.
        "keywords_text": _PII.sub(" ", text)[:8000],
    }


def profile_from_pdf(data: bytes) -> dict:
    return profile_from_text(_pdf_text(data))


# ---------------------------------------------------------------- index


class JobIndex:
    """TF-IDF matrix over open canonical jobs, rebuilt when the data version changes."""

    def __init__(self):
        self._lock = threading.Lock()
        self.version = None
        self.vectorizer = None
        self.matrix = None
        self.rows: list[dict] = []

    @staticmethod
    def fit(rows: list[dict]):
        """Vectorize job rows (each with a 'text' key, dropped afterwards). ~10 s for ~8k jobs."""
        from sklearn.feature_extraction.text import TfidfVectorizer

        docs = [f"{r['title']} {r['title']} {' '.join(r['skills'])} {r.pop('text', '')}" for r in rows]
        vec = TfidfVectorizer(stop_words="english", max_features=60000, ngram_range=(1, 2), min_df=2,
                              sublinear_tf=True, dtype=np.float32)
        return vec, (vec.fit_transform(docs) if docs else None)

    def load(self, version, vectorizer, matrix, rows: list[dict]) -> None:
        with self._lock:
            self.vectorizer, self.matrix, self.rows, self.version = vectorizer, matrix, rows, version

    def ensure(self, version, load_rows) -> None:
        """Fallback when no prebuilt index exists: build in-process."""
        if version == self.version:
            return
        with self._lock:
            if version == self.version:
                return
            rows = load_rows()
            vec, matrix = self.fit(rows)
            self.vectorizer, self.matrix, self.rows, self.version = vec, matrix, rows, version


INDEX = JobIndex()


def _experience_fit(years: float, exp_min, seniority: str) -> tuple[float, str]:
    if seniority == "intern":
        return (1.0, "Internship suits a fresher") if years < 1 else (0.45, "Internship — below your experience level")
    if exp_min is None:
        return (0.85, "Experience not stated; entry/junior title") if seniority in ("entry", "junior") else (0.75, "Experience not stated")
    if exp_min <= years + 0.3:
        return 1.0, f"Asks {exp_min:g}+ yrs, you have {years:g}"
    if exp_min <= years + 1.2:
        return 0.6, f"Asks {exp_min:g}+ yrs — a slight stretch from your {years:g}"
    return 0.2, f"Asks {exp_min:g}+ yrs — well above your {years:g}"


def _location_fit(profile: dict, row: dict) -> tuple[float, str]:
    pref = profile.get("locations") or {}
    if row["city"] and row["city"] == pref.get("city"):
        return 1.0, f"In {row['city']}"
    if row["work_mode"] == "remote":
        if row["country"] in (None, pref.get("country")):
            return 0.95 if pref.get("remote_ok", True) else 0.6, "Remote"
        return 0.5, f"Remote, but restricted to {row['country']}"
    if row["country"] and row["country"] == pref.get("country"):
        return 0.85, f"In {row['country']}"
    return 0.3, f"Located in {row['city'] or row['country'] or 'unspecified location'}"


def match_jobs(profile: dict, limit: int = 100, min_trust: int = 35) -> list[dict]:
    if INDEX.matrix is None or not INDEX.rows:
        return []
    from sklearn.metrics.pairwise import linear_kernel

    years = float(profile.get("years_experience") or 0)
    pskills = set(profile.get("skills") or [])
    targets = set(profile.get("target_roles") or [])
    qvec = INDEX.vectorizer.transform([f"{' '.join(pskills)} {' '.join(targets)} {profile.get('keywords_text', '')}"])
    sims = linear_kernel(qvec, INDEX.matrix).ravel()
    top_sim = float(sims.max()) or 1.0
    now = datetime.now(timezone.utc)

    scored = []
    for i, row in enumerate(INDEX.rows):
        if row["trust_score"] < min_trust:
            continue
        jskills = set(row["skills"])
        matched = jskills & pskills
        weight = lambda s: 2 if s in CORE_SKILLS else 1  # noqa: E731
        denom = sum(weight(s) for s in jskills) or 1
        skill = min(1.0, sum(weight(s) for s in matched) / min(denom, 12)) if jskills else 0.5
        sim = min(1.0, float(sims[i]) / top_sim)
        exp, exp_why = _experience_fit(years, row["exp_min"], row["seniority"])
        role = 1.0 if row["role_family"] in targets else 0.45
        loc, loc_why = _location_fit(profile, row)
        posted = row["live_since"]
        age_days = (now - posted).total_seconds() / 86400 if posted else 30
        fresh = 1.0 if age_days <= 3 else max(0.4, 1 - (age_days - 3) / 45)
        parts = {"skills": skill, "similarity": sim, "experience": exp, "role": role, "location": loc, "freshness": fresh}
        base = sum(WEIGHTS[k] * v for k, v in parts.items())
        trust_factor = 0.75 + 0.25 * row["trust_score"] / 100
        score = round(100 * base * trust_factor)
        scored.append((score, i, parts, matched, exp_why, loc_why))

    scored.sort(key=lambda x: -x[0])
    out = []
    for score, i, parts, matched, exp_why, loc_why in scored[:limit]:
        row = INDEX.rows[i]
        missing = [s for s in row["skills"] if s not in matched]
        missing.sort(key=lambda s: s not in CORE_SKILLS)
        out.append({
            "job_id": row["id"],
            "score": score,
            "breakdown": {k: round(v, 2) for k, v in parts.items()},
            "matched_skills": sorted(matched, key=lambda s: s not in CORE_SKILLS),
            "missing_skills": missing[:6],
            "why": [exp_why, loc_why],
        })
    return out

"""Tailor the master CV to one job with an LLM, then *verify* the result against the master.

The model may only reorder and rephrase what is already true. Every rewritten bullet is checked:
numbers must come from its source bullet and named skills must already appear somewhere in the
master CV. Anything that fails falls back to the original wording and is reported as a warning,
so a tailored CV can never claim more than the real one.
"""

import copy
import json
import re
import urllib.error
import urllib.request

from ..config import settings
from ..domain.classify import extract_skills

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
_NUM = re.compile(r"\d+(?:[.,]\d+)?")


class TailorError(RuntimeError):
    pass


def load_master() -> dict:
    if settings.master_cv_json:
        return json.loads(settings.master_cv_json)
    path = settings.profile_file.parent / "master_cv.json"
    if not path.exists():
        raise TailorError("No master CV: set GRADIENT_MASTER_CV_JSON or create data/master_cv.json")
    return json.loads(path.read_text(encoding="utf-8"))


def master_text(cv: dict) -> str:
    parts = [cv.get("summary", ""), " ".join(cv.get("skills", []))]
    for sec in ("experience", "projects"):
        for item in cv.get(sec, []):
            parts += [item.get("title", ""), *item.get("bullets", [])]
    return "\n".join(parts)


def _numbers(text: str) -> set[str]:
    return {n.replace(",", "") for n in _NUM.findall(text)}


def _llm(messages: list[dict]) -> dict:
    if not settings.groq_api_key:
        raise TailorError("GRADIENT_GROQ_API_KEY is not set on the server")
    body = {"model": settings.groq_model, "messages": messages, "temperature": 0.2,
            "response_format": {"type": "json_object"}, "max_tokens": 2200}
    req = urllib.request.Request(GROQ_URL, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {settings.groq_api_key}",
                                          "Content-Type": "application/json", "User-Agent": "gradient-jobs"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise TailorError("Groq rate limit hit (free tier). Wait a minute and try again.") from None
        raise TailorError(f"Groq error {exc.code}: {exc.read().decode(errors='replace')[:200]}") from None
    except (urllib.error.URLError, TimeoutError) as exc:
        raise TailorError(f"Could not reach Groq: {exc}") from None
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, json.JSONDecodeError):
        raise TailorError("The model returned malformed JSON; try again") from None


SYSTEM = """You tailor a candidate's CV to one job posting. Hard rules:
- Never invent experience, employers, projects, numbers, tools or skills. Only reorder and rephrase what is in MASTER_CV.
- Every rewritten bullet must keep the facts and numbers of the original bullet it comes from.
- You may surface job keywords only where the original bullet already supports them.
- Write plainly, no buzzwords, no em dashes.
Return JSON:
{"summary": "2-3 sentence summary aimed at this role, true to MASTER_CV",
 "skills": ["MASTER_CV skills, most relevant to the job first"],
 "experience": [{"id": "...", "bullets": [{"src": <index of original bullet>, "text": "..."}]}],
 "projects": [{"id": "...", "bullets": [{"src": <index>, "text": "..."}]}],
 "project_order": ["project ids, most relevant first; drop at most 2 irrelevant ones"],
 "gaps": ["job requirements the CV genuinely does not show"],
 "answers": {"why_this_role": "...", "why_this_company": "...", "relevant_project": "...", "years_experience": "..."}}"""


def tailor(cv: dict, job: dict) -> dict:
    """job: title, company, description, skills. Returns a verified tailored CV."""
    user = json.dumps({"JOB": {"title": job["title"], "company": job["company"],
                               "description": (job.get("description") or "")[:3500],
                               "skills_wanted": job.get("skills", [])},
                       "MASTER_CV": {k: cv[k] for k in ("summary", "skills", "experience", "projects", "facts") if k in cv}})
    out = _llm([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}])
    return verify(cv, out)


def verify(cv: dict, out: dict) -> dict:
    allowed_lower = {s.lower() for s in extract_skills(master_text(cv))} | {s.lower() for s in cv.get("skills", [])}
    all_numbers = _numbers(master_text(cv))
    warnings: list[str] = []
    result = copy.deepcopy(cv)

    def clean(text: str) -> str:
        return (text or "").strip().replace("—", ", ").replace("–", "-")

    def safe(new: str, source: str, where: str) -> str:
        new = clean(new)
        if not new:
            return source
        extra_nums = _numbers(new) - _numbers(source)
        extra_skills = [s for s in extract_skills(new) if s.lower() not in allowed_lower]
        if extra_nums or extra_skills:
            what = ", ".join([*sorted(extra_nums), *extra_skills])
            warnings.append(f"{where}: kept the original wording (the rewrite added {what}, which isn't in your CV)")
            return source
        return new

    summary = clean(out.get("summary") or "")
    if summary:
        bad_nums = _numbers(summary) - all_numbers
        bad_sk = [s for s in extract_skills(summary) if s.lower() not in allowed_lower]
        if bad_nums or bad_sk:
            warnings.append(f"Summary: kept the original (the rewrite added {', '.join([*sorted(bad_nums), *bad_sk])})")
        else:
            result["summary"] = summary

    master_skills = {s.lower(): s for s in cv.get("skills", [])}
    asked = [s for s in out.get("skills", []) or [] if isinstance(s, str)]
    ordered = [master_skills[s.lower()] for s in asked if s.lower() in master_skills]
    dropped = [s for s in asked if s.lower() not in master_skills]
    if dropped:
        warnings.append(f"Skills not on your CV were left out: {', '.join(dropped[:8])}")
    result["skills"] = list(dict.fromkeys(ordered + cv.get("skills", [])))

    for sec in ("experience", "projects"):
        by_id = {i["id"]: i for i in result.get(sec, [])}
        for item in out.get(sec, []) or []:
            target = by_id.get(item.get("id")) if isinstance(item, dict) else None
            if not target:
                continue
            original = target["bullets"]
            new_bullets, used = [], set()
            for b in item.get("bullets", []) or []:
                src = b.get("src") if isinstance(b, dict) else None
                if not isinstance(src, int) or not 0 <= src < len(original) or src in used:
                    continue
                used.add(src)
                new_bullets.append(safe(b.get("text", ""), original[src], f"{target['title']} bullet {src + 1}"))
            # Bullets the model skipped stay, after the reordered ones: nothing true is lost.
            new_bullets += [b for i, b in enumerate(original) if i not in used]
            target["bullets"] = new_bullets

    order = [p for p in out.get("project_order", []) or [] if isinstance(p, str)]
    projects = {p["id"]: p for p in result.get("projects", [])}
    kept = [projects[p] for p in dict.fromkeys(order) if p in projects]
    if len(kept) >= max(1, len(projects) - 2):
        result["projects"] = kept

    answers = out.get("answers") if isinstance(out.get("answers"), dict) else {}
    return {"cv": result, "gaps": [g for g in out.get("gaps", []) or [] if isinstance(g, str)][:8],
            "answers": {k: clean(v) for k, v in answers.items() if isinstance(v, str)}, "warnings": warnings}

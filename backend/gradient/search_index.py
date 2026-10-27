"""The match index's lifecycle: built by the scraper after each sweep, stored in the DB, and
loaded by the web tier. A small web instance (e.g. Render free, 0.1 CPU) would need minutes to
fit the TF-IDF model itself; loading the prebuilt one takes about a second."""

import logging
import pickle
import zlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import aware, utcnow
from .domain.matching import INDEX, JobIndex
from .models import Artifact, Job, ScrapeRun

log = logging.getLogger("gradient.search_index")

NAME = "match_index"
LIVE_SINCE = func.coalesce(Job.posted_at, Job.first_seen_at)


def load_rows(session: Session) -> list[dict]:
    rows = session.execute(
        select(Job.id, Job.title, Job.skills, Job.description, Job.exp_min, Job.seniority, Job.city, Job.country,
               Job.work_mode, Job.role_family, Job.trust_score, LIVE_SINCE.label("live"))
        .where(Job.status == "open", Job.duplicate_of.is_(None), Job.trust_label != "likely_scam")
    ).all()
    return [{"id": r.id, "title": r.title, "skills": r.skills or [], "text": (r.description or "")[:3000],
             "exp_min": r.exp_min, "seniority": r.seniority, "city": r.city, "country": r.country,
             "work_mode": r.work_mode, "role_family": r.role_family, "trust_score": r.trust_score,
             "live_since": aware(r.live)} for r in rows]


def build_and_store(session: Session, version: str) -> int:
    """Fit the index over current open jobs and save it. Returns the stored size in bytes."""
    rows = load_rows(session)
    vec, matrix = JobIndex.fit(rows)
    blob = zlib.compress(pickle.dumps((vec, matrix, rows), protocol=pickle.HIGHEST_PROTOCOL), 6)
    art = session.get(Artifact, NAME) or Artifact(name=NAME)
    art.version, art.created_at, art.data = version, utcnow(), blob
    session.add(art)
    INDEX.load(version, vec, matrix, rows)  # this process can serve matches straight away too
    return len(blob)


def ensure_index(session: Session) -> None:
    """Make INDEX current: load the stored index if a newer one exists, else build locally."""
    stored = session.scalar(select(Artifact.version).where(Artifact.name == NAME))
    if stored is not None:
        if stored != INDEX.version:
            data = session.scalar(select(Artifact.data).where(Artifact.name == NAME))
            vec, matrix, rows = pickle.loads(zlib.decompress(data))  # our own DB: trusted input
            INDEX.load(stored, vec, matrix, rows)
            log.info("loaded match index %s (%d jobs)", stored, len(rows))
        return
    local = (session.scalar(select(func.max(ScrapeRun.id))),
             session.scalar(select(func.count()).select_from(Job).where(Job.status == "open")))
    INDEX.ensure(local, lambda: load_rows(session))

"""Lifecycle rules against a real (temporary) database: the logic most likely to hurt users if it regresses."""

import pytest
from sqlalchemy import delete, select

from gradient.db import init_db, session_scope, utcnow
from gradient.ingest.base import FetchResult, RawJob, Source
from gradient.ingest.pipeline import _process_source, dedupe_and_score
from gradient.models import Job, ScrapeRun, SourceRun

DESC = ("You will train PyTorch models, build RAG pipelines with LLMs and embeddings, fine-tune transformers "
        "and deploy machine learning systems to production. 1-3 years of experience required. ") * 4


class FakeAts(Source):
    name, kind, authoritative, priority = "greenhouse", "ats", True, 90

    async def fetch(self, http):  # pragma: no cover - results are injected directly
        raise NotImplementedError


class FakeLinkedIn(FakeAts):
    name, kind, authoritative, priority = "linkedin", "linkedin", False, 60


def raw(jid: str, title="Machine Learning Engineer", company="Acme AI", url=None) -> RawJob:
    return RawJob(source_job_id=jid, title=title, company=company, url=url or f"https://boards.greenhouse.io/acme/jobs/{jid}",
                  description=DESC, location="Bengaluru, India")


@pytest.fixture(autouse=True)
def clean_db():
    init_db()
    with session_scope() as s:
        for model in (SourceRun, Job, ScrapeRun):
            s.execute(delete(model))
    yield


def sweep(src: Source, jobs: list[RawJob] | None, error: str | None = None) -> dict:
    touched: set[str] = set()
    with session_scope() as s:
        run = ScrapeRun(started_at=utcnow(), status="running")
        s.add(run)
        s.flush()
        result = None if jobs is None else FetchResult(jobs=jobs, seen_ids={j.source_job_id for j in jobs})
        stats = _process_source(s, run, src, result, error, 10, touched, {})
    with session_scope() as s:
        dedupe_and_score(s, touched)
    return stats


def job(jid: str, key="greenhouse:acme") -> Job:
    with session_scope() as s:
        return s.scalars(select(Job).where(Job.source_key == key, Job.source_job_id == jid)).one()


def test_new_job_is_stored_verified_with_live_since():
    src = FakeAts("acme", "Acme AI")
    assert sweep(src, [raw("1")])["new"] == 1
    j = job("1")
    assert j.status == "open" and j.trust_label == "verified" and j.city == "Bengaluru" and j.exp_min == 1


def test_authoritative_job_closes_after_two_missed_runs_and_reopens():
    src = FakeAts("acme", "Acme AI")
    sweep(src, [raw("1"), raw("2", title="Data Scientist")])
    sweep(src, [raw("2", title="Data Scientist")])
    assert job("1").status == "open" and job("1").missed_runs == 1  # one miss is not proof
    sweep(src, [raw("2", title="Data Scientist")])
    closed = job("1")
    assert closed.status == "closed" and closed.close_reason == "removed_from_source"
    sweep(src, [raw("1"), raw("2", title="Data Scientist")])
    reopened = job("1")
    assert reopened.status == "open" and reopened.reopened_count == 1


def test_failed_source_never_closes_jobs():
    src = FakeAts("acme", "Acme AI")
    sweep(src, [raw("1")])
    for _ in range(3):
        assert sweep(src, None, error="HTTP 500")["ok"] is False
    assert job("1").status == "open" and job("1").missed_runs == 0


def test_search_source_absence_does_not_close():
    li = FakeLinkedIn("guest", "LinkedIn")
    sweep(li, [raw("9", url="https://www.linkedin.com/jobs/view/9")])
    sweep(li, [])
    sweep(li, [])
    assert job("9", "linkedin:guest").status == "open"


def test_cross_listing_dedupes_to_ats_and_boosts_linkedin_trust():
    li = FakeLinkedIn("guest", "LinkedIn")
    sweep(li, [raw("9", url="https://www.linkedin.com/jobs/view/9")])
    sweep(FakeAts("acme", "Acme AI"), [raw("1")])
    ats_job, li_job = job("1"), job("9", "linkedin:guest")
    assert ats_job.duplicate_of is None and li_job.duplicate_of == ats_job.id
    assert any(r["signal"] == "cross_listed" for r in li_job.trust_reasons)


def test_senior_and_unrelated_roles_are_not_stored():
    src = FakeAts("acme", "Acme AI")
    stats = sweep(src, [raw("1", title="Senior Machine Learning Engineer"), raw("2", title="Account Executive")])
    assert stats["kept"] == 0


def test_retention_prunes_only_old_closed_data():
    from datetime import timedelta

    from gradient.ingest.pipeline import prune

    src = FakeAts("acme", "Acme AI")
    sweep(src, [raw("1"), raw("2", title="Data Scientist"), raw("3", title="AI Engineer")])
    now = utcnow()
    with session_scope() as s:
        for jid, age in (("1", 40), ("2", 200)):
            j = s.scalars(select(Job).where(Job.source_job_id == jid)).one()
            j.status, j.closed_at = "closed", now - timedelta(days=age)
        s.add(SourceRun(run_id=s.scalars(select(ScrapeRun.id)).first(), source_key="x", source="x", ok=True,
                        finished_at=now - timedelta(days=20)))
    with session_scope() as s:
        stats = prune(s)
    # both closed jobs are past 30 days (slimmed); only the 200-day one is past 180 (deleted)
    assert stats["closed_slimmed"] == 2 and stats["closed_deleted"] == 1 and stats["source_runs_pruned"] >= 1
    assert job("1").description == "" and job("3").description  # open job untouched
    with session_scope() as s:
        assert s.scalars(select(Job).where(Job.source_job_id == "2")).first() is None


def test_undated_job_on_first_sweep_has_no_posted_time():
    src = FakeAts("acme", "Acme AI")
    sweep(src, [raw("1")])  # raw() carries no posted_at
    assert job("1").posted_at is None  # first_seen_at is not passed off as a posted time


def test_undated_job_appearing_on_an_already_swept_listing_is_posted_now():
    src = FakeAts("acme", "Acme AI")
    sweep(src, [raw("1")])
    sweep(src, [raw("1"), raw("2", title="Data Scientist")])
    assert job("1").posted_at is None
    assert job("2").posted_at is not None


def test_borrowed_posted_times_are_cleared():
    from datetime import timedelta

    from gradient.ingest.pipeline import clear_borrowed_posted_times

    src = FakeAts("acme", "Acme AI")
    sweep(src, [raw("1"), raw("2", title="Data Scientist")])
    old = utcnow() - timedelta(days=3)
    with session_scope() as s:
        for j in s.scalars(select(Job)):
            j.first_seen_at = old
            j.posted_at = old if j.source_job_id == "1" else old - timedelta(days=2)  # 1 borrowed, 2 a real date
    with session_scope() as s:
        assert clear_borrowed_posted_times(s) == 1
    assert job("1").posted_at is None and job("2").posted_at is not None

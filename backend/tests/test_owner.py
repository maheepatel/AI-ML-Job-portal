"""Owner tools: auth gate, apply-queue rules, tracker transitions and the CV fabrication guard."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from gradient.config import settings
from gradient.db import init_db, session_scope, utcnow
from gradient.models import Application, Job, ScrapeRun, SourceRun
from gradient.owner import queue as q
from gradient.owner.cvpdf import render
from gradient.owner.tailor import verify

CV = {
    "name": "Test Person", "summary": "Developer with 2+ years building ML models.",
    "skills": ["Python", "SQL", "PyTorch"],
    "experience": [{"id": "e1", "title": "AI Developer", "org": "Acme", "dates": "2024 - Present",
                    "bullets": ["Built regression models on 7,385 records with R2 of 0.99.", "Shipped AI agents for internal workflows."]}],
    "projects": [{"id": "p1", "title": "P1", "bullets": ["Did a thing in Python."]},
                 {"id": "p2", "title": "P2", "bullets": ["Did another thing."]}],
    "education": [{"school": "College", "degree": "B.Tech", "dates": "2024"}],
}


@pytest.fixture(autouse=True)
def clean():
    init_db()
    with session_scope() as s:
        for model in (Application, SourceRun, Job, ScrapeRun):
            s.execute(delete(model))
    yield


@pytest.fixture
def owner(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret-test")
    from gradient.api.app import app

    with TestClient(app) as client:
        client.headers["X-Admin-Token"] = "s3cret-test"
        yield client


def _job(**kw) -> int:
    now = utcnow()
    base = dict(source="greenhouse", source_key="greenhouse:acme", source_kind="ats", source_job_id=kw.pop("jid", "1"),
                fingerprint=kw.pop("fp", "fp1"), title="ML Engineer", company="Acme", url="https://x/1",
                role_family="ML Engineer", status="open", trust_label="verified", trust_score=90, seniority="entry",
                country="India", city="Bengaluru", work_mode="onsite", first_seen_at=now, last_seen_at=now)
    base.update(kw)
    with session_scope() as s:
        j = Job(**base)
        s.add(j)
        s.flush()
        return j.id


def test_owner_api_is_invisible_without_a_token(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", None)
    from gradient.api.app import app

    with TestClient(app) as c:
        assert c.get("/api/owner/me").status_code == 404


def test_owner_api_rejects_wrong_token(owner):
    assert owner.get("/api/owner/me", headers={"X-Admin-Token": "nope"}).status_code == 401
    assert owner.get("/api/owner/me").json()["ok"] is True


def test_eligibility_rules():
    assert not q.eligible(Job(title="Senior ML Engineer", country="India", work_mode="onsite", location_raw=""))
    assert not q.eligible(Job(title="Data Science Leader", country="India", work_mode="onsite", location_raw=""))
    assert q.eligible(Job(title="ML Engineer", country="India", work_mode="onsite", location_raw=""))
    assert not q.eligible(Job(title="ML Engineer", country=None, work_mode="remote", location_raw="Remote - US"))
    assert q.eligible(Job(title="ML Engineer", country=None, work_mode="remote", location_raw="Remote - APAC"))
    assert not q.eligible(Job(title="ML Engineer", country="Germany", work_mode="onsite", location_raw="Berlin"))


def test_lanes():
    m = {"score": 80, "breakdown": {"location": 1, "experience": 1, "skills": 0.8}, "missing_skills": ["Docker"]}
    assert q.lane_for(m) == "direct"
    m["missing_skills"] = ["TensorFlow", "Spark", "LLMs"]
    assert q.lane_for(m) == "tailor"
    m["breakdown"]["experience"] = 0.2
    assert q.lane_for(m) is None


def test_queue_respects_daily_cap_and_is_idempotent(monkeypatch):
    ids = [_job(jid=str(i), fp=f"fp{i}", company=f"Co{i}", url=f"https://x/{i}") for i in range(6)]
    fake = [{"job_id": i, "score": 80, "breakdown": {"location": 1, "experience": 1, "skills": 1},
             "matched_skills": [], "missing_skills": [], "why": []} for i in ids]
    monkeypatch.setattr(q, "match_jobs", lambda profile, limit: fake)
    monkeypatch.setattr(q, "ensure_index", lambda s: None)
    with session_scope() as s:
        assert len(q.build_queue(s, {"skills": []}, cap=4)) == 4
    with session_scope() as s:
        assert q.build_queue(s, {"skills": []}, cap=4) == []  # cap met: nothing more today


def test_marking_applied_sets_a_follow_up(owner):
    jid = _job()
    with session_scope() as s:
        now = utcnow()
        a = Application(job_id=jid, lane="direct", status="queued", score=80, reasons={}, queued_on=q.today_ist(),
                        created_at=now, updated_at=now)
        s.add(a)
        s.flush()
        aid = a.id
    out = owner.patch(f"/api/owner/applications/{aid}", json={"status": "applied"}).json()
    assert out["status"] == "applied" and out["follow_up_at"]
    tracker = owner.get("/api/owner/queue?view=tracker").json()
    assert tracker["applied_total"] == 1 and tracker["items"][0]["id"] == aid
    assert owner.patch(f"/api/owner/applications/{aid}", json={"status": "hacked"}).status_code == 422


def test_tailoring_guard_never_adds_facts():
    out = {"summary": "Engineer with 5 years of Kubernetes.", "skills": ["PyTorch", "Kubernetes", "Python"],
           "experience": [{"id": "e1", "bullets": [{"src": 1, "text": "Shipped AI agents that automate internal workflows."},
                                                   {"src": 0, "text": "Built regression models on 7,385 records (R2 0.99), lifting revenue 30%."}]}],
           "project_order": ["p2", "p1"]}
    r = verify(CV, out)
    assert r["cv"]["summary"] == CV["summary"]  # invented "5 years" + Kubernetes rejected
    assert r["cv"]["skills"][:2] == ["PyTorch", "Python"] and "Kubernetes" not in r["cv"]["skills"]
    bullets = r["cv"]["experience"][0]["bullets"]
    assert bullets[0] == "Shipped AI agents that automate internal workflows."  # honest rewrite kept, reordered
    assert bullets[1] == CV["experience"][0]["bullets"][0]  # "30%" invented: original kept
    assert [p["id"] for p in r["cv"]["projects"]] == ["p2", "p1"]
    assert len(r["warnings"]) == 3


def test_pdf_renders():
    pdf = render(CV)
    assert pdf.startswith(b"%PDF") and len(pdf) > 1000


def test_queue_skips_stale_roles(monkeypatch):
    old = _job(first_seen_at=utcnow() - timedelta(days=30), last_seen_at=utcnow())
    fake = [{"job_id": old, "score": 90, "breakdown": {"location": 1, "experience": 1, "skills": 1},
             "matched_skills": [], "missing_skills": [], "why": []}]
    monkeypatch.setattr(q, "match_jobs", lambda profile, limit: fake)
    monkeypatch.setattr(q, "ensure_index", lambda s: None)
    with session_scope() as s:
        assert q.build_queue(s, {"skills": []}, cap=5) == []

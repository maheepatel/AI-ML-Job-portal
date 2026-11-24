"""Outreach signals: headline parsing, hiring-intent detection, post filters and contact routes."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from gradient.api.owner import email_guesses
from gradient.config import settings
from gradient.db import init_db, session_scope, utcnow
from gradient.models import FundingEvent, HiringPost, Outreach, Person
from gradient.signals.parse import company_from, is_hiring_post, parse_funding
from gradient.signals.run import _upsert_funding


@pytest.mark.parametrize("headline, company, rnd, usd", [
    ("AI startup Humyn Labs raises $47 million in Series A funding round - Business Standard", "Humyn Labs", "series-a", 47e6),
    ("Lemonpeel Raises $1 Mn In Pre-Seed Round Led By Shastra VC - BW Disrupt", "Lemonpeel", "pre-seed", 1e6),
    ("Security Startup Matters.AI raises ₹115 crore pre-series A funding - ET", "Matters.AI", "pre-series-a", 115e7 / 84),
    ("Rahul Dravid-backed Disseqt AI bags $8 million seed - Inc42", "Disseqt AI", "seed", 8e6),
    ("Startup Foo raises $500,000 seed", "Foo", "seed", 5e5),
])
def test_funding_headlines(headline, company, rnd, usd):
    r = parse_funding(headline)
    assert r and r["company"] == company and r["round"] == rnd
    assert abs(r["amount_usd"] - usd) < 1e5


@pytest.mark.parametrize("headline", [
    "Exclusive: Bengaluru-based Zeta raises $30M Series B",          # later stage
    "Spend management platform Payhawk announces $280M raise",       # unlabelled and big
    "Israeli startup raises $11 million Seed - CTech",               # no name
    "Video Production Platform raises pre-seed",                     # descriptor, no name
])
def test_funding_headlines_rejected(headline):
    assert parse_funding(headline) is None


def test_company_names():
    assert company_from("Riyadh 009") is None
    assert company_from("UK AI-powered legal software start-up Perry AI") == "Perry AI"


def test_hiring_intent():
    assert is_hiring_post("We're hiring an ML engineer in Bengaluru!")
    assert not is_hiring_post("Hiring a data scientist won't fix bad data")  # no one is hiring here
    assert not is_hiring_post("I'm open to work as an ML engineer")
    assert not is_hiring_post("We are hiring a barista")  # not AI/ML


@pytest.fixture(autouse=True)
def clean():
    init_db()
    with session_scope() as s:
        for m in (Outreach, Person, FundingEvent, HiringPost):
            s.execute(delete(m))
    yield


def _post(pid, handle, text, likes=0, hours_ago=2):
    now = utcnow()
    return HiringPost(source="bluesky", post_id=pid, url=f"https://bsky.app/{pid}", author=handle, author_handle=handle,
                      author_url="", text=text, likes=likes, links=[], skills=[], posted_at=now - timedelta(hours=hours_ago),
                      fetched_at=now)


def test_posts_filters_bots_seniors_likes_and_age():
    with session_scope() as s:
        s.add_all([
            _post("1", "alice.bsky.social", "We're hiring an ML engineer, 1-3 yrs, Bengaluru"),
            _post("2", "datasciencejobs", "Red Hat is hiring a Data Scientist Location: Pune"),
            _post("3", "bob.bsky.social", "We're hiring a Senior ML engineer"),
            _post("4", "carol.bsky.social", "We're hiring an AI engineer", likes=500),
            _post("5", "dan.bsky.social", "We're hiring a data scientist", hours_ago=60),
        ])
    from gradient.api import signals
    from gradient.api.app import app

    signals._CACHE.clear()
    with TestClient(app) as c:
        r = c.get("/api/signals/posts?hours=24&max_likes=100").json()
    assert [p["author_handle"] for p in r["items"]] == ["alice.bsky.social"]
    assert r["hidden"]["bots"] == 1 and r["hidden"]["senior"] == 1


def test_one_row_per_startup_and_best_round_wins():
    now = utcnow()
    base = dict(amount_text=None, amount_usd=None, source="google-news", url="u", headline="h", ai=True,
                one_liner=None, website=None, location=None, yc_slug=None)
    with session_scope() as s:
        _upsert_funding(s, [{**base, "company": "Reversa", "round": "funding", "announced_at": now},
                            {**base, "company": "Reversa", "round": "pre-seed", "announced_at": now - timedelta(hours=1)}],
                        {"reversa": {"slug": "reversa", "website": "https://reversa.ai"}}, now)
    with session_scope() as s:
        rows = s.query(FundingEvent).all()
        assert len(rows) == 1 and rows[0].round == "pre-seed" and rows[0].yc_slug == "reversa"


def test_email_guesses():
    assert email_guesses("Aman Mishra", "unsiloed.ai") == ["aman@unsiloed.ai", "aman.mishra@unsiloed.ai",
                                                           "amanm@unsiloed.ai", "amishra@unsiloed.ai"]
    assert email_guesses("Aman", None) == []


def test_contacts_and_outreach_are_owner_only(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "tok")
    now = utcnow()
    with session_scope() as s:
        e = FundingEvent(company="Acme AI", company_key="acmeai", round="seed", source="yc", url="u", headline="h", ai=True,
                         website="https://www.acme.ai/", announced_at=now, fetched_at=now)
        s.add(e)
        s.add(Person(company_key="acmeai", name="Jane Doe", title="CEO", source="yc", source_url="u", fetched_at=now))
        s.flush()
        eid = e.id
    from gradient.api.app import app

    with TestClient(app) as c:
        assert c.get(f"/api/owner/funded/{eid}/contacts").status_code == 401
        h = {"X-Admin-Token": "tok"}
        contacts = c.get(f"/api/owner/funded/{eid}/contacts", headers=h).json()
        assert contacts["domain"] == "acme.ai" and contacts["people"][0]["emails"][0] == "jane@acme.ai"
        c.post("/api/owner/outreach", headers=h, json={"company": "Acme AI", "person": "Jane Doe", "kind": "funding", "ref_id": eid})
        assert c.get(f"/api/owner/funded/{eid}/contacts", headers=h).json()["people"][0]["contacted"] is True
        log = c.get("/api/owner/outreach", headers=h).json()
        assert log["today"] == 1 and log["target"] == 20

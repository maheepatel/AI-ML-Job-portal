"""API contract checks that the frontend relies on."""

from fastapi.testclient import TestClient
from sqlalchemy import delete

from gradient.api.app import _cache, app
from gradient.db import init_db, session_scope
from gradient.models import Board, Job, ScrapeRun, SourceRun


def test_stats_on_empty_database_are_zero_not_null():
    # A fresh deploy has no jobs yet; null counts crashed the home page (toLocaleString on null).
    init_db()
    with session_scope() as s:
        for model in (SourceRun, Job, ScrapeRun, Board):
            s.execute(delete(model))
    _cache.clear()
    with TestClient(app) as client:
        stats = client.get("/api/stats").json()
    for key in ("open", "companies", "new_4h", "new_24h", "closed_7d", "india", "remote", "verified", "flagged_scams", "boards"):
        assert stats[key] == 0, (key, stats[key])
    assert stats["ticker"] == [] and stats["last_run"] is None

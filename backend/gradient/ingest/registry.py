"""Builds the list of Source instances for a run from the boards table + static sources."""

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import utcnow
from ..models import Board
from .base import Source
from .sources.ats import ATS_TYPES
from .sources.bigtech import Amazon, Microsoft, Workday
from .sources.boards import BOARD_SOURCES
from .sources.linkedin import LinkedInGuest
from .sources.simplify import Simplify

DISABLE_AFTER_FAILURES = 5


def seed_from_yaml(session: Session) -> int:
    """Insert curated boards from companies.yaml that are not in the DB yet."""
    if not settings.companies_file.exists():
        return 0
    data = yaml.safe_load(settings.companies_file.read_text(encoding="utf-8")) or {}
    existing = {(b.ats, b.ident) for b in session.scalars(select(Board))}
    added = 0
    for ats, entries in data.items():
        for e in entries or []:
            if ats == "workday":
                ident, company = f"{e['tenant']}|{e['wd']}|{e['site']}", e.get("company")
            elif isinstance(e, dict):
                ident, company = e["slug"], e.get("company")
            else:
                ident, company = str(e), None
            if (ats, ident) not in existing:
                session.add(Board(ats=ats, ident=ident, company=company, origin="curated", added_at=utcnow()))
                existing.add((ats, ident))
                added += 1
    return added


def add_boards(session: Session, found: set[tuple[str, str]], origin: str, companies: dict | None = None) -> int:
    """Register newly discovered boards (idempotent)."""
    if not found:
        return 0
    boards = {(b.ats, b.ident): b for b in session.scalars(select(Board))}
    existing = set(boards)
    # Heal names of boards known only by slug ("openai") with names seen elsewhere ("OpenAI").
    for key, name in (companies or {}).items():
        b = boards.get(key)
        if b is not None and name and (not b.company or b.company.lower().replace(" ", "") == b.ident.lower().replace("-", "")):
            b.company = name
    new = [(a, i) for a, i in found if (a, i) not in existing and a in (*ATS_TYPES, "workday")]
    for ats, ident in new:
        session.add(Board(ats=ats, ident=ident, company=(companies or {}).get((ats, ident)), origin=origin, added_at=utcnow()))
    return len(new)


def board_source(board: Board) -> Source | None:
    if board.ats == "workday":
        tenant, wd, site = board.ident.split("|")
        src = Workday(tenant, wd, site, board.company or tenant.title())
    elif board.ats in ATS_TYPES:
        src = ATS_TYPES[board.ats](board.ident, board.company)
    else:
        return None
    src.board_id = board.id
    return src


def build_sources(session: Session, only: set[str] | None = None) -> list[Source]:
    sources: list[Source] = [Amazon(), Microsoft(), Simplify("newgrad"), Simplify("internships")]
    sources += [cls() for cls in BOARD_SOURCES]
    if settings.enable_linkedin:
        sources.append(LinkedInGuest())
    for board in session.scalars(select(Board).where(Board.enabled.is_(True))):
        if src := board_source(board):
            sources.append(src)
    if only:
        sources = [s for s in sources if s.name in only or s.key in only]
    return sources

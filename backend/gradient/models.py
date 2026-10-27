from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("source_key", "source_job_id", name="uq_job_source"),
        Index("ix_jobs_status_posted", "status", "posted_at"),
        Index("ix_jobs_status_seen", "status", "first_seen_at"),
        Index("ix_jobs_listing", "status", "duplicate_of", "trust_label"),  # every public query filters on these
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Provenance
    source: Mapped[str] = mapped_column(String(40), index=True)  # greenhouse, linkedin, remotive…
    source_key: Mapped[str] = mapped_column(String(160), index=True)  # greenhouse:celonis
    source_kind: Mapped[str] = mapped_column(String(20))  # ats | bigtech | linkedin | board | community
    source_job_id: Mapped[str] = mapped_column(String(200))
    authoritative: Mapped[bool] = mapped_column(Boolean, default=False)
    fingerprint: Mapped[str] = mapped_column(String(40), index=True)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("jobs.id"), index=True, nullable=True)

    # Content
    title: Mapped[str] = mapped_column(String(300))
    company: Mapped[str] = mapped_column(String(200), index=True)
    company_domain: Mapped[str | None] = mapped_column(String(200), nullable=True)
    url: Mapped[str] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)  # raw content; skip unchanged
    desc_hash: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    location_raw: Mapped[str] = mapped_column(String(400), default="")
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    work_mode: Mapped[str] = mapped_column(String(20), default="unknown")  # remote | hybrid | onsite | unknown
    employment_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    salary_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    salary_currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    salary_period: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Classification
    role_family: Mapped[str] = mapped_column(String(60), index=True)
    ai_score: Mapped[float] = mapped_column(Float, default=0)
    seniority: Mapped[str] = mapped_column(String(20), default="unknown")
    exp_min: Mapped[float | None] = mapped_column(Float, nullable=True)
    exp_max: Mapped[float | None] = mapped_column(Float, nullable=True)
    skills: Mapped[list] = mapped_column(JSON, default=list)

    # Trust
    trust_score: Mapped[int] = mapped_column(Integer, default=50)
    trust_label: Mapped[str] = mapped_column(String(20), default="caution", index=True)
    trust_reasons: Mapped[list] = mapped_column(JSON, default=list)

    # Lifecycle
    status: Mapped[str] = mapped_column(String(10), default="open", index=True)  # open | closed
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    missed_runs: Mapped[int] = mapped_column(Integer, default=0)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    close_evidence: Mapped[str | None] = mapped_column(String(400), nullable=True)
    reopened_count: Mapped[int] = mapped_column(Integer, default=0)


class Board(Base):
    """One employer job board on a supported ATS. Seeded from companies.yaml, grown automatically
    from apply links seen anywhere (LinkedIn, Simplify, HN, boards) and from bulk seed datasets."""

    __tablename__ = "boards"
    __table_args__ = (UniqueConstraint("ats", "ident", name="uq_board"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ats: Mapped[str] = mapped_column(String(30), index=True)  # greenhouse | lever | ashby | workday …
    ident: Mapped[str] = mapped_column(String(200))  # slug, or "tenant|wd|site" for workday
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="curated")  # curated | simplify | yc | auto
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_job_count: Mapped[int] = mapped_column(Integer, default=0)
    last_relevant_count: Mapped[int] = mapped_column(Integer, default=0)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Artifact(Base):
    """Precomputed blobs the web tier loads instead of computing (e.g. the TF-IDF match index,
    built by the scraper so a small web instance never has to fit it)."""

    __tablename__ = "artifacts"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    version: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    data: Mapped[bytes] = mapped_column(LargeBinary)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | partial | failed
    trigger: Mapped[str] = mapped_column(String(20), default="schedule")
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


class SourceRun(Base):
    __tablename__ = "source_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), index=True)
    source_key: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(40))
    ok: Mapped[bool] = mapped_column(Boolean)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched: Mapped[int] = mapped_column(Integer, default=0)
    kept: Mapped[int] = mapped_column(Integer, default=0)
    new: Mapped[int] = mapped_column(Integer, default=0)
    closed: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

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


class Application(Base):
    """The owner's apply pipeline: one row per job queued, tailored, applied or skipped."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), unique=True, index=True)
    lane: Mapped[str] = mapped_column(String(10), default="direct")  # direct | tailor
    status: Mapped[str] = mapped_column(String(12), default="queued", index=True)
    # queued | applied | skipped | interview | offer | rejected | ghosted
    score: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)  # matched/missing skills, why, breakdown
    queued_on: Mapped[str] = mapped_column(String(10), index=True)  # IST date, YYYY-MM-DD (daily cap)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    follow_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tailored: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class HiringPost(Base):
    """A public "we're hiring" social post (Bluesky, Mastodon…). Fresh + low-engagement ones
    are the outreach targets: few people have seen them yet."""

    __tablename__ = "hiring_posts"
    __table_args__ = (UniqueConstraint("source", "post_id", name="uq_hiring_post"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(20))  # bluesky | mastodon
    post_id: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(600))
    author: Mapped[str] = mapped_column(String(200))
    author_handle: Mapped[str] = mapped_column(String(200))
    author_url: Mapped[str] = mapped_column(String(600))
    text: Mapped[str] = mapped_column(Text)
    likes: Mapped[int] = mapped_column(Integer, default=0)
    reposts: Mapped[int] = mapped_column(Integer, default=0)
    replies: Mapped[int] = mapped_column(Integer, default=0)
    links: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FundingEvent(Base):
    """A startup that just raised (news headline) or joined a YC batch."""

    __tablename__ = "funding_events"
    __table_args__ = (UniqueConstraint("company_key", name="uq_funding_company"),)  # one row per startup: its latest raise

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    company_key: Mapped[str] = mapped_column(String(200), index=True)  # lowercase alnum
    round: Mapped[str] = mapped_column(String(40))  # pre-seed | seed | series-a | yc-<batch> | funding
    amount_text: Mapped[str | None] = mapped_column(String(60), nullable=True)
    amount_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    one_liner: Mapped[str | None] = mapped_column(String(500), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source: Mapped[str] = mapped_column(String(40))  # google-news | techcrunch | yc | …
    url: Mapped[str] = mapped_column(String(1000))
    headline: Mapped[str] = mapped_column(String(500))
    ai: Mapped[bool] = mapped_column(Boolean, default=False)
    yc_slug: Mapped[str | None] = mapped_column(String(200), nullable=True)
    announced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Person(Base):
    """A public decision-maker at a funded startup (founders from their YC company page)."""

    __tablename__ = "people"
    __table_args__ = (UniqueConstraint("company_key", "name", name="uq_person"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_key: Mapped[str] = mapped_column(String(200), index=True)
    name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    x_url: Mapped[str | None] = mapped_column(String(400), nullable=True)
    source: Mapped[str] = mapped_column(String(40))  # yc
    source_url: Mapped[str] = mapped_column(String(600))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Outreach(Base):
    """The owner's cold-email log (20/day target)."""

    __tablename__ = "outreach"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company: Mapped[str] = mapped_column(String(200))
    person: Mapped[str] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(300), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # funding | post | job
    ref_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # funding_events.id / hiring_posts.id / jobs.id
    status: Mapped[str] = mapped_column(String(12), default="sent")  # sent | replied | call | no-reply | bounced
    sent_on: Mapped[str] = mapped_column(String(10), index=True)  # IST date
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

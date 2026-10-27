# Gradient — architecture

Gradient is an AI/ML job aggregator for candidates with 0–4 years of experience. It pulls
openings from employer applicant-tracking systems (ATS), big-tech career APIs, public job
boards and LinkedIn's public guest listings, then normalises, classifies, de-duplicates,
trust-scores and lifecycle-tracks every posting.

## Guiding decisions

| Decision | Choice | Why |
|---|---|---|
| Primary data path | **Structured JSON endpoints behind career portals** (Greenhouse, Lever, Ashby, Workable, Recruitee, SmartRecruiters, Workday CXS, Amazon, …) | These are the employer's own source of truth: real posting dates, stable IDs, and a complete list, which is what lets us *prove* a job closed. HTML scraping is the fallback, not the default. |
| Fetch layer | **Scrapling** (`AsyncFetcher`, curl_cffi under the hood) | Fast async HTTP with browser-grade TLS fingerprints plus a CSS/XPath parser for HTML sources (LinkedIn guest cards, JSON-LD career pages, liveness checks). One client for every source. |
| Walls | Public data only. No login scraping, no CAPTCHA solving, no Cloudflare challenge bypass. A 429/999 means back off. | Keeps the platform legally defensible and the pipeline stable. Sites that hide behind bot walls (Naukri, Wellfound, Instahyre) are covered indirectly, because the same companies post on their own ATS, which we read directly. |
| Storage | SQLAlchemy 2.0. SQLite (WAL) locally, Postgres in production through `DATABASE_URL` | Zero-setup dev, same code in prod. |
| API | FastAPI | Typed, fast, auto OpenAPI docs at `/api/docs`. |
| Frontend | Vite + React + TypeScript SPA, served by the API in production | One deployable unit. Design language: Jobright (from `voltagent/awesome-design-md`). |
| Scheduling | Separate `worker` process (APScheduler), with GitHub Actions cron as an alternative | The scraper never blocks the API. Either one can be scaled or replaced independently. |
| Matching | Explainable hybrid scorer (skills taxonomy + TF-IDF cosine + experience fit + location + freshness). No paid LLM needed. | Fast, free, deterministic, and every score explains itself. An embedding model can be swapped into `matching.py` later. |

## System diagram

```
            ┌────────────────────────── worker (every 4h) ──────────────────────────┐
            │                                                                        │
 sources ──▶│ fetch (Scrapling, per-host throttle) → normalise → classify → dedupe   │
 registry   │        → trust-score → upsert → lifecycle (close/reopen) → liveness    │
 (YAML)     └──────────────────────────────┬─────────────────────────────────────────┘
                                           ▼
                                   SQLite / Postgres
                                           ▲
                    FastAPI  /api/jobs /api/stats /api/match /api/runs …
                                           ▲
                         React SPA: Home · Jobs · For Me · Closed · Status
```

## Pipeline stages (`backend/gradient/ingest/pipeline.py`)

1. **Fetch.** Every source *instance* (for example `greenhouse:celonis` or `linkedin:ml-india`)
   runs concurrently under a global semaphore and a per-host rate limiter. A failed source is
   recorded and **its jobs are left untouched**, so an outage can never mass-close postings.
2. **Normalise** (`domain/normalize.py`): location → city/country/work-mode, salary parsing,
   HTML → text, and a fingerprint `sha1(company|title|city)` for cross-source de-duplication.
3. **Classify** (`domain/classify.py`):
   - AI/ML relevance score (title signals are strong, description signals are weaker) → role family
     (ML Engineer, Data Scientist, AI Engineer / LLM, Research, MLOps, Computer Vision, NLP,
     Data/Analytics adjacent, AI Product Engineering).
   - Experience extraction (`2-4 years`, `3+ yrs`, `minimum 5 years`) plus title seniority
     (intern / entry / junior / mid / senior+). Senior, staff, lead and manager roles, and
     anything requiring at least 5 years, are dropped.
4. **De-duplicate.** The same fingerprint from several sources collapses into one canonical
   job. Source priority is ATS > big-tech API > LinkedIn > boards. Listing on several sources
   raises trust.
5. **Trust score** (`domain/trust.py`): 0–100 with itemised reasons → `verified`,
   `likely_genuine`, `caution` or `likely_scam`. Scams are hidden by default.
6. **Upsert.** `posted_at` is the source's own publish time. `first_seen_at` is when we first saw
   the job. `last_seen_at` / `last_verified_at` record each later sighting.
7. **Lifecycle** (closed detection):
   - *Authoritative sources* (full ATS listings): a job missing from **2 consecutive successful
     runs**, or missing once with a 404 on its URL, → `closed` / `removed_from_source`.
   - *Search-based sources* (LinkedIn, boards, Workday searches): absence proves nothing, so
     those jobs rely on URL liveness checks and expiry.
   - `validThrough` / application deadline in the past → `closed` / `deadline_passed`.
   - Not verified for 30 days → `closed` / `expired`.
   - A closed job that reappears → reopened (history kept).
8. **Liveness** (`ingest/liveness.py`): each run re-checks a rolling slice of open jobs, oldest
   check first, so every job is verified at least daily. A 404/410, a redirect off the job page,
   or "no longer accepting applications" text → closed with the evidence stored.

## Scheduling

Full run every **4 hours** (00, 04, 08, 12, 16, 20 IST). ATS boards change slowly and
early-career roles fill in days, not hours, so a 4h freshness window keeps "posted X hours ago"
honest. It is also polite to every API. Sources with stricter limits declare `min_interval_hours`
(Remotive asks for at most 4 calls a day, so it gets 6h); the scheduler skips them until due.

## Data model (`backend/gradient/models.py`)

- `jobs`: one row per (source_key, source_job_id), plus fingerprint, canonical link
  (`duplicate_of`), classification, trust, lifecycle timestamps and close evidence.
- `scrape_runs` / `source_runs`: every run and every source within it (fetched, kept, new,
  closed, error, duration). These feed the Status page and alerting.

## Scaling path

| Pressure | Next step |
|---|---|
| > 100k jobs or slow search | Postgres + `tsvector` full-text index, or Meilisearch |
| Many more sources | Split fetch into a queue (Redis + RQ/Arq), one worker per source family |
| Multi-user "For Me" | Accounts + saved profiles + email/Telegram alerts on new matches |
| Better matching | Sentence-embedding model (bge-small) behind the same `score_job` interface |
| JS-only career sites | Scrapling `StealthySession` (headless browser) for sites that render client-side, still without challenge bypass |

## Adding a source

1. For a company on a supported ATS, add one line to `backend/data/companies.yaml`
   (`scripts/discover_ats.py <slugs…>` finds which ATS a company uses).
2. For a new source type, implement `Source.fetch()` in `ingest/sources/`, returning `RawJob`s,
   and register it in `ingest/registry.py`.

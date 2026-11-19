# Gradient

**Every AI/ML job on the internet, for freshers to 4 years of experience.**

Gradient sweeps employer career systems, big-tech careers APIs, LinkedIn's public job pages
and public job boards twice a day. It keeps only AI/ML roles you can actually get, shows
exactly how long each one has been live, flags scams with an explainable trust score, moves
filled or removed roles to *Closed*, and ranks everything against your résumé.

Architecture and design decisions: [ARCHITECTURE.md](ARCHITECTURE.md).

## Pages

| Route | What it does |
|---|---|
| `/` | Live stats, latest-openings ticker, fresh verified roles |
| `/jobs` | Search + filters (role, experience band, location, posted within, trust, source) with a detail panel |
| `/jobs/:id` | Full posting, live-since timeline, trust breakdown, "also listed on" |
| `/for-me` | Roles ranked against the owner's résumé, or any uploaded PDF (parsed in memory, never stored) |
| `/closed` | Roles that closed, with the evidence and how long they stayed open |
| `/status` | Pipeline health, per-source counts, closure and trust rules |
| `/api/docs` | OpenAPI docs for the public read API |

## Sources

- **Employer ATS (authoritative):** Greenhouse, Lever, Ashby, Workable, Recruitee, SmartRecruiters, Personio, Teamtailor, BambooHR, Breezy, JazzHR, Rippling. The registry grows on its own: any ATS link seen in any listing registers that company's whole board. Curated boards by region (US, EU, UK, India, Asia, Australia, Africa, LatAm) live in `backend/data/companies.yaml`.
- **YC startups:** the ATS boards of YC companies (`backend/data/yc_boards.yaml`, plus boards found each run by crawling a rotating slice of YC company websites from the yc-oss directory), and YC's own job board on ycombinator.com (role pages plus a rotating slice of AI/ML-tagged hiring companies, kept under the site's rate limit).
- **Big tech:** Amazon Jobs, Microsoft Careers, Workday tenants (NVIDIA, Adobe, Intel, Salesforce, Cisco …) and Oracle Recruiting Cloud sites (JPMorgan, American Express, BNY, Nokia, Dell …).
- **Regional:** MyCareersFuture (Singapore), Get on Board (LatAm), Habr Career (Russia/CIS), Arbeitnow (EU).
- **Aggregators:** LinkedIn public guest listings, SimplifyJobs new-grad and internship lists, Hacker News "Who is hiring", Remotive, RemoteOK, Himalayas, Jobicy, Working Nomads.

Only public data is read. There is no login scraping and no CAPTCHA or bot-wall bypass. Sites behind bot
walls (Naukri, Wellfound, Instahyre) are covered indirectly, because their employers post on their own ATS, which
Gradient reads directly.

## Run locally

```bash
python -m venv .venv && .venv/Scripts/pip install -r backend/requirements-dev.txt   # Windows
cd frontend && npm install && cd ..
```

```bash
cd backend
../.venv/Scripts/python -m gradient.cli profile "path/to/resume.pdf"   # powers /for-me
../.venv/Scripts/python -m gradient.cli scrape                          # one full sweep (~10-20 min first time)
../.venv/Scripts/python -m gradient.cli serve                           # API on :8270
```

```bash
cd frontend && npm run dev                                              # UI on :5270 (proxies /api)
```

Keep it fresh with the scheduler (sweeps at 00/04/08/12/16/20 IST, plus a daily backup):

```bash
cd backend && ../.venv/Scripts/python -m gradient.cli worker
```

## Production

Step-by-step hosting guide (Fly.io, Railway, Render, VPS, Oracle Free): [DEPLOY.md](DEPLOY.md).


`docker compose up -d --build` runs the API (serving the built SPA) and the worker from one image,
sharing a SQLite volume. For managed hosting, point `GRADIENT_DATABASE_URL` at Postgres for both processes.
Alternatively, skip the worker and enable `.github/workflows/scrape.yml` (cron twice a day, 06:00 and 18:00 IST).

## Growing coverage

```bash
python scripts/discover_ats.py stripe razorpay sarvam --merge   # which ATS does a company use?
python scripts/expand_registry.py                               # bulk-probe YC companies
```

Add a new source type by implementing `Source.fetch()` in `backend/gradient/ingest/sources/` and registering it
in `ingest/registry.py`. After changing classification rules, bump `CLASSIFIER_VERSION` in `ingest/pipeline.py` so
stored jobs are re-processed on the next sweep.

## Tests

```bash
cd backend && ../.venv/Scripts/python -m pytest -q
```

# Launch Gate — Gradient — 2026-10-22

Stack: FastAPI + Vite/React SPA, one Docker container on Fly.io (`bom`): API + embedded 4-hourly scheduler, SQLite on a volume. No auth, payments, email or AI provider. The only write path is the stateless résumé upload.
Deployed: not yet (pre-deploy gate). Verdict: **GO for first deploy**. 0 blockers. Follow-ups below are dated, non-blocking.

| # | Check | Status | Evidence / next step |
|---|---|---|---|
| 1 | Keys hidden | PASS | Secret-pattern grep over source + `frontend/dist`: 0 hits. No `VITE_*` secret vars. `.env*` gitignored, 0 env files tracked. The app has no secrets at all. |
| 2 | Leaked keys rotated | PASS | Repo has 0 commits. No history to leak from, no keys exist. |
| 3 | Rate limits | FIXED | Was keyed on the socket IP, which behind Fly's proxy is the proxy itself, so all users would share one bucket. Now keyed on `Fly-Client-IP` when `GRADIENT_TRUST_PROXY_HEADERS=true` (set in `fly.toml`). Verified: client A gets 240×200 then 429, client B stays 200. Upload limit 6/min (6×422 on a junk PDF, then 429). Idle buckets are pruned. |
| 4 | Auth on every route | N/A | No accounts or private routes. Inventory: GET health, jobs, jobs/{id}, stats, runs, match, docs; POST match/resume. All public and read-only, the upload is stateless. |
| 5 | Data isolation | N/A | No user-owned rows. Uploaded PDFs are parsed in memory and never written. |
| 6 | Server validation | FIXED | All params have pydantic `Query` constraints. Added a 200-char cap on `q` (300 chars → 422). Probes: page_size=999 → 422, bad status → 422, non-PDF → 415, 6 MB → 413, SQL-injection-style `q` → 200 (parameterized). PDF parsing now runs in a worker thread with a 20 s timeout and a 6-page cap, so a hostile PDF can't stall the event loop. |
| 7 | AI spend cap | N/A | No paid AI. Matching is local scikit-learn. |
| 8 | No stack traces | PASS | Error bodies for bad id / bad type / bad page: 0 matches for `Traceback\|File "\|.py\|sqlalchemy\|sqlite`. Every response carries `X-Request-ID`, and 500s return `{detail, request_id}`. |
| 9 | Error tracking | FAIL (follow-up) | No Sentry yet. Interim: `fly logs` plus the Fly health check on `/api/health`. Add a Sentry DSN within 2 weeks of launch. |
| 10 | Backup + tested restore | PASS | Daily snapshot at 03:30 IST to `/data/backups` (14 kept), plus Fly's daily volume snapshots. Local restore tested: integrity `ok`, row counts match. Repeat the restore once in production (ROLLBACK.md). |
| 11 | 404/500 pages | FIXED | Unknown URL → real **404** with a branded page. Added a React error boundary ("Something broke" + home link) so render errors no longer white-screen. |
| 12 | Cheap Android | PASS | At 360×640, all 7 key pages have `scrollWidth == 360` (no horizontal scroll). Search input is now 16px (no iOS zoom). Chips ≥38px and small buttons 40px. |
| 13 | < 3 s load | FIXED | `/api/stats` was 1.9 s. Merged ~10 COUNTs into one aggregate pass, added a listing index, and a 60 s response cache. Uncached now 0.07–0.15 s, warm ~10 ms. JS bundle 65 KB gzipped. Mobile Lighthouse on the live URL still to run after deploy. |
| 14 | Meta + OG | FIXED | Server HTML has title, description, og:title/description/url/image, 1200×630 `og.png` (200, image/png, 34 KB), `twitter:card=summary_large_image`, favicon. URLs assume `gradient-jobs.fly.dev`; update if the app name differs. |
| 15 | Privacy + terms | PASS | `/privacy`, `/terms` linked in the footer. Legal review → USER-ACTION. |
| 16 | Analytics funnel | FAIL (follow-up) | None yet. Add Plausible/PostHog (landing → search → job view → apply click → résumé match) within 2 weeks. |
| 17 | Signup/payment/reset E2E | N/A | No signup, password or payment flows. |
| 18 | Email deliverability | N/A | The site sends no email. |
| 19 | Contact path | USER-ACTION | Set `VITE_CONTACT_EMAIL` (build arg) to the address you want public. Until then the footer's Contact falls back to the privacy page. |
| 20 | Rollback plan | FIXED | `ROLLBACK.md` rewritten for Fly: `fly releases` → `fly deploy --image`, kill switches via `fly secrets set`, restore commands, decision rule. |

## Blockers
None.

## User actions (exact steps)
1. Create a Fly.io account (card required) and log in from this machine (see the chat walkthrough).
2. Choose the public contact email → I'll pass it as `VITE_CONTACT_EMAIL` at deploy.
3. Legal review of `/privacy`, `/terms`, and of LinkedIn guest-page use (disable with `fly secrets set GRADIENT_ENABLE_LINKEDIN=false` if unsure).

## Nice-to-have
- Sentry (#9) and analytics (#16) within 2 weeks.
- Mobile Lighthouse run on the live URL (#13).
- A sweep runs inside the API process: CPU-heavy classification can briefly slow API responses during the ~15 min sweep. If it shows, split the worker into its own Fly machine with Postgres (ARCHITECTURE.md → scaling path).

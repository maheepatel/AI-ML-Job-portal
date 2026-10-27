# Launch checklist: Gradient

Tier: public app with file upload (no accounts, no payments, no paid AI calls)
Stack: FastAPI + Vite/React · Docker on Fly.io (bom), single container · SQLite → Postgres · no auth · no payments · no email · no LLM (local TF-IDF)

Tick with *where* it lives. `launch-gate` re-verifies every tick before launch.

## Security
- [x] 1. No secrets exist. Config comes from env via pydantic-settings, `.env*` is gitignored, and nothing secret has a `VITE_` prefix: `backend/gradient/config.py`, `.gitignore`, `backend/.env.example`
- [ ] 2. No key ever committed: no commits yet. Run a secret scan before the first push.
- [x] 3. Rate limits: 240 req/min per IP on the API, 6/min on résumé upload: `backend/gradient/api/app.py` (`rate_limit`, `_request_context`). Keyed on `Fly-Client-IP` behind the proxy (verified 2026-10-22). In-memory, so move it to Redis if you run more than one API instance.
- [x] 4. N/A: no private routes and no accounts. The API is read-only apart from the stateless résumé match.
- [x] 5. N/A: no user-owned rows. Uploaded résumés are parsed in memory and never stored.
- [x] 6. Validation: FastAPI/pydantic `Query` constraints on every parameter. Uploads are capped at 5 MB with a PDF magic-byte check: `backend/gradient/api/app.py`
- [x] 8. Generic `{"detail","request_id"}` on 500s with full detail in server logs, and an `X-Request-ID` header on every response: `backend/gradient/api/app.py`

## Cost & ops
- [x] 7. N/A: no paid AI calls. Matching is local scikit-learn.
- [ ] 9. Error tracking: add Sentry (backend + frontend) once a deploy target exists.
- [x] 10. Daily SQLite snapshot at 03:30 IST, keeping 14. Restore tested 2026-10-22: `backend/gradient/backup.py`, `ROLLBACK.md`
- [x] 20. `ROLLBACK.md` written. Last-known-good deploy gets recorded on first deploy.

## Experience
- [x] 11. Branded 404 page with a real 404 status, a React error boundary, and an error state on every data view: `frontend/src/main.tsx`, `backend/gradient/api/app.py` (`SPA_ROUTES`)
- [x] 12. No horizontal scroll at 360×640 on all key pages, 16px inputs, 38-40px tap targets (verified 2026-10-22). A real-device check is still worthwhile.
- [ ] 13. Mobile LCP: measure after deploy. JS bundle is small (React + router only).
- [x] 14. Title, description, OG and Twitter tags, 1200×630 `og.png`, favicon: `frontend/index.html`, `frontend/scripts/make_og.py`

## Trust & growth
- [x] 15. `/privacy` + `/terms` linked in the footer: `frontend/src/pages/Legal.tsx`. Needs legal review.
- [ ] 16. Analytics funnel (landing → search → job view → apply click → résumé match): add Plausible/PostHog on deploy.
- [x] 18. N/A: the site sends no email.
- [ ] 19. Contact path: set `VITE_CONTACT_EMAIL` at build time (footer and legal pages read it).

## Critical flows
- [x] 17. N/A: no signup, password or payment flows. The key flows (search, filter, job detail, résumé match) were verified in the browser on 2026-10-22.

## Not yet verified
- [ ] `docker build` hasn't run locally (Docker Desktop off). Fly's remote builder is the first real build. Single-container mode was verified without Docker (empty disk → seed copy → scheduler up → data served).

## You need to do (dashboards / money / legal / DNS)
- [ ] Pick a host (VPS with Docker, or Render/Fly) and a domain. Point DNS and enable HTTPS.
- [ ] Decide the public contact email and set `VITE_CONTACT_EMAIL`.
- [ ] If using Postgres: create the DB, set `GRADIENT_DATABASE_URL`, and enable automated backups.
- [ ] Legal review of privacy/terms, and of LinkedIn guest-page use (disable with `GRADIENT_ENABLE_LINKEDIN=false` if unsure).

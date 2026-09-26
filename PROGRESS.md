# Progress

## 2026-09-26 — Local invoice extraction slice verified

- Added text-layer PDF upload, S3-compatible storage, content-hash deduplication, tenant-scoped document and extraction tables, and a transactional outbox worker with retry and stale-claim recovery.
- Added a working inbox that shows extracted fields with PDF evidence. The extraction provider is a deterministic mock by default; an optional OpenRouter adapter requests structured JSON and rejects fields without matching text evidence.
- Added a fictional PDF sample, a 20-invoice synthetic evaluation, and an ADR documenting direct Postgres outbox polling before Redis queue dispatch.
- Local checks passed: backend Ruff, mypy, seven tests; frontend ESLint, TypeScript, two tests, production build; live API smoke; browser login/upload/extraction/logout. `make eval` wrote a report with 100% exact field match and 100% evidence grounding for the **generated mock-only invoices**. No live model accuracy claim is made.
- The user-shared OpenRouter key was not used or stored. Live OpenRouter extraction and evaluation still need a newly issued key in ignored local environment variables.
- Public staging, human review/approval, scanned-PDF support, and actions remain outstanding. CI for this change is pending the GitHub push.

## 2026-09-26 — Published to GitHub and verified

- Published the Phase 0 repository at https://github.com/Abhinavsuri90/opspilot with eight focused commits.
- Normalized login identifiers and kept unknown-account password checks on the Argon2 path.
- Standardized API error envelopes and request IDs, synchronized frontend session state, and verified logout in the browser.
- Added regression coverage for forged sessions and transaction-scoped tenant isolation, plus a live HTTP smoke check in CI.
- Replaced README placeholders with an actual Phase 0 dashboard screenshot and a clear feature status table.
- `make lint typecheck test smoke` and the browser smoke test pass locally. The first GitHub Actions run completed successfully.
- Railway staging remains outstanding; project and access details are needed.

## 2026-09-26 — Phase 0 local foundation verified; staging pending

- Added a Python 3.12 FastAPI API with health, readiness, login, logout, current-session endpoints, and request IDs.
- Added Postgres migrations for organizations, users, memberships, workflow configs, audit events, tenant RLS, and append-only audit grants.
- Added fictional Northwind and Contoso seed data, tenant isolation tests, a smoke test, and an ADR.
- Added a Next.js login and empty dashboard shell, a typed API client generated from OpenAPI, Docker Compose, Makefile, and CI.
- `make up` builds and starts the local stack, migrates the database, and seeds demo users.
- `make lint typecheck test smoke` passes: two backend tests, two frontend tests, and the live API smoke test. `make smoke-ui` passes in headless Chrome.
- Integration tests verify login, admin/reviewer access, tenant read and write isolation, and append-only audit permissions.
- The running API container has no owner database credential. A separate one-off `admin` service runs migrations and seeding.
- Railway staging deployment remains outstanding. No production work has begun.
- The original MinIO image reference no longer pulls. Local Compose now uses Adobe S3Mock; see ADR 002.

Next: configure Railway staging, deploy the web and API, run migrations and private demo seeding, then run the smoke test against the staging URL. Obtain the project/access details first.

# Progress

## 2026-09-26 — Company demo and operations console

- Replaced the placeholder web experience with a shared responsive shell, a document-driven Dashboard, a searchable/filterable Inbox, and a read-only Admin member directory. TanStack Query remains the data layer. Review editing, approval, actions, and settings are still unimplemented.
- Added four fictional text-layer invoices, two each for Northwind and Contoso, plus a browser check that uploads all four and verifies both directions of document isolation and the reviewer/admin access boundary.
- Updated the local demo guide and screenshots. The local mock-provider checks passed: 41 API tests, 16 web tests, Ruff, mypy, ESLint, TypeScript, production web build, browser happy path and error states, tenant demo, and a 390-pixel responsive check. The containers were stopped afterward; local volumes remain.
- Live OpenRouter accuracy and public deployment remain unverified.

## 2026-09-26 — Local walkthrough and complete route review

- Rebuilt the local mock-provider stack and verified the browser at `http://localhost:3300/login`: sign-in, fresh PDF upload, extraction with evidence, retry UI, and logout passed. Refreshed the real dashboard and inbox screenshots in `docs/assets/`.
- Audited all 10 explicit API routes. The Docker/Postgres suite passed 41 tests, including successful responses and unauthenticated, forbidden, malformed ID, invalid upload, quota/configuration, oversized request, rate-limit, and storage-error paths. Ruff and strict mypy passed.
- The web suite passed 16 tests, lint, typecheck, and production build. A browser error-state run passed login, upload, list/detail, retry, permissions, session expiry, and long-list layout cases. The same-origin proxy now forwards `Sec-Fetch-Site` to the API.
- Fixed the Inbox's excessive blank space with long document lists and made login input normalization/messages clearer. Added the browser error-state run to CI for subsequent pushes.
- Removed five empty future customer-engagement Markdown templates and repaired their spec/design references. Kept the substantive design, ADR, deployment, handoff, and demo documents.
- Public Railway deployment, OCR, review edits/approval, actions, and live OpenRouter accuracy remain unverified or unimplemented.

## 2026-09-26 — Second deployment and security review

- Confirmed that the failed GitHub notification for `69ebf1b` was historical; its Python import issue was fixed in `45f4f3e`, whose three CI jobs passed. Added a fourth, full browser smoke job for the next push.
- Bounded raw API upload requests before multipart parsing, enforced bounded S3 reads and document hash/size checks in the worker, tightened production origin validation, added a shared Postgres login attempt limit and migration, and rotated worker tenant selection to avoid starvation.
- Cleared browser query data across login/logout/session expiry, gated protected invoice queries on a valid session, aligned upload controls with role permissions, clarified upload/rate-limit errors, and improved keyboard focus visibility.
- Pinned the Python 3.12 runtime dependency set, added `pip check` and `pip-audit` in CI, and added a Compose browser smoke job. The local runtime audit and the full frontend npm audit reported no known advisories at review time. The [first four-job GitHub run](https://github.com/Abhinavsuri90/opspilot/actions/runs/36233730171) passed at commit `217545a`.
- Local checks passed after the fixes: 29 Postgres API tests, Ruff, strict mypy, 12 web tests, web lint/typecheck/build, the full Compose startup, API smoke, fresh-invoice browser smoke including retry/logout, and the synthetic mock eval. The mock eval's 100% exact match and grounding apply only to generated invoices, not live AI accuracy.
- Public deployment remains unverified. A Railway project/access, Postgres and Bucket setup, migration-first rollout, hosted browser smoke, backups/alerts, and a rotated OpenRouter key for optional live-model testing remain the next work.

## 2026-09-26 — Deployment readiness and full local review

- Reviewed the API, worker, web, Docker images, Compose startup, Railway options, and public demo path. Findings and remaining gates are in `docs/deployment-readiness-review.md`.
- Fixed same-origin auth proxy, runtime API URL, Railway-compatible S3 addressing and Postgres URLs, schema-aware readiness, release image port/nonroot behavior, local-only support ports, ordered migration startup, worker lease races, invalid PDF intake, a document quota, and bounded manual retry.
- Improved Inbox upload errors, hosted sample download, extraction polling, failed-job retry, and browser smoke so each run verifies a fresh extraction.
- Local verification passed: backend Ruff/mypy/24 Postgres tests, frontend lint/typecheck/10 tests and production image build, API smoke, browser login/upload/extraction/retry/logout, release API image import as UID 10001, and synthetic mock eval. Production npm audit reported zero advisories at the time of review.
- Public Railway deployment and live OpenRouter evaluation are still unverified. They need a Railway project, bucket, secrets, migration/bootstrap job, rotated model key, and public URL smoke test.

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

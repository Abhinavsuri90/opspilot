# Progress

## 2026-09-27 — Review fixes and Phase 2: validation, confidence and corrections

- Full project evaluation before further work: 5.5/10 overall (engineering about 7, spec completeness about 3). All check suites were green; the review found twelve concrete bugs and a test-data leak that had brought the local Northwind organization to 99 of 100 documents.
- Fixed the review findings: Postgres tests now clean up after themselves (Northwind back to 3 documents); the API derives the client address from the rightmost forwarded entry only when the peer is a private network, and throttles login per address as well as per account; request IDs are logged on 500 responses; the admin-versus-admin membership deadlock is gone; `ENVIRONMENT` defaults to production; extraction and upload parsing run under hard timeouts; missing indexes were added; dead code and hand-built error envelopes were removed.
- Phase 2 backend: versioned workflow configuration with typed fields, thresholds and cross-field rules in a parsed rule grammar (no `eval`); a six-signal confidence engine (ADR 006); immutable extracted fields with confidence, status, signals and reasons; append-only field corrections; review tasks with an SLA; a filterable review queue; a per-document timeline; approval gated on corrected fields with derived verified money; a `validating` step and threshold-based auto-approval behind an opt-in policy. Migration 0006. Prompts moved to `apps/api/app/prompts/` with a version id. Evals now report flagging precision and recall against `evals/baseline.json`.
- Frontend fixes: no more endless polling of failed lookups, filter-aware inbox states, cross-tab sign-in no longer signs the other tab out, cookie-presence middleware, forwarded headers and 405 handling in the proxy, one shared session hook and error helper, Zod registration schema, the invoice workspace split into focused components, and jsdom unit tests.
- Verification: Ruff and strict mypy clean; 179 API tests (was 80) including Postgres concurrency, lease, timeout and throttle cases; 54 web tests (was 16); ESLint, TypeScript and production builds; API smoke; all five browser suites including the full fresh-company workflow; the extraction eval against its baseline. An independent review of the backend diff found no tenant-isolation or authorization gaps and listed follow-ups (migration backfill under RLS on non-superuser owners, throttle behavior on shared addresses, configurable trusted proxies, timeout versus lease bound, money magnitude bounds) that are being fixed next.
- Follow-up fix pass from the independent review: migration 0007 re-runs the audit backfill with row security disabled so non-superuser owners cannot silently skip rows, records whether verified money was reviewer-entered or derived (reopen clears only derived money), charges the per-address login budget only after failed credentials, makes trusted proxy ranges configurable, keeps the extraction timeout under the lease, caps concurrent PDF parsing with a semaphore and daemon threads, bounds money magnitude, rejects nested-quantifier regexes in field specs, scopes flagged counts to the latest run, and adds a Postgres end-to-end review test. 210 API tests. CI now retries base-image pulls and runs the runtime import check in development mode.
- Phase 2 frontend: a filterable review queue with SLA chips and flagged counts, and the keyboard-first split view at `/review/[id]`: PDF on the left with evidence highlight rectangles, per-field confidence meters with threshold markers, status chips, plain-language reasons and signal tables, inline typed edits with the API's validation reason shown in place, rule results, a decision panel gated on flagged fields, discussion, access, timeline and questions tabs, and J/K/Enter/E/A/R/? shortcuts with a focus-trapped shortcuts dialog. Inbox shows a confidence summary and links into review; dashboard shows auto-approved counts. The API error parser now surfaces specific validation messages on every page. 79 web tests; a new browser acceptance script (`make smoke-review`) runs in CI alongside the six existing suites.
- Phase 3 backend: migration 0008 adds organization settings (kill switch, shadow mode), per-type action policies, connector instances with Fernet-encrypted credentials, actions with idempotency keys and append-only attempt records. After approval or auto-approval the worker proposes one action per configured destination with a preview; the policy, kill switch and shadow mode are re-read immediately before every external call; retries back off with jitter to a dead-letter queue with manual retry; reopening withdraws proposals. Connectors: HMAC-signed webhook with an SSRF guard, idempotent CSV export to object storage with downloads, Postgres table inserts with quoted identifiers and conflict-free duplicates, Google Sheets via service-account JWT. Settings APIs for policies, connectors (with connection tests), and workflow configuration with YAML import/export and append-only versions. Timeline shows actions. 261 API tests; ADR 007. The Oracle configuration helper now generates the encryption key.
- Phase 3 security fix pass from the independent review: the Postgres connector parses and allow-lists DSN keys, refuses socket hosts and private or flipped addresses and connects to the checked address with TLS required; the Google token endpoint is pinned; webhooks send to the resolved address with the hostname kept for TLS and SNI, closing the DNS-rebinding window; reopen and connector changes withdraw unstarted actions; tightening a policy to needs-approval re-proposes auto-approved actions; busy workers defer instead of burning attempts; poison events are abandoned after three claims; connector errors never store document values; authorization headers cannot be stored in webhook config; CSV downloads are admin-only; connection tests refuse while the agent is paused; migration 0009 gives attempt records a tenant-scoped foreign key; deadlocks surface as 409. 275 API tests.
- Phase 3 frontend: `/actions` with pending approvals, history and dead letters, preview diffs, approve/reject/retry with version checks; `/settings/policies` with a confirmed kill switch, shadow mode and a per-type policy table; `/settings/connectors` with per-type validated forms, connection tests, deactivation and CSV export downloads; `/settings/workflow` with a YAML editor, import/export, line-referenced validation errors and a structured summary; an "Agent paused" banner; dashboard tiles for approvals and dead letters; timeline action entries. 113 web tests. A new browser script drives a real signed webhook into a local receiver and proves the kill switch, shadow mode and forbidden policy in the UI; it runs in CI.
- CI now routes Docker Hub pulls through a public mirror and caches base images, after shared runners hit anonymous pull limits.
- Next: Phase 4 (logistics document types, synthetic dataset, near-duplicate detection, API keys, email intake, KPIs).

## 2026-09-26 — Oracle Free Tier deployment preparation

- Owner requires $0 hosting; card verification is allowed, paid plans are not. Researched current official limits and selected Oracle A1 as the first option, subject to signup/capacity. Retained Render+Supabase as an unimplemented fallback with sleep/worker limitations. The existing paid Render Blueprint is explicitly marked unsuitable for this budget.
- Added production Compose with Caddy HTTPS, private API/worker/Postgres, persistent volumes, bounded logs/memory and isolated migrations. Added private configuration generation, a consistent command wrapper, database backup helper and known-key S3 check. Runtime retains restricted database credentials; optional model secrets stay on the worker. Nested environment files are excluded from Docker builds.
- Expanded the existing deployment guide with account/network/SSH/DNS/bucket/IAM setup, Docker install, exact startup and migration commands, hosted acceptance, backup/restore and maintenance. Updated README/system design and ADR005. All pages and application behavior are unchanged.
- Verified production image builds, Caddy validation, migrations on isolated PostgreSQL16, local HTTPS signup/proxy/cookies and authorization error cases, restricted role privileges, backup and isolated restore, secret setup/overwrite protection, Python lint/format and shell syntax. No live model calls or Oracle credentials were used. Hosted capacity, public certificates, private bucket round trip and complete hosted invoice workflow remain to verify in the owner's account.

## 2026-09-26 — Public landing and organization entry flow

- Added a public homepage with a responsive cream/teal design, clearly labeled product illustration, admin/member/reviewer entry cards, workflow guide, five workspace page explanations and accessible FAQ/navigation.
- Connected role choices to registration form defaults and aligned login/register with a shared brand. Direct links, client navigation and browser history preserve correct entry behavior; invalid role values cannot create privileges. Sign-in remains common to all approved roles. Clicking the selected registration mode now preserves entered organization fields.
- Added the public browser suite to CI and updated the system design with the eight-page map, entry-flow diagram and authorization boundaries. Render instructions explain that all frontend pages deploy as one web service with a separate private API and worker.
- Verification: 16 web tests, ESLint, TypeScript, production Docker build, public browser suite and complete fresh-company/invoice-review browser suite passed. Visually reviewed desktop/mobile landing and authentication screens. Landing navigation passes at 390/320 px; login and all registration variants fit at 320 px. No live model call was used.
- Application changes are in `a8dfad5`. Local homepage runs at http://localhost:3300. Public Render deployment remains the next step after the user registers/connects GitHub and supplies database/storage settings.

## 2026-09-26 — Organization onboarding and collaborative invoice review

- Added real organization registration and pending member/reviewer requests, admin approvals/rejections/suspension, category management and role controls. Normal startup no longer seeds sample accounts.
- Added reviewer assignment, verified Decimal money/currency, comments, approve/reject/reopen history and restricted sharing. Lists, file downloads, summaries, questions and duplicate uploads enforce the same invoice permissions. Added migrations `0004`/`0005` and permission/concurrency regression tests.
- Expanded to seven pages with Review and Insights, category/status filtering, pagination, company totals and grounded questions. Full PDFs render locally with page navigation, zoom and readable text; the compatibility worker handles the installed browser. Drafts retain their base version and survive background refreshes.
- Rewrote SYSTEM_DESIGN.md around implemented architecture, explicit boundaries, failure recovery, latency objectives and capacity calculations. Added Render Blueprint/runbook for a new project; removed the obsolete demo guide. Hosted deployment and live-model testing remain unverified.
- Final local gates passed: 80 API tests against Postgres, 16 web tests, lint/types, production Docker builds, matching generated API contracts, existing happy/error/tenant browser suites, and the fresh-company workflow suite including two-page rendering, editor conflicts, access revocation and 390 px layout. Production npm audit found 0 advisories at this check.
- Local sequential browser smoke, 20 samples/endpoint and one reviewed two-page invoice: documents p50 12.0 ms / p95 67.5 ms; workspace summary p50 5.4 ms / p95 7.3 ms. This is a small functional smoke measurement, not sustained throughput or production reliability evidence.
- The user selected a new Render project and will register/connect GitHub. Local application remains available at localhost:3300 with rules extraction; no exposed model credential was used. Application commit `ad55d0f` passed [all four GitHub CI jobs](https://github.com/Abhinavsuri90/opspilot/actions/runs/36241455074), including the complete fresh-company browser workflow.

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

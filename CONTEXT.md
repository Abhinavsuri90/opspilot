# Current handoff

Updated 2026-09-26 for the public landing and signup release. Implementation commit: `a8dfad5`; the following documentation commit records this handoff.

## Implemented

Eight pages: public Home, Register, Login, Dashboard, Inbox, Review, Insights and Admin. Home presents the workflow, role choices, product preview, page guide and FAQ. Landing and authentication use a shared cream/teal visual identity. Organization owners register as admins; member/reviewer entry links preselect pending join requests. URL parameters do not grant permissions. All roles share one sign-in; the API checks active membership and invoice access. Admins manage categories, roles and suspension. Invoices support full document viewing, immutable extraction evidence, reviewer assignment, verified Decimal money, comments, approve/reject/reopen and restricted authenticated sharing. SQL-backed questions and currency-separated totals honor the complete document ACL.

FastAPI uses a restricted Postgres role plus tenant RLS. Migrations through `0005` add membership lifecycle and collaboration tables. A leased transactional outbox runs extraction; default provider rules parses labeled text locally, with optional OpenRouter structured extraction. Runtime services never receive owner database credentials. Normal make up does not seed accounts; make demo explicitly does.

## Verification in this release

Public-entry release: web lint, TypeScript, 16 unit tests and production Docker build passed. The new public browser suite passes homepage 200, all three role links, direct entry, history, invalid-parameter fallback, preserved organization draft, shared login, protected Dashboard redirect, keyboard skip link, mobile navigation and 390/320 px layout. The full fresh-company workflow suite passed again. Visual review covered desktop/mobile landing, sign-in and reviewer registration; all signup forms also fit 320 px. The public suite is included in GitHub CI after browser dependencies are installed. No extraction or API behavior changed in this release.

Previous organization/collaboration release evidence:

Final local verification: 80 Postgres API tests; Python lint and strict types; 16 web tests; web lint, types and production Docker build; zero production npm audit advisories. Existing browser happy/error/company-isolation suites pass. The fresh-company browser suite passes signup, pending 403, approval, categories, extraction, verified money, comments, restricted sharing, decisions, questions, totals, suspension, concurrent draft preservation/conflicts, actual two-page PDF rendering/navigation/zoom, and 390 px responsive Admin. Local sequential 20-sample browser p95: documents 67.5 ms, summary 7.3 ms; these are not load-test or production results. OpenAPI matches the built API image (26 operations). Application commit `ad55d0f` passed all four jobs in [GitHub CI](https://github.com/Abhinavsuri90/opspilot/actions/runs/36241455074): API, web, release images and browser smoke.

## Deployment

Owner chose a new Render project and will register/connect GitHub. render.yaml and docs/deployment.md define one public web service for all eight pages, a separate private API and background worker; create/migrate managed Postgres first and supply private S3/R2 credentials. The local application is running at http://localhost:3300 using rules extraction. No hosted URL/account connection or live OpenRouter evaluation has been verified. An earlier OpenRouter key was disclosed in chat; it was not used by this work. Require a rotated key in ignored local environment or Render worker secrets before live model tests.

## Exact next step

Confirm the latest GitHub checks, then use docs/deployment.md with the user's new Render account: private database/bucket setup, owner-only migrations, Blueprint provisioning, secrets/origin, and hosted acceptance. All frontend routes deploy together; the API and worker have separate services. Do not seed the hosted database.

## Important files

- SYSTEM_DESIGN.md: current architecture, permissions, data model, failure handling, concurrency, latency targets and capacity assumptions.
- README.md: local signup steps, pages, checks and limits.
- docs/deployment.md and render.yaml: Render deployment procedure.
- apps/api/app/auth.py, onboarding.py, invoice_workflows.py: organization access and collaboration.
- apps/web/components/InvoiceWorkspace.tsx: review/discussion/sharing UI.
- apps/web/scripts/e2e-workspace.mjs: fresh company acceptance flow and small sequential latency smoke.
- apps/web/app/page.tsx, landing.module.css and components/PublicBrand.tsx: public entry and visual identity.
- apps/web/scripts/e2e-public.mjs: public navigation and signup selection checks.

## How to run and test

Start Docker Desktop, then `LLM_PROVIDER=rules OPENROUTER_API_KEY= make up`. Open http://localhost:3300. `make down` stops services while preserving data. Web checks: `cd apps/web && npm run lint && npm run typecheck && npm test && npm run test:e2e:public && npm run test:e2e:workspace`. Full stack commands and optional model configuration are in README.md. Secrets belong only in ignored environment files or Render settings.

## Remaining operational gates

Render project/access, private storage, hosted acceptance test, fresh model key/model evaluation if enabled, email verification/password recovery, owner recovery/transfer, trusted edge abuse controls, hostile PDF isolation, backups/restore, alerts and measured production load. SPEC.md is the historical roadmap; it is not the release status. See docs/deployment-readiness-review.md.

The old demo-guide.md was removed because README and SYSTEM_DESIGN now provide the maintained walkthrough and interview material. PROGRESS.md retains historical entries; read the newest entry first.

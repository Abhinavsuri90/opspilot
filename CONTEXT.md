# Current handoff

Updated 2026-09-26 for the complete Oracle walkthrough and production VM files. Previous verified application release: `c92450d`; application implementation: `a8dfad5`. The Oracle configuration has been tested locally, but no Oracle resources have been provisioned by this work.

## Implemented

Eight pages: public Home, Register, Login, Dashboard, Inbox, Review, Insights and Admin. Home presents the workflow, role choices, product preview, page guide and FAQ. Landing and authentication use a shared cream/teal visual identity. Organization owners register as admins; member/reviewer entry links preselect pending join requests. URL parameters do not grant permissions. All roles share one sign-in; the API checks active membership and invoice access. Admins manage categories, roles and suspension. Invoices support full document viewing, immutable extraction evidence, reviewer assignment, verified Decimal money, comments, approve/reject/reopen and restricted authenticated sharing. SQL-backed questions and currency-separated totals honor the complete document ACL.

FastAPI uses a restricted Postgres role plus tenant RLS. Migrations through `0005` add membership lifecycle and collaboration tables. A leased transactional outbox runs extraction; default provider rules parses labeled text locally, with optional OpenRouter structured extraction. Runtime services never receive owner database credentials. Normal make up does not seed accounts; make demo explicitly does.

## Verification in this release

Public-entry release: web lint, TypeScript, 16 unit tests and production Docker build passed. The new public browser suite passes homepage 200, all three role links, direct entry, history, invalid-parameter fallback, preserved organization draft, shared login, protected Dashboard redirect, keyboard skip link, mobile navigation and 390/320 px layout. The full fresh-company workflow suite passed again. Visual review covered desktop/mobile landing, sign-in and reviewer registration; all signup forms also fit 320 px. The public suite is included in GitHub CI after browser dependencies are installed. No extraction or API behavior changed in this release.

Previous organization/collaboration release evidence:

Final local verification: 80 Postgres API tests; Python lint and strict types; 16 web tests; web lint, types and production Docker build; zero production npm audit advisories. Existing browser happy/error/company-isolation suites pass. The fresh-company browser suite passes signup, pending 403, approval, categories, extraction, verified money, comments, restricted sharing, decisions, questions, totals, suspension, concurrent draft preservation/conflicts, actual two-page PDF rendering/navigation/zoom, and 390 px responsive Admin. Local sequential 20-sample browser p95: documents 67.5 ms, summary 7.3 ms; these are not load-test or production results. OpenAPI matches the built API image (26 operations). Application commit `ad55d0f` passed all four jobs in [GitHub CI](https://github.com/Abhinavsuri90/opspilot/actions/runs/36241455074): API, web, release images and browser smoke.

## Deployment

Owner reports completing the guide through Step 3: Render account/project setup and a Postgres database on the Free plan, with connection credentials saved privately. Region, database privileges and connectivity have not been independently verified. Storage, migrations and application deployment remain pending. The owner now explicitly requires free hosting and allows card verification, but no paid plan. Do not provision the existing Blueprint: its web/API/worker all use paid plans. Render Free Postgres expires after 30 days and has no backups.

Recommended alternative, pending signup/capacity: Oracle Always Free A1 VM, self-managed PostgreSQL, private object storage and HTTPS ingress. Current official allowance is 2 OCPUs/12 GB, not the older 4/24 figure. Free capacity is not guaranteed; idle instances can be reclaimed; no uptime SLA. Production Compose is prepared below; hosted verification still depends on account capacity and credentials. Fallback is one combined Render Free web service plus Supabase Free Postgres/storage. It requires process supervision, bounded memory, restricted-role pooler support, S3 compatibility validation and disabling Supabase Data API. Render sleep stops the worker; do not promise identical availability. Continuous worker polling makes Neon compute-hour quotas a poor fit. Details and official sources are in docs/deployment.md.

Oracle production Compose is now implemented in infra/oracle: separate Caddy/web/API/worker/Postgres, only TCP80/443 published, private database network, persistent data/TLS volumes, rotated Docker logs, container memory limits, owner-only migration profile, secure cookies and restricted runtime role. init_env.py generates private secrets without printing them and refuses overwrites; ops selects the production files; backup.sh writes a validated database archive; check_storage.py verifies a tiny synthetic PDF round trip once real credentials exist. No storage SDK change was needed: current OCI supports the pinned SDK's checksum trailers. ADR005 records the single-VM tradeoff.

Oracle local verification: API/web production builds; Caddy config; fresh PostgreSQL16 migrations through0005; API/web/Caddy health; HTTPS homepage and organization registration through Caddy with Secure/HttpOnly cookie; authenticated proxy requests;403 wrong-origin and401 anonymous denials; restricted role has no superuser/BYPASSRLS; backup helper and restore into a separate database preserve schema and the synthetic organization. Private env creation/600 mode/no secret output/overwrite refusal, shell syntax and Python lint/format passed. TLS used a local test certificate; public CA issuance, actual OCI S3 and cloud firewall remain unverified. Existing application source was not changed.

render.yaml retains the paid Render reference with one public web service for all eight pages, a separate private API and background worker. The local application is running at http://localhost:3300 using rules extraction. No hosted URL/account connection or live OpenRouter evaluation has been verified. An earlier OpenRouter key was disclosed in chat; it was not used by this work. Require a rotated key in ignored local environment or host worker secrets before live model tests. Rules extraction avoids model charges but only supports labeled text invoices.

## Exact next step

The user requested the entire Oracle guide in chat. Follow docs/deployment.md from signup through compartment, manual public VCN, A1 Ubuntu24.04 ARM VM, SSH, DuckDNS, private bucket/scoped Customer Secret Key, Docker install, clone, private config helper, build/migrate/start, real storage/TLS/browser verification and backups. First confirm signup and actual A1 Running capacity in the home region, staying on Free Tier. Keep secrets on the VM or in a password manager. All eight pages deploy together. Do not seed the hosted database. Use the managed fallback if free VM capacity cannot be obtained.

## Important files

- SYSTEM_DESIGN.md: current architecture, permissions, data model, failure handling, concurrency, latency targets and capacity assumptions.
- README.md: local signup steps, pages, checks and limits.
- docs/deployment.md: free hosting comparison and paid Render reference; render.yaml: paid Render configuration.
- infra/oracle/: production Compose, Caddy, private configuration setup, command wrapper, database backup and scoped storage check.
- docs/adr/005-free-vm-deployment.md: free VM choice and operational tradeoffs.
- apps/api/app/auth.py, onboarding.py, invoice_workflows.py: organization access and collaboration.
- apps/web/components/InvoiceWorkspace.tsx: review/discussion/sharing UI.
- apps/web/scripts/e2e-workspace.mjs: fresh company acceptance flow and small sequential latency smoke.
- apps/web/app/page.tsx, landing.module.css and components/PublicBrand.tsx: public entry and visual identity.
- apps/web/scripts/e2e-public.mjs: public navigation and signup selection checks.

## How to run and test

Start Docker Desktop, then `LLM_PROVIDER=rules OPENROUTER_API_KEY= make up`. Open http://localhost:3300. `make down` stops services while preserving data. Web checks: `cd apps/web && npm run lint && npm run typecheck && npm test && npm run test:e2e:public && npm run test:e2e:workspace`. Full stack commands and optional model configuration are in README.md. Secrets belong only in ignored environment files or Render settings.

## Remaining operational gates

Free host signup/capacity, production host configuration, private storage, hosted acceptance test, fresh model key/model evaluation if enabled, email verification/password recovery, owner recovery/transfer, trusted edge abuse controls, hostile PDF isolation, backups/restore, alerts and measured production load. SPEC.md is the historical roadmap; it is not the release status. See docs/deployment-readiness-review.md.

The old demo-guide.md was removed because README and SYSTEM_DESIGN now provide the maintained walkthrough and interview material. PROGRESS.md retains historical entries; read the newest entry first.

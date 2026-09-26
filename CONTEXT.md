# Current handoff

## Last updated

2026-09-26 16:37 IST. Application code at `6a680a6` passed the [four-job CI run](https://github.com/Abhinavsuri90/opspilot/actions/runs/36237433628). The local Compose stack is stopped; its database and storage volumes remain.

## Current status

OpsPilot is a local Phase 1 invoice intake/extraction prototype. The four working web pages are Login, Dashboard, Inbox, and a read-only Admin directory for administrators. Authenticated tenants upload text-layer PDFs through the Next.js same-origin API proxy. FastAPI stores documents in S3-compatible storage and queues extraction through a Postgres outbox. The worker records four fields with page-level evidence; the Inbox searches/filters recent records and permits two manual retries of a failed document. A Postgres login attempt counter and raw-upload limit guard the public demo path. OpenRouter is optional; live extraction accuracy has not been tested. Public staging and the review/approval/action phases are pending.

The screenshot of failed CI commit `69ebf1b` is historical. The [application CI run](https://github.com/Abhinavsuri90/opspilot/actions/runs/36237433628) passed API, web, release-image, and browser jobs at `6a680a6`; the browser job includes company-wise invoice upload and isolation.

The latest local audit covers all 10 API routes and web error states. The redesigned frontend has a shared responsive shell, useful Dashboard, searchable Inbox, and read-only Admin member directory. Four fictional PDFs under `examples/demo/` support a Northwind/Contoso isolation walkthrough. Five empty future engagement templates were removed earlier; all remaining tracked Markdown is substantive. Every deployed commit must have a green CI run.

## Exact next step

1. Obtain the owner's Railway project link or invite. Follow [docs/deployment.md](docs/deployment.md): provision Postgres and Bucket, run migration/bootstrap first, deploy private API/worker and public web, then run the browser smoke against the public URL. Confirm CI passes on the exact deploy commit.
2. Record the verified hosted URL, CI run, backup/restore status, and remaining limitations in `PROGRESS.md`. Keep `LLM_PROVIDER=mock` until the infrastructure demo is stable. Rotate the previously shared OpenRouter key before optional live-model evaluation; never send the replacement in chat or commit it.

## Files in play

- `apps/api/`: migration `0003`, login throttle, upload/storage/integrity limits, tenant-fair worker, and tests.
- `apps/web/`: responsive shell, Dashboard, Inbox, Admin member directory, session-aware queries, and browser happy/error/tenant-isolation tests.
- `.github/workflows/ci.yml`, `infra/`, `Makefile`: pinned release dependencies, audits, ordered local startup, and browser CI.
- `README.md`, `SPEC.md`, `SYSTEM_DESIGN.md`, `docs/assets/`, and `examples/demo/`: local steps, honest scope, current screenshots, and fictional company invoices.
- `docs/deployment.md`, `docs/deployment-readiness-review.md`, `docs/demo-guide.md`, ADR 003/004: deployment and design evidence.

## Decisions and deviations

- The worker polls the transactional Postgres outbox directly before the planned Redis dispatcher ([ADR 003](docs/adr/003-direct-outbox-polling.md)). It rotates its starting tenant after each claim.
- Login throttling uses a shared Postgres identity counter rather than process memory ([ADR 004](docs/adr/004-postgres-login-throttle.md)); an edge per-IP limit remains a deployment task.
- Local storage uses Adobe S3Mock ([ADR 002](docs/adr/002-local-s3-emulator.md)). The target Railway deployment uses a private S3-compatible Bucket.
- The current inbox is a holding state for human review; editing, approval, actions, OCR, confidence scoring, and the later `SPEC.md` phases are not implemented.

## Environment

- Local web: `http://localhost:3300`; local API: `http://localhost:8000`. Staging and production: no verified URLs. Repository: https://github.com/Abhinavsuri90/opspilot.
- Required deployment variable **names** are listed in `.env.example` and the deployment runbook. Key names include `DATABASE_URL`, `DATABASE_OWNER_URL` (migration job only), `APP_DB_PASSWORD`, `JWT_SECRET`, `DEMO_PASSWORD`, `WEB_ORIGIN`, `API_INTERNAL_URL`, `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`, `S3_ADDRESSING_STYLE`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `LLM_PROVIDER`, and optional `OPENROUTER_API_KEY`/`OPENROUTER_MODEL` (worker only).
- Local fictional accounts: `northwind@example.com` in `northwind` and `contoso@example.com` in `contoso`; passwords are supplied through the ignored `.env`. No Railway account or project access has been supplied in this session.

## How to run and test

Run `LLM_PROVIDER=mock OPENROUTER_API_KEY= make up`, then `make smoke`, `LLM_PROVIDER=mock OPENROUTER_API_KEY= make smoke-ui`, and `LLM_PROVIDER=mock OPENROUTER_API_KEY= make smoke-tenants`. Run `cd apps/web && npm run test:e2e:errors` for the mocked browser error paths; `make lint typecheck test` runs code checks. `make down` stops local services without deleting persistent data. The latest local verification passed: 41 API tests across all 10 routes, 16 web tests, Ruff, strict mypy, web lint/typecheck/build, browser happy/error/company-isolation flows, and a 390-pixel mobile check. The synthetic mock evaluation and dependency audits passed in the previous review; they are not live-model accuracy claims.

## Known issues and gotchas

- A public URL, actual Railway Bucket, backup restore, alerts, and live OpenRouter call have not been verified. Do not claim production readiness or AI accuracy.
- Login identity throttling can be used to cause a temporary lockout; use an edge per-IP limit/WAF before sharing a demo account widely. Document retention/deletion and real-customer privacy controls are still missing.
- The worker accepts only unencrypted text-layer PDFs up to the documented limits. Scanned documents need OCR.
- Docker Desktop on this Mac may need `DOCKER_CONFIG=/private/tmp/opspilot-docker-config` during image pulls if its credential helper hangs. Do not commit that local workaround.

## Open questions for the owner

- Which Railway project should host the first private public demo? Share a project URL or invite, not credentials.
- Should the first hosted demo stay on deterministic mock extraction? This is recommended until the hosted browser workflow passes; live-model evaluation can follow with a rotated key stored only as a worker secret.

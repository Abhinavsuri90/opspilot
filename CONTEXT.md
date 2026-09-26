# Current handoff

## Last updated

2026-09-26, after implementation commit `280b1d7`. Run `git log -1 --oneline` for the current documentation commit.

## Current status

OpsPilot is a local Phase 1 invoice intake/extraction prototype. Authenticated tenants upload text-layer PDFs through a Next.js web app and same-origin API proxy. FastAPI stores documents in S3-compatible storage and queues extraction through a Postgres outbox. The worker records four fields with page-level evidence; the Inbox displays results and permits two manual retries of a failed document. A Postgres login attempt counter and raw-upload limit guard the public demo path. OpenRouter is optional; live extraction accuracy has not been tested. Public staging and the review/approval/action phases are pending.

The screenshot of failed CI commit `69ebf1b` is historical. Commit `45f4f3e` passed all three then-existing jobs. A new full-stack browser CI job and Python dependency audit have been added and need a green run on the current push before release.

## Exact next step

1. Push the current commits and confirm API, web, release-images, and browser-smoke jobs all pass on the same GitHub commit.
2. Obtain the owner's Railway project link or invite. Follow [docs/deployment.md](docs/deployment.md): provision Postgres and Bucket, run migration/bootstrap first, deploy private API/worker and public web, then run the browser smoke against the public URL.
3. Record the verified hosted URL, CI run, backup/restore status, and remaining limitations in `PROGRESS.md`. Keep `LLM_PROVIDER=mock` until the infrastructure demo is stable. Rotate the previously shared OpenRouter key before optional live-model evaluation; never send the replacement in chat or commit it.

## Files in play

- `apps/api/`: migration `0003`, login throttle, upload/storage/integrity limits, tenant-fair worker, and tests.
- `apps/web/`: session-aware queries, upload validation and role UX, focus styles, and tests.
- `.github/workflows/ci.yml`, `infra/`, `Makefile`: pinned release dependencies, audits, ordered local startup, and browser CI.
- `docs/deployment.md`, `docs/deployment-readiness-review.md`, `docs/demo-guide.md`, `SYSTEM_DESIGN.md`, ADR 003/004: deployment and design evidence.

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

Run `LLM_PROVIDER=mock OPENROUTER_API_KEY= make up`, then `make smoke`, `make smoke-ui`, and `make eval` with the same mock override. `make lint typecheck test` runs backend and frontend checks. `make down` stops local services. The current local verification passed: 29 API tests, 12 web tests, Ruff, strict mypy, web lint/typecheck/build, API and browser smokes, and synthetic mock evaluation. The release dependency audit and full npm audit reported no known advisories at review time.

## Known issues and gotchas

- A public URL, actual Railway Bucket, backup restore, alerts, and live OpenRouter call have not been verified. Do not claim production readiness or AI accuracy.
- Login identity throttling can be used to cause a temporary lockout; use an edge per-IP limit/WAF before sharing a demo account widely. Document retention/deletion and real-customer privacy controls are still missing.
- The worker accepts only unencrypted text-layer PDFs up to the documented limits. Scanned documents need OCR.
- Docker Desktop on this Mac may need `DOCKER_CONFIG=/private/tmp/opspilot-docker-config` during image pulls if its credential helper hangs. Do not commit that local workaround.

## Open questions for the owner

- Which Railway project should host the first private public demo? Share a project URL or invite, not credentials.
- Should the first hosted demo stay on deterministic mock extraction? This is recommended until the hosted browser workflow passes; live-model evaluation can follow with a rotated key stored only as a worker secret.

# Current handoff

## Last updated
2026-09-26 03:22 IST. Latest commit hash: run `git rev-parse HEAD` after this handoff is committed.

## Current status
Phase 0 local foundation works. `make up`, lint, typecheck, tests, API smoke test, and browser login all pass. The repository has its own Git checkout. Railway staging is pending.

## Exact next step
Get the user's Railway project choice and access details. Configure Postgres and the staging web/API services following `docs/deployment.md`, run migrations and private demo seeding, then run `scripts/smoke_test.py` against the staging API URL and verify browser login.

## Files in play
`apps/api`, `apps/web`, `docker-compose.yml`, `Makefile`, `.github/workflows/ci.yml`, ADRs, deployment and handoff docs.

## Decisions and deviations
Build Phase 0 first. The local MinIO image could not be pulled, so Compose uses Adobe S3Mock (ADR 002). Postgres is exposed on host port 55432 and web on 3300 because local services already occupy the defaults. API runs with only the restricted database role; one-off admin jobs get owner credentials (ADR 001). An isolated Git repository was initialized after sandbox escalation, avoiding the unrelated parent checkout.

## Environment
Local URL: `http://localhost:3300` (web), `http://localhost:8000` (API). Staging and production: unset. External accounts: unknown. Required environment variable names: see `.env.example`. Local demo: org `northwind`, email `northwind@example.com`, password from `DEMO_PASSWORD` (never store its value here).

## How to run and test
`make up`, `make lint typecheck test smoke`, `make smoke-ui`, `make gen-client`, and `make down`. On this Mac, set `DOCKER_CONFIG=/private/tmp/opspilot-docker-config` for Compose while Docker Desktop's credential helper hangs; this temporary config and its CLI plugin links were created during local verification. Host-side web checks require Node.js 22 and npm.

## Known issues and gotchas
Staging requires a Railway project and access. Docker Desktop's credential helper hangs on public image pulls in this environment; a temporary empty Docker config works. The host has Python 3.13; containers use Python 3.12. FastAPI TestClient emits a dependency deprecation warning while tests pass.

## Open questions for me
Railway project choice and staging access details are needed. The user has been asked whether a project already exists.

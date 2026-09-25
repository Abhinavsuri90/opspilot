# Current handoff

## Last updated
2026-09-26 03:48 IST. Latest commit hash: run `git rev-parse HEAD` after this handoff is committed.

## Current status
Phase 0 local foundation works. The eight-commit `main` branch is published at https://github.com/Abhinavsuri90/opspilot. The first GitHub Actions run passed: https://github.com/Abhinavsuri90/opspilot/actions/runs/36195985550. Local lint, typecheck, tests, API smoke, and browser login/logout pass. Railway staging is pending.

## Exact next step
Get the user's Railway project choice and access details. Configure Postgres and the staging web/API services following `docs/deployment.md`, run migrations and private demo seeding, then run `scripts/smoke_test.py` against the staging API URL and verify browser login. Before beginning, run `git status --short --branch` and `make up` to confirm the local stack.

## Files in play
`apps/api`, `apps/web`, `.github/workflows/ci.yml`, `scripts/ci_api_smoke.sh`, `README.md`, `docs/assets/dashboard.png`, deployment and handoff docs. The current task ends with the GitHub publication and verification recorded here.

## Decisions and deviations
Build Phase 0 first. The local MinIO image could not be pulled, so Compose uses Adobe S3Mock (ADR 002). Postgres is exposed on host port 55432 and web on 3300 because local services already occupy the defaults. API runs with only the restricted database role; one-off admin jobs get owner credentials (ADR 001). An isolated Git repository was initialized after sandbox escalation, avoiding the unrelated parent checkout. GitHub SSH authentication was unavailable, so `origin` uses HTTPS; the authenticated push succeeded.

## Environment
Local URL: `http://localhost:3300` (web), `http://localhost:8000` (API). GitHub: https://github.com/Abhinavsuri90/opspilot. Staging and production: unset. External accounts: GitHub configured; Railway unknown. Required environment variable names: see `.env.example`. Local demo: org `northwind`, email `northwind@example.com`, password from `DEMO_PASSWORD` (never store its value here).

## How to run and test
`make up`, `make lint typecheck test smoke`, `make smoke-ui`, `make gen-client`, and `make down`. The full check suite passed on 2026-09-26: four backend tests, two frontend tests, live API smoke, and browser login/logout. The GitHub CI run passed. On this Mac, set `DOCKER_CONFIG=/private/tmp/opspilot-docker-config` for Compose while Docker Desktop's credential helper hangs; this temporary config and its CLI plugin links were created during local verification. Host-side web checks require Node.js 22 and npm.

## Known issues and gotchas
Staging requires a Railway project and access. Docker Desktop's credential helper hangs on public image pulls in this environment; a temporary empty Docker config works. The host has Python 3.13; containers use Python 3.12. FastAPI TestClient emits a dependency deprecation warning while tests pass.

## Open questions for me
Railway project choice and staging access details are needed. The user has been asked whether a project already exists.

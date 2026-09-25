# Progress

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

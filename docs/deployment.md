# Deployment runbook (Phase 0 staging preparation)

Railway staging and the single-VM option are planned. Neither is verified yet.

## Railway staging

1. Create a Railway project with a Postgres 16 service. Set up a database owner credential for migrations and a restricted app credential from migration `0001`. The migration requires `CREATEROLE` privileges to create `opspilot_app`; use an administrative connection for the initial migration.
2. Create an API service from `infra/api.Dockerfile`. Set only the restricted `DATABASE_URL`, `JWT_SECRET`, `WEB_ORIGIN`, `COOKIE_SECURE=true`, and `ENVIRONMENT=staging`. Do not use the local development values. The API service must not receive the owner database URL.
3. Run `alembic upgrade head` as a one-off job with `DATABASE_OWNER_URL` and `APP_DB_PASSWORD`, then run `python /workspace/scripts/seed.py` only for a private staging environment. Keep owner credentials scoped to these one-off jobs.
4. Create a web service from `infra/web.Dockerfile`. Set build arg and runtime `NEXT_PUBLIC_API_BASE_URL` to the public API URL. Set `WEB_ORIGIN` on the API to the public web URL.
5. Verify `/healthz`, `/readyz`, login, and `/v1/auth/me` with `scripts/smoke_test.py`. Record the URLs and date in `CONTEXT.md` and `PROGRESS.md` after the checks actually pass.

The API image currently includes test dependencies and owner tooling for Phase 0. Split migration into a separate release image before production. Compose already keeps owner credentials out of the normal API process.

## Single-VM option

Install Docker Engine and Compose, put environment variables in a secret file outside the repository, and run the Compose services behind a reverse proxy such as Caddy with HTTPS. Replace development passwords, restrict database and infrastructure ports to localhost or a private network, then run `make migrate`, `make seed` only for a demo environment, and the smoke test. A complete customer-hosted runbook will be written before go-live.

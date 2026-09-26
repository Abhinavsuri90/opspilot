# Deployment runbook (staging preparation)

Railway staging and the single-VM option are planned. Neither is verified yet.

## Railway staging

1. Create a Railway project with a Postgres 16 service. Set up a database owner credential for migrations and a restricted app credential from migration `0001`. The migration requires `CREATEROLE` privileges to create `opspilot_app`; use an administrative connection for the initial migration.
2. Provision an S3-compatible bucket and give the API and worker only the object permissions they need. Set `S3_BUCKET`, `S3_REGION`, `S3_ACCESS_KEY_ID`, and `S3_SECRET_ACCESS_KEY` on those services. Set `S3_ENDPOINT_URL` for an S3-compatible provider; leave it unset for AWS S3. Confirm upload and download behavior against this bucket before calling staging verified.
3. Create an API service from `infra/api.Dockerfile`. Set only the restricted `DATABASE_URL`, `JWT_SECRET`, `WEB_ORIGIN`, `COOKIE_SECURE=true`, `ENVIRONMENT=staging`, and the storage variables. Do not use the local development values. The API service must not receive the owner database URL or a model API key.
4. Run `alembic upgrade head` as a one-off job with `DATABASE_OWNER_URL` and `APP_DB_PASSWORD`, then run `python /workspace/scripts/seed.py` only for a private staging environment. Keep owner credentials scoped to these one-off jobs.
5. Create a worker service from the same API image with command `python -m app.worker`, the restricted `DATABASE_URL`, and the storage variables. Set `LLM_PROVIDER=mock` for initial staging. For real extraction, supply a new `OPENROUTER_API_KEY` through Railway secrets, set `LLM_PROVIDER=openrouter`, and choose `OPENROUTER_MODEL`; do not give the key to the API or web service.
6. Create a web service from `infra/web.Dockerfile`. Set build arg and runtime `NEXT_PUBLIC_API_BASE_URL` to the public API URL. Set `WEB_ORIGIN` on the API to the public web URL.
7. Verify `/healthz`, `/readyz`, login, and `/v1/auth/me` with `scripts/smoke_test.py`. Also upload a fictional text-layer invoice and verify it reaches `needs_review` with evidence. Record the URLs and date in `CONTEXT.md` and `PROGRESS.md` after the checks actually pass.

The API image currently includes test dependencies and owner tooling. Split migration into a separate release image before production. Compose already keeps owner credentials out of the normal API and worker processes. The local direct outbox polling design is documented in [ADR 003](adr/003-direct-outbox-polling.md); add scaling and operational safeguards before production.

## Single-VM option

Install Docker Engine and Compose, put environment variables in a secret file outside the repository, and run the Compose services behind a reverse proxy such as Caddy with HTTPS. Replace development passwords, restrict database and infrastructure ports to localhost or a private network, then run `make migrate`, `make seed` only for a demo environment, and the smoke test. A complete customer-hosted runbook will be written before go-live.

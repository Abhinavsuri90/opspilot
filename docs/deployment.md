# Deploying OpsPilot

**Status:** the Docker Compose workflow is verified locally. A public deployment has not been created or tested. Do not describe the app as production ready until the public URL, storage, worker, and browser workflow have been checked.

## Choose a host

| Option | Fit for the first public demo | Work left |
| --- | --- | --- |
| [Railway](https://docs.railway.com/guides/docker-compose) | Recommended: web, private API and worker, Postgres, and an S3-compatible [Bucket](https://docs.railway.com/storage-buckets) in one project | Create services, secrets, and bucket; run migrations; verify public URL and spend |
| [Render](https://render.com/docs/background-workers) | Viable web and background worker host | Add an external S3-compatible bucket and wire the services |
| Single VM | Maximum control | Build a separate production Compose stack with TLS, backups, monitoring, patching, and no demo support services |

The repository's `docker-compose.yml` is **local development only**. It binds host ports to `127.0.0.1`, uses local demo secrets and S3Mock, and `make up` seeds fictional accounts. Do not publish those containers directly to the internet.

## Railway: first private demo

The project owner needs to create or share a Railway project before these steps can be executed. The setup below uses Railway's dashboard; new services should not use legacy `railway.toml`/`railway.json`, which [Railway has deprecated for new projects](https://docs.railway.com/config-as-code).

1. Connect the [GitHub repository](https://github.com/Abhinavsuri90/opspilot) to a Railway project. Leave each service's Root Directory at the default repository root: the Dockerfiles use paths under `apps/` and `infra/`, and the API image also copies `scripts/`. Set each service's Dockerfile Path explicitly (`infra/api.Dockerfile` or `infra/web.Dockerfile`). [Disable GitHub autodeploy](https://docs.railway.com/deployments/github-autodeploys) on the migration job and application services during the first rollout so the migration runs before the API and worker. When an ordered release process is in place, enable [Wait for CI](https://docs.railway.com/deployments/github-autodeploys) on the services that autodeploy from `main`.
2. Add Railway Postgres and a Railway Storage Bucket. Enable [Postgres backups](https://docs.railway.com/guides/postgres-backups-restores) before public traffic. In the Postgres shell, run `SELECT current_user, rolsuper, rolcreaterole FROM pg_roles WHERE rolname = current_user;`. Migration `0001` creates `opspilot_app` and needs `CREATEROLE`. Railway's default Postgres image likely permits this, but it has not been verified for this project.
3. Generate a strong URL-safe `APP_DB_PASSWORD`, a strong `JWT_SECRET` (at least 32 characters), and a private `DEMO_PASSWORD` through Railway secrets. Do not paste them into GitHub, issues, chat, or committed files. Use a replacement OpenRouter key only after rotating the key previously shared in chat. Keep `LLM_PROVIDER=mock` for the first hosted smoke test. Reserve the web service's public domain before starting the API, so its exact `https://` origin can be set as `WEB_ORIGIN`.
4. Create a **migration job** from `infra/api.Dockerfile` with no public domain and an owner-only `DATABASE_OWNER_URL` referencing Railway Postgres, plus `APP_DB_PASSWORD` and `DEMO_PASSWORD`. Use start command `sh -c 'alembic upgrade head && python /workspace/scripts/seed.py'`, set restart policy to Never, and keep GitHub autodeploy disabled. Deploy it manually from the intended commit and inspect a successful exit before starting the API and worker. This seed creates two fictional demo accounts. Later seed runs preserve existing passwords and roles unless `RESET_DEMO_CREDENTIALS=1` is explicitly set. Railway service deployments do not provide a migration gate merely because they share a repository; [Wait for CI alone does not order migrations](https://docs.railway.com/deployments/github-autodeploys).
5. Create a private **API** service from `infra/api.Dockerfile`. Set `PORT=8000`, `ENVIRONMENT=staging`, `COOKIE_SECURE=true`, `WEB_ORIGIN` to the exact public web origin, and `JWT_SECRET`. Set `DATABASE_URL` to a `postgresql+psycopg://` URL for the restricted `opspilot_app` role, using Railway Postgres host, port, database, and the URL-safe `APP_DB_PASSWORD`. Configure the bucket variables below. Set `MAX_DOCUMENTS_PER_ORG` to a small demo cap (the default is 100). Do **not** give the API the owner database URL or an OpenRouter key. Use `/readyz` as the deployment health path. The image listens on Railway's `PORT` and runs as a nonroot user.
6. Create a private **worker** service from `infra/api.Dockerfile` with start command `python -m app.worker`. Give it the same restricted DB and bucket settings, `ENVIRONMENT=staging`, `COOKIE_SECURE=true`, `WEB_ORIGIN`, `JWT_SECRET`, and `LLM_PROVIDER=mock`. Do not assign it a public domain. Keep the OpenRouter key only on this service when live extraction is enabled.
7. Configure the public **web** service from `infra/web.Dockerfile`. Set `API_INTERNAL_URL=http://${{api.RAILWAY_PRIVATE_DOMAIN}}:8000`, substituting the actual API service reference shown in Railway. No API URL is embedded into the browser build. Give only the web service a public domain; use `/login` as its deployment health path. Set the API and worker `WEB_ORIGIN` to that domain's exact `https://` origin.

For both API and worker, map the Railway Bucket's [reference variables](https://docs.railway.com/storage-buckets) to:

| OpsPilot variable | Railway Bucket variable | Setting |
| --- | --- | --- |
| `S3_BUCKET` | `BUCKET` | Bucket name |
| `S3_REGION` | `REGION` | Bucket region |
| `S3_ENDPOINT_URL` | `ENDPOINT` | Full S3 endpoint |
| `S3_ACCESS_KEY_ID` | `ACCESS_KEY_ID` | Secret reference |
| `S3_SECRET_ACCESS_KEY` | `SECRET_ACCESS_KEY` | Secret reference |
| `S3_ADDRESSING_STYLE` | Bucket Credentials tab | `virtual` for new Railway Buckets; older buckets may require `path`; local S3Mock uses `path` |

The migration job needs only the database owner URL and demo bootstrap secrets; it does not need bucket or model credentials. The API and worker must not receive `DATABASE_OWNER_URL`.

## Release order and recovery

For the first release, wait for the GitHub CI checks to pass on one commit. Deploy the migration job from that commit and confirm success, then deploy the API and worker, then the web service. Run the hosted browser smoke below before sharing the URL. Record the commit SHA and Railway deployment IDs; after the hosted check passes, create an annotated Git tag such as `demo-v0.1.0` on that exact commit. Keep application autodeploy disabled until the migration-first sequence is automated or every schema change has been reviewed for compatibility with the previous app image.

Before a later schema migration, make a Postgres backup and verify the migration job's commit. If an app release fails, [Railway's Rollback action](https://docs.railway.com/deployments/deployment-actions) restores a previous image and its variables, subject to the plan's image retention period. It does **not** reverse database migrations or remove data written by the new version. Roll back the web, API, and worker to compatible versions, and restore the database only through an explicit, tested recovery plan. If the older image has expired, Railway's Redeploy action rebuilds from the selected deployment's source. Keep the Git tag and CI result as the long-lived release record.

The API release image installs versions from `infra/api-requirements.lock`. CI uses the same constraints and runs [pip-audit](https://github.com/pypa/pip-audit) against the pinned runtime set. Run `make lock-api` to resolve and write a new lock in a Python 3.12 Linux container, then run the audit, release-image build, backend tests, and browser smoke before releasing a dependency update. The lock pins versions but does not yet pin wheel hashes or the base-image digest.

## Verify the hosted app

Use the public web URL in a browser. Sign in with the private demo password, download the fictional invoice from the Inbox, upload it, wait for `needs_review`, inspect the evidence, and sign out. Run the browser smoke against the public URL with `WEB_BASE_URL` and `DEMO_PASSWORD` supplied through your local environment. The browser smoke exercises `/api` through the web service, including cookies and PDF upload; the API can stay private.

Check the API, worker, and web logs for errors. Test one failed-document retry, restart the worker during a queued extraction, and confirm the job recovers. Record the URL, date, CI run, and outcome in `PROGRESS.md` only after these checks pass. Keep the model on `mock` until this infrastructure path is stable; then configure a **new** OpenRouter key only on the worker and run the live synthetic eval before making accuracy claims.

Railway [healthchecks gate new deployments](https://docs.railway.com/deployments/healthchecks), but do not continuously monitor the worker or bucket. Add uptime/worker alerts and a pending-extraction-age check for anything beyond a private demo. Configure [usage alerts](https://docs.railway.com/pricing/cost-control); usage varies with always-on services, bucket storage, and model calls.

## Single-VM path

The development Compose file is intentionally bound to localhost and includes services that should not be internet-facing. Before using a VM, create a separate production Compose stack with only web/API/worker, a managed or hardened Postgres and S3 bucket, a TLS reverse proxy, backups with a restore test, restricted firewall rules, non-demo credentials, and monitoring. This path remains unimplemented.

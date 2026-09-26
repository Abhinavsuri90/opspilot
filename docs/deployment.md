# Deploy OpsPilot on Render

This runbook prepares a real organization signup deployment without seeded accounts. The repository contains a [Render Blueprint](../render.yaml), but no hosted URL, Render database, or external bucket has been verified in this session. Successful local checks do not establish hosted reliability or model accuracy.

## Services and release order

| Component | Render service | Configuration |
| --- | --- | --- |
| Website | Public web service | `infra/web.Dockerfile`; homepage and all seven other pages; only public entry point |
| API | Private service | `infra/api.Dockerfile`; restricted database role |
| Extraction | Background worker | Same API image; `python -m app.worker` |
| Database | Managed Render Postgres | Create before applying the Blueprint; same region as services |
| PDFs | External private S3-compatible bucket | Cloudflare R2 or AWS S3; never a public invoice bucket |

The Blueprint places the three application services in Singapore. Pick another region before creation if appropriate, and place Postgres there too. Private services accept traffic from the private network; workers process jobs without accepting incoming connections. Our worker polls the Postgres outbox, so Redis is not needed. [Render private services](https://render.com/docs/private-services), [background workers](https://render.com/docs/background-workers).

The order is **database → migrations → private API and worker → web → hosted acceptance tests**. Automatic Git deploys are disabled in the Blueprint to keep that order explicit. Review the paid service and database estimate in Render before provisioning; the file does not create free substitutes for the private API or worker.

### One website, separate application services

The eight frontend pages deploy together as `opspilot-web`: `/`, `/register`, `/login`, `/dashboard`, `/inbox`, `/review`, `/insights` and `/admin`. You do not create a Render service for each page. The homepage is public; workspace data requires an approved organization membership, and Admin requires an admin role.

The backend is required for accounts, permissions, stored invoices, reviews and insights. `opspilot-api` runs privately, while `opspilot-worker` handles queued extraction. The web service forwards browser requests through its same-origin `/api` proxy to the private API. No public backend domain or browser-side API secret is needed for this topology.

For the first deployment, create a new Render project, connect GitHub and grant access to `Abhinavsuri90/opspilot`. Complete the database and bucket steps below before applying the application Blueprint. Keep every service in that project and the same selected region.

## 1. Create the database and bucket

Create a Render Postgres database named `opspilot` using PostgreSQL 16, in the selected region. Choose a paid database plan for persistent hosting and backup recovery. In **Connect**, find the external owner URL for the one-off migration and the internal host/database for runtime services. Temporarily allow only your own IP for external database access. Render provides separate internal and external URLs; services in the same account and region should use the internal URL. [Render Postgres connections](https://render.com/docs/postgresql-creating-connecting).

The initial migration creates `opspilot_app`, a restricted database login. Check the owner connection before migration:

```sql
SELECT current_user, rolcreaterole
FROM pg_roles
WHERE rolname = current_user;
```

`rolcreaterole` must be true, or the owner must otherwise have permission to create the application role. Stop and resolve permissions if the migration fails; assigning the owner credential to the API would bypass the intended isolation. Creating a role requires the corresponding Postgres privilege. [Postgres CREATE ROLE](https://www.postgresql.org/docs/17/sql-createrole.html). Directly created application roles are not Render-managed default credentials. [Render database credentials](https://render.com/docs/postgresql-credentials).

Create a private bucket such as `opspilot-invoices-production`. For R2, create bucket-scoped credentials with object read/write permission. Copy the S3 endpoint, Access Key ID, and Secret Access Key into Render's secret inputs. Typical R2 settings are:

```dotenv
S3_BUCKET=opspilot-invoices-production
S3_REGION=auto
S3_ENDPOINT_URL=https://YOUR_ACCOUNT_ID.r2.cloudflarestorage.com
S3_ADDRESSING_STYLE=path
```

Use the endpoint actually shown for your bucket, including any jurisdiction-specific endpoint. Do not use a public `r2.dev` download URL as the S3 API endpoint. [Cloudflare R2 S3 API](https://developers.cloudflare.com/r2/api/), [R2 boto3 configuration](https://developers.cloudflare.com/r2/examples/aws/boto3/).

## 2. Run migrations once, with separate credentials

Use Docker Desktop on your computer, from the intended Git commit. Keep the migration inputs in a temporary file outside the repository; Docker reads the values without placing them in the command arguments. Generate a strong URL-safe `APP_DB_PASSWORD` in your password manager. Keep that value because the runtime database URL will use it.

```bash
cd /Users/abhinavsuri/Desktop/opspilot
docker build --target runtime -f infra/api.Dockerfile -t opspilot-migrate .
install -m 600 /dev/null /tmp/opspilot-render-migration.env
open -e /tmp/opspilot-render-migration.env
```

In that local editor, enter these three names with your own values:

```dotenv
DATABASE_OWNER_URL=postgresql://RENDER_OWNER:OWNER_PASSWORD@EXTERNAL_DB_HOST/opspilot?sslmode=require
APP_DB_PASSWORD=YOUR_GENERATED_URL_SAFE_PASSWORD
ENVIRONMENT=development
```

`ENVIRONMENT=development` here only lets the migration command import settings without runtime storage configuration. This container runs Alembic and exits; it does not run the web app. URL-encode special characters in database URL passwords, or use a URL-safe generated password. The actual database name may differ from `opspilot`; copy it from Render.

```bash
docker run --rm --env-file /tmp/opspilot-render-migration.env opspilot-migrate alembic upgrade head
docker run --rm --env-file /tmp/opspilot-render-migration.env opspilot-migrate alembic current
rm /tmp/opspilot-render-migration.env
```

Proceed after `alembic current` reports the repository's head revision. Do not run `scripts/seed.py` against the hosted database. Close external database access again after the migration; reopen your own IP temporarily for future migrations. A later migration uses the same separate process after a backup.

## 3. Apply the application Blueprint

In Render, choose **New → Blueprint**, connect this repository, and select the tested commit's branch and `render.yaml`. Leave the repository root as the Docker build context. The final API Docker stage is the nonroot runtime image.

Supply these values when prompted:

| Variable | Value and destination |
| --- | --- |
| `DATABASE_URL` | API: internal database URL with username **`opspilot_app`**, its generated password, and `?sslmode=require` |
| `WEB_ORIGIN` | API: exact public HTTPS web origin, with no path or trailing slash |
| `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL` | API: private bucket settings above |
| `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY` | API: private object credentials |
| `LLM_PROVIDER` | Worker defaults to `rules` for supported labeled-text invoices; choose `openrouter` for model extraction after setting its credentials |

For example, the runtime database URL has the shape `postgresql://opspilot_app:APP_PASSWORD@INTERNAL_DB_HOST/opspilot?sslmode=require`. Do not paste the Render owner connection string into this field. The application rejects a production database URL whose username is not `opspilot_app`.

The Blueprint generates `JWT_SECRET` on the API and references the same value from the worker. It also copies API database/storage settings to the worker. `DATABASE_OWNER_URL` and `APP_DB_PASSWORD` belong only to the separate migration operation. The web service needs only the API's private address, which the Blueprint supplies automatically.

If the final web hostname is unknown before the first deploy, enter your intended HTTPS origin, then replace it with the exact assigned `onrender.com` origin in the API settings once Render shows it. Sync/redeploy the worker to refresh its reference too. Finish this before trying signup. A mismatch returns a request-origin error. Changing to a custom domain later also requires updating this origin.

Render prompts for `sync: false` variables on initial Blueprint creation only. New variables added to an existing Blueprint need to be entered manually; `sync: false` does not work inside environment groups. References refresh on Blueprint sync. [Render Blueprint environment variables](https://render.com/docs/blueprint-spec), [secrets configuration](https://render.com/docs/configure-environment-variables).

## 4. Choose extraction mode

`rules` runs a deterministic extractor for labeled text invoices without external model calls. Signup, persistence, permissions, review, and sharing all use the real application and database. For real model extraction, add a newly issued `OPENROUTER_API_KEY` and an available `OPENROUTER_MODEL` ID to **the worker only**, set its `LLM_PROVIDER=openrouter`, and redeploy it. Verify the model's current ID and support for the requested structured response on OpenRouter before choosing it; the repository default is not a measured best model. Revoke the key previously posted in chat before using a replacement.

The live provider sends PDF text to the model service and can incur charges. Upload a fresh, fictional invoice and confirm its output before using private business invoices. Uploaded PDFs need selectable text; scanned images require OCR, which is not implemented. Invoice questions use stored, authorized invoice data; do not describe them as unlimited general-purpose AI chat.

## 5. Verify the hosted application

Render's private-service health probe is TCP only. The Blueprint therefore configures `/login` as the public web health path and does not pretend it can configure an HTTP `/readyz` probe for the private API. [Render health checks](https://render.com/docs/health-checks).

After API startup, run this in the **API service's Render Shell**:

```bash
python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5).read().decode())"
```

Expect `{"status":"ready"}`. The public Next.js `/api` proxy intentionally forwards only `/v1` routes, so `/api/readyz` is not a public health URL.

In the public browser:

1. Open the public HTTPS origin at `/`. Check the homepage, section links, FAQ and mobile layout. Follow the owner, member and reviewer entry links; confirm the expected registration mode and requested role are selected. Test the Sign in link and navigation back to the homepage.
2. Use the owner entry to create a new organization and its admin account. Confirm Dashboard and Admin load with no seeded accounts.
3. In a separate browser profile, use the reviewer entry and request membership in that organization. Login must say approval is pending. Selecting a reviewer link must not grant access before approval.
4. In Admin, approve the applicant; sign in again in the applicant's profile. Confirm the role and visible documents are correct.
5. Upload a new text-layer PDF. Wait for extraction, inspect the original PDF and evidence, categorize it, add a comment, and record a review decision with its reason where required. Confirm Inbox, Review and Insights all load from their own URLs.
6. Ask for the amount and count awaiting review. Compare the answer with the visible authorized invoices and currencies.
7. Use the member entry to request another account, approve it, and exercise workspace and restricted sharing. Verify the user cannot retrieve an unshared invoice by URL or ID or perform admin actions. Suspend the account in Admin and confirm its existing session loses access.
8. Create a second organization; verify its invoices, members, categories, comments, and totals are isolated from the first organization.
9. Restart the worker while an extraction is queued; verify it completes after the worker returns. Sign out and confirm protected pages require login.

Record the actual public URL, Git SHA, date, extraction mode, and outcomes in the project handoff only after these checks pass. The old demo-account smoke script is not a substitute for this fresh signup acceptance flow.

## Operations and later releases

Keep GitHub checks passing on the exact release commit. Before a schema change, make and verify a database backup, run migrations with the owner-only process, then deploy API, worker, and web. Render supports a pre-deploy command, but this Blueprint deliberately keeps the owner credential out of runtime services; moving migrations into an automated pipeline needs a separate protected migration job. [Render deploy lifecycle](https://render.com/docs/deploys).

An image rollback does not undo schema migrations or newly written invoices. Retain compatible release images and test database and object recovery. Configure spend alerts, web uptime checks, extraction backlog monitoring, and edge rate limits for signup/login before inviting a wider audience. The database signup throttle remains shared across all API instances, but a proxy's network address can represent many users.

Email verification, self-service password recovery, a measured live-model evaluation, scanned-PDF OCR, and a verified hosted backup/restore remain deployment/product gaps. Hosting the services does not complete those workflows.

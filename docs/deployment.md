# Deploy OpsPilot

## Current budget: free hosting only

The owner requires a $0 plan and permits card verification only. **The existing `render.yaml` provisions paid application services; do not apply it for this budget.** Render Free Postgres also expires after 30 days, so the database already created is not a durable free hosting solution. [Render free limits](https://render.com/docs/free).

### Alternatives checked on 2026-09-26

| Option | Fit for OpsPilot | Limits that affect the experience |
| --- | --- | --- |
| Oracle Always Free A1 VM | Recommended if signup and free capacity succeed. Run Next.js, FastAPI, the extraction worker and PostgreSQL on one VM, with private object storage. | Self-managed server and database; capacity may be unavailable; idle instances may be reclaimed. |
| Render Free web + Supabase Free database/storage | Fallback requiring a new image that supervises the three application processes together. | Render sleeps after 15 idle minutes and takes about a minute to wake. Extraction stops while asleep. Supabase can pause inactive projects. |

Oracle currently documents **2 OCPUs / 12 GB memory** in its A1 Always Free allowance, with 200 GB total boot/block storage in the home region. Keep the account on Free Tier and resources within Always Free limits. Card verification may place a temporary authorization hold. Free Tier has no uptime SLA. [Oracle resource limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), [signup and card FAQ](https://www.oracle.com/cloud/free/faq/), [account upgrade rules](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm).

Supabase Free includes a 500 MB database, 1 GB files and 5 GB regular egress; projects pause after a week of inactivity. Combined Render hosting needs testing under its memory limit and changes for Supabase's restricted-role pooler username and S3 compatibility. Disable Supabase Data API if using this alternative: OpsPilot uses its own API and authorization. [Supabase pricing](https://supabase.com/pricing), [Postgres connections](https://supabase.com/docs/guides/database/connecting-to-postgres), [Data API security](https://supabase.com/docs/guides/api/securing-your-api).

Both alternatives preserve the existing pages and workflows. Neither is a verified hosted deployment yet. Oracle production files are in `infra/oracle/`; the root Compose file remains for development. PostgreSQL is self-managed on the VM, not an Oracle managed database product. The setup still needs actual Oracle capacity, credentials, public TLS, storage and browser acceptance checks.

**Next step:** register at [Oracle Cloud Free Tier](https://signup.cloud.oracle.com/), remain on the free account, and check whether `VM.Standard.A1.Flex` capacity is available in the chosen home region. Confirm that before changing deployment topology. If it is unavailable, revisit the managed fallback. No hosted resources have been provisioned by this work.

Use `LLM_PROVIDER=rules` to avoid model API charges; this supports labeled text invoices and does not provide general AI extraction. Optional OpenRouter usage has separate model costs and limits.

## Oracle walkthrough

Run commands marked **Mac** in your local Terminal; commands marked **VM** run after SSH connects to Ubuntu. Replace uppercase placeholders with your own nonsecret names/IPs. Never enter card details, SSH private keys or service secrets in chat. All eight pages use one public hostname.

### A. Account, compartment and network

1. Complete [Oracle signup](https://signup.oraclecloud.com/), including email and card verification. Choose the home region carefully: it cannot be changed. Stay on the free account and provision Always Free resources rather than services funded only by trial credits. [Official signup](https://docs.oracle.com/en-us/iaas/Content/GSG/Tasks/signingup_topic-Sign_Up_for_Free_Oracle_Cloud_Promotion.htm).
2. Under **Identity & Security → Compartments**, create `opspilot` under the root tenancy. Select this compartment when creating the VM, network and bucket.
3. Under **Networking → Virtual cloud networks → Create VCN**, create `opspilot-vcn`, CIDR `10.0.0.0/16`, DNS enabled, IPv6 disabled. Use the plain creation form; the Internet Connectivity wizard creates additional resources.
4. Inside the VCN create an enabled Internet Gateway `opspilot-internet`. Add a default route: destination `0.0.0.0/0`, target type Internet Gateway, target `opspilot-internet`.
5. Create regional **public** subnet `opspilot-public`, CIDR `10.0.0.0/24`, using that route table, default DHCP options and default security list. [Oracle public network reference](https://docs.oracle.com/en-us/iaas/Content/Network/Tasks/scenarioa.htm).
6. Edit the attached security list. Stateful TCP ingress: port22 from **your current public IPv4/32**; ports80 and443 from `0.0.0.0/0`; source ports All. Replace any broader existing SSH allow rule. Preserve standard ICMP and outbound rules. Do not expose3000,8000 or5432. If your home IP changes, update the SSH source rule.

### B. Create the server and connect

Open **Compute → Instances → Create instance**:

| Field | Setting |
| --- | --- |
| Name / compartment | `opspilot` / `opspilot` |
| Image | Ubuntu24.04 ARM64 platform image marked Always Free eligible |
| Shape | Virtual machine → Ampere → `VM.Standard.A1.Flex` |
| CPU / memory | 2 OCPUs /12GB; total allowance across your A1 instances |
| Boot volume | Default about50GB, default Balanced performance |
| Network | Existing `opspilot-vcn` and `opspilot-public` |
| Public IPv4 | Automatically assign |
| SSH | Generate a key pair; download and retain the private key |

Use Oracle-managed encryption and no paid marketplace image or extra volumes. A selectable shape does not guarantee capacity. Proceed when the instance reaches **Running**. If creation says out of host capacity, try another availability domain in the same region if offered, or retry later. A1 free capacity and uptime are not guaranteed; do not switch to a paid shape to bypass this gate. [Current instance creation](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/launchinginstance.htm), [free limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

**Mac:** replace the downloaded filename and VM public IP:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
cp ~/Downloads/YOUR_DOWNLOADED_KEY.key ~/.ssh/opspilot-oracle.key
chmod 600 ~/.ssh/opspilot-oracle.key
ssh -i ~/.ssh/opspilot-oracle.key ubuntu@YOUR_VM_PUBLIC_IP
```

Keep the key private. The terminal prompt should now show the Ubuntu server. Preserve OCI's firewall rules; do not enable UFW or flush iptables. [OCI Ubuntu firewall warning](https://docs.oracle.com/en-us/iaas/Content/Compute/known-issues.htm#ufw).

### C. Free hostname

Sign in at [DuckDNS](https://www.duckdns.org/), create an available name such as `opspilot-yourname`, and explicitly set its IPv4 address to the **VM public IP**, replacing any address detected from your Mac. Leave IPv6 blank for this setup. Your hostname becomes `opspilot-yourname.duckdns.org`. Keep it pointed at the VM if the public IP changes. Caddy obtains and renews HTTPS certificates when DNS and ports80/443 work. [Caddy HTTPS requirements](https://caddyserver.com/docs/automatic-https).

### D. Private PDF bucket and its credentials

1. Select the VM's home region. Open **Storage → Object Storage & Archive Storage → Buckets** in compartment `opspilot`.
2. Create `opspilot-invoices`: Standard storage, namespace scope if prompted, Oracle-managed encryption, no public access, auto-tiering/events/versioning off initially. Track total storage; keep Standard data below10GB for the conservative trial-to-free allowance. Versioning and backup copies also use storage.
3. Open **Identity & Security → Domains → Default → User management**. Create group `opspilot-storage` and a dedicated user `opspilot-storage`; assign that group only. Do not grant Administrators. Enter a user-controlled email if required.
4. Under **Identity & Security → Policies**, create `opspilot-storage-access` in the root tenancy. Use the manual editor with this statement (names must match):

```text
Allow group 'Default'/'opspilot-storage' to manage objects in compartment opspilot where all {target.bucket.name='opspilot-invoices', any {request.permission='OBJECT_CREATE', request.permission='OBJECT_READ', request.permission='OBJECT_OVERWRITE'}}
```

This allows the app's object put/get operations without bucket administration, listing or deletion. [Object permission reference](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/objectstoragepolicyreference.htm).

5. Open the dedicated user's **Customer secret keys → Generate secret key**. Save the Secret Key immediately, then copy the corresponding Access Key from the list. These are different from an API signing key or Auth Token. [Customer key creation](https://docs.oracle.com/en-us/iaas/Content/Identity/access/to_create_a_Customer_Secret_key.htm).
6. Find **Object Storage Namespace** in the profile menu's **Tenancy** page. Record the bucket's region identifier, such as `ap-mumbai-1`. The endpoint for commercial regions is:

```text
https://YOUR_NAMESPACE.compat.objectstorage.YOUR_REGION_IDENTIFIER.oci.customer-oci.com
```

Do not append the bucket name. The older `.oraclecloud.com` form remains supported. [Oracle endpoints](https://docs.oracle.com/en-us/iaas/Content/Object/Concepts/dedicatedendpoints.htm). The current SDK's checksum uploads are supported by [OCI's S3 API](https://docs.oracle.com/en-us/iaas/Content/Object/Tasks/s3compatibleapi_topic-Amazon_S3_Compatibility_API_Support.htm); an actual scoped round trip remains required below.

### E. Install Docker on the VM

**VM**, fresh Ubuntu24.04 platform image:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: arm64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

These fixed `noble`/`arm64` values are for the specified Ubuntu24.04 A1 image. For another OS/version follow [Docker's matching installation instructions](https://docs.docker.com/engine/install/ubuntu/).

### F. Download and configure OpsPilot

**VM:**

```bash
cd /home/ubuntu
git clone https://github.com/Abhinavsuri90/opspilot.git
cd opspilot
python3 infra/oracle/init_env.py
```

The helper asks for hostname, region identifier, S3 endpoint, private bucket, access key and secret key. Keys are hidden while typing. It creates `infra/oracle/.env` with permissions600, distinct random database passwords, a JWT secret and the connector credential encryption key; it refuses to overwrite existing configuration. It is excluded from Git and Docker builds. Back up this file privately. Do not regenerate database passwords after initializing the persistent volume.

`infra/oracle/ops` is a wrapper that consistently selects the production Compose file and private environment. Commands below run from `/home/ubuntu/opspilot`. Never run the root `make demo` on this server.

### G. Build, migrate and start

```bash
sudo ./infra/oracle/ops config --quiet
sudo ./infra/oracle/ops build api web
sudo ./infra/oracle/ops up -d --wait postgres
sudo ./infra/oracle/ops run --rm migrate
sudo ./infra/oracle/ops run --rm migrate alembic current
sudo ./infra/oracle/ops up -d --wait api worker web caddy
sudo ./infra/oracle/ops ps
```

The current migration head is `0005`. Stop on a failed command and inspect its error before continuing. `config --quiet` validates without printing secrets. Plain `config` renders credentials and should not be pasted into support chat. The API and worker use only `opspilot_app`; the one-shot migration uses the owner role. PostgreSQL and TLS state use separate persistent volumes. The worker runs continuously while the VM is available; process status alone does not prove extraction progress.

### H. Verify the actual deployment

**VM:**

```bash
sudo ./infra/oracle/ops exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/readyz', timeout=5).read().decode())"
sudo ./infra/oracle/ops exec -T api python - < infra/oracle/check_storage.py
```

Expect `{"status":"ready"}` and `Storage PUT/GET passed.` The storage check writes one tiny synthetic PDF and reports its key. Delete that exact diagnostic object in the admin bucket console. Do not use `list_buckets` as a test; the restricted key intentionally cannot list buckets.

**Mac / browser:** open `https://YOUR_HOSTNAME/` and `/login`. There must be a valid public certificate, without a certificate exception. All eight pages are listed in README. Test a fresh organization, pending reviewer request, admin approval, upload, completed extraction, full PDF, category, comment, decision and Insights totals. Repeat from another organization to verify denied invoice access. Never claim deployment complete based only on the homepage or container health.

### I. Backups, maintenance and updates

**VM:** make a database backup and allow only the SSH owner to retrieve it:

```bash
sudo ./infra/oracle/backup.sh /home/ubuntu/opspilot-backups
sudo chown -R ubuntu:ubuntu /home/ubuntu/opspilot-backups
```

**Mac:** use the filename printed by the script:

```bash
scp -i ~/.ssh/opspilot-oracle.key ubuntu@YOUR_VM_PUBLIC_IP:/home/ubuntu/opspilot-backups/YOUR_BACKUP_FILE.dump ~/Downloads/
```

Move the copy into encrypted private storage. The dump contains account records and password hashes; it is sensitive. It does not contain PDFs or database-role passwords. Back up bucket objects and `.env` separately. One VM is a single failure domain; a dump left on that VM is insufficient. Set a regular backup schedule and verify restore before relying on it for business data.

For a restore drill **on the same server**, after a backup, restore into an unused temporary database. Run once; do not reuse a name containing real data:

```bash
sudo ./infra/oracle/ops exec -T postgres createdb -U opspilot_owner -T template0 opspilot_restore_check
sudo ./infra/oracle/ops exec -T postgres pg_restore -U opspilot_owner -d opspilot_restore_check --exit-on-error < /home/ubuntu/opspilot-backups/YOUR_BACKUP_FILE.dump
sudo ./infra/oracle/ops exec -T postgres psql -U opspilot_owner -d opspilot_restore_check -c 'SELECT version_num FROM alembic_version; SELECT count(*) FROM documents;'
```

The existing cluster already has the application roles. A replacement server needs those roles recreated first; running migrations on its empty live database creates them. Restore the dump into an empty replacement database with those roles available; do not restore over the migration-created tables. Verify counts, permissions, PDF objects and app behavior before switching traffic. Clean up the temporary drill database only after confirming its name and checks.

Logs and stop/start:

```bash
sudo ./infra/oracle/ops logs --tail=100 api worker caddy
sudo ./infra/oracle/ops stop
sudo ./infra/oracle/ops up -d --wait api worker web caddy
```

For a planned update, first review the incoming release and schema changes. Pull/build while the current version is still running, then stop serving/processing writes, take a backup, migrate and restart:

```bash
git pull --ff-only
sudo ./infra/oracle/ops build api web
sudo ./infra/oracle/ops stop caddy web worker api
sudo ./infra/oracle/backup.sh /home/ubuntu/opspilot-backups
sudo ./infra/oracle/ops run --rm migrate
sudo ./infra/oracle/ops up -d --wait api worker web caddy
```

Repeat hosted acceptance afterward. If a migration fails, keep traffic stopped until repaired; rolling back app images alone does not reverse a schema change. `down -v` deletes persistent data and is not a normal stop command. Do not use volume pruning against this deployment. Monitor free quotas, disk usage, OS updates, errors and certificate renewal; image builds and old backups can fill the50GB boot disk.

### Troubleshooting

| Symptom | Check |
| --- | --- |
| SSH timeout | Running instance, correct public IP, public subnet/default Internet Gateway route, current Mac IPv4/32 in ingress22 |
| SSH permission denied | Ubuntu username and the matching downloaded private key, permissions600 |
| Browser timeout | DuckDNS points to VM, ingress80/443, Caddy logs, Docker forwarding rules; preserve Oracle firewall rules |
| TLS failure | Correct DNS and public ports; no incorrect AAAA record; persistent Caddy data; inspect logs before repeated retries |
| 502 | API/web health and logs; migrations must finish before API readiness |
| Upload/extraction fails | Storage round trip, bucket policy, endpoint/region, worker logs, selectable text in PDF |
| Login pending | Organization admin must approve that membership |
| Login origin error | Hostname used in browser matches `OPSPILOT_DOMAIN`; recreate API/worker after an environment change |
| Out of free capacity | Retry another availability domain in the same home region or use the evaluated fallback; no paid upgrade |

## Paid Render deployment reference

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

# Deployment readiness review

Reviewed 2026-09-26 for the organization onboarding and invoice collaboration release. The implementation now supports user-created workspaces and governed membership. This review covers code and local testing; no public Render URL, hosted database, or real object bucket has been verified.

## Current product scope

| Area | Implemented behavior |
| --- | --- |
| Organization signup | A person creates an organization and becomes its active administrator. A default invoice currency and extraction workflow are created atomically. |
| Joining a company | Public organization search exposes bounded name/ID choices. Members and reviewers submit pending requests; a valid password alone does not grant access. |
| Admin access controls | Administrators approve or reject requests, choose member/reviewer/viewer roles, suspend accounts, and restore access. Member approval cannot grant admin privileges or remove the existing admin. |
| Account ownership | Reusing an existing email requires its existing password. Signup never replaces another account's password. |
| Authentication and isolation | Every protected request checks active membership in Postgres. Tenant RLS protects records, and suspension waits for an in-flight authorized transaction before completing. |
| Invoice intake | Text-layer PDFs are validated, stored privately, deduplicated within an organization, and queued through a transactional Postgres outbox. Failed extraction has bounded retry. |
| Document review | Authorized reviewers inspect the original PDF and extraction evidence, verify amount/currency, categorize invoices, approve or reject with history, and reopen completed reviews. Original extraction evidence is preserved. |
| Team collaboration | Comments, administrator reviewer assignment, workspace visibility, and restricted sharing with selected active members. Admins, the uploader, and assigned reviewer retain access under the documented rules. |
| Categories | Administrators create, edit, and archive categories. Reviewers use the organization's available categories. |
| Totals and questions | Accessible invoice counts, status/category summaries, and verified totals separated by currency. Structured invoice questions cite stored evidence; unsupported requests are explicitly declined. |
| Browser flow | Public homepage, login, registration, Dashboard, Inbox, Review, Insights, and Admin, with a same-origin API proxy and TanStack Query updates. Owner/member/reviewer links preselect signup forms; the API owns access decisions. |

Money totals include manually verified amounts with explicit currencies. Unverified invoices are counted separately, and amounts in different currencies are not added together. Questions support the implemented invoice fields and current summaries; they are not a general-purpose finance assistant or date/vendor-filtered analytics engine.

## Concrete protections and deployment changes

| Risk | Current control |
| --- | --- |
| API or worker accidentally uses unrestricted database credentials | Runtime uses `opspilot_app`; production settings reject owner usernames. Only the separate migration operation receives `DATABASE_OWNER_URL`. |
| Pending or suspended users reuse a signed session | Authentication checks current membership on every request. A row lock orders member suspension against requests already in progress. |
| Administrators act on another company's membership | Tenant context, scoped member lookup, RLS, and serialized decisions keep changes inside the current organization. |
| Restricted invoice leaks through another route | Lists, detail, PDF download, collaboration endpoints, and aggregate/question queries apply document access checks. Possession of a document ID or identical PDF does not grant access. |
| Concurrent invoice edits overwrite a review | Invoice mutations lock the document and compare metadata versions; stale changes return a refresh conflict. |
| Browser cookies fail across service domains | The public Next.js server proxies `/api/v1` to the private API. Cookies, origin checks, and request IDs stay on the expected browser flow. |
| Requests exhaust authentication or parsing resources | Shared Postgres login/signup counters and request-size limits guard the API. Edge rate limiting remains a hosted deployment requirement. |
| Worker restart loses queued invoices | Durable outbox jobs, claim validation, stale-claim recovery, and bounded attempts support recovery. Worker scans rotate tenant order. |
| Application starts before migrations are applied | The release procedure runs migrations first and checks `/readyz`. The Render Blueprint disables automatic deploys until ordering is operated deliberately. |
| Blueprint leaks model or migration secrets to the website | Web receives only the private API address. The model key belongs only to the worker; owner migration credentials stay outside all three runtime services. |
| Private API health is overstated | Render private services use TCP probes. The runbook separately checks API `/readyz`; public `/login` health alone does not validate storage or extraction. |
| Image rollback is treated as data rollback | Deployment instructions separate application rollback from database/object recovery. |

See [render.yaml](../render.yaml) and the [Render deployment runbook](deployment.md). The Blueprint defines the public web service, private API, and background worker. Provision managed Render Postgres and a private external S3-compatible bucket first; run migrations without seeding hosted accounts. Creating the first organization through registration provides its administrator.

## Verification evidence

- The later public-entry release passed web lint/types, all 16 unit tests, production Docker build, public navigation/role-selection browser checks, 390/320 px landing checks and the complete fresh-company workflow again. Landing and authentication screens were visually reviewed; login and registration fit 320 px. These are local results, not evidence of a hosted Render deployment.

- The new onboarding suite passed against the local Docker Postgres database with migrations through `0005`: **18 passed**. It exercises signup validation, active admin/workflow creation, bounded literal organization search, pending login denial, approval, rejection, suspension and restoration, existing-email ownership, admin protection, tenant isolation, and suspension ordering against an in-flight authenticated transaction.
- Ruff passed for the owned onboarding/authentication code, migration, models, throttle, and onboarding tests.
- The Render YAML parses and passed a local structural check against Render's published schema. This is configuration validation, not a successful Render deployment.
- The expanded local release passed 80 Postgres API tests, 16 web tests, lint/types, production builds and the complete fresh-company browser flow including two-page PDF rendering and concurrent editor conflicts. Current results and small local latency samples are recorded in `CONTEXT.md`, `PROGRESS.md` and `SYSTEM_DESIGN.md`. Application commit `ad55d0f` passed [all four CI jobs](https://github.com/Abhinavsuri90/opspilot/actions/runs/36241455074). Check the latest commit's checks before deployment.

Reproduce the focused integration test after local migrations:

```bash
docker compose run --rm -v "$PWD/apps/api:/workspace/apps/api" admin pytest tests/test_onboarding.py -q
```

Test fixtures remove only organizations and users they created. Never run development integration tests against the production database.

## Remaining gates before wider use

| Gate | What still needs evidence or implementation |
| --- | --- |
| Hosted deployment | Provision the owner's Render database/services and private bucket; run owner-only migrations; configure exact HTTPS origin; verify the public signup, approval, invoice review, and cross-company isolation flow. No hosted URL has been verified. |
| Live extraction | Use a replacement for the key previously shared in chat, select a currently available OpenRouter model, and verify fresh extraction plus a representative accuracy/cost evaluation. Mock-provider success is workflow evidence only. |
| Recovery and operations | Exercise Postgres restore and PDF recovery, worker restart under load, pending-job alerts, uptime checks, and spend limits. |
| Account lifecycle | Email verification, self-service password recovery, admin ownership transfer/additional-admin management, and invitations are not implemented. Public signup currently uses admin approval to govern membership. |
| Privacy lifecycle | Establish document retention/deletion, customer consent for model processing, and operational access policies before accepting sensitive business invoices. |
| Scale and abuse controls | Configure edge per-client signup/login limits, measure concurrent uploads/reviews and large member/invoice histories, and tune database/service capacity. Application peer throttling may group users behind a proxy. |
| Broader invoice processing | Scanned-PDF OCR, structured line-item review, model confidence calibration, and accounting/payment connectors remain outside this release. |
| Independent assurance | Hosted acceptance checks and local regression tests do not replace an independent security assessment or measured production reliability. |

The application now implements onboarding, approval, invoice review, categorization, discussions, sharing, and current totals. Public hosting, account recovery, verified live extraction, and operational recovery still require the gates above.

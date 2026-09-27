# OpsPilot

[![CI](https://github.com/Abhinavsuri90/opspilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Abhinavsuri90/opspilot/actions/workflows/ci.yml)

**An invoice workspace for organizations and their reviewers.** Create a company workspace, approve joining teammates, upload PDFs, inspect original documents, discuss discrepancies and track verified invoice decisions.

Built with Next.js, React, TanStack Query, FastAPI, Postgres row-level security and S3-compatible storage. Extraction, validation and governed actions run asynchronously through a durable Postgres outbox. Optional OpenRouter extraction accepts a configurable model; human review, totals and governance operate independently of model access.

![OpsPilot public landing page](docs/assets/landing.png)

## What works

- Public product homepage with workflow explanations and separate entry points for organization owners, members and reviewers.
- Organization registration and company selection at login/join; admin approval for joining members/reviewers.
- Admin-managed invoice categories and membership approval, role selection, rejection and suspension.
- PDF upload, tenant-specific deduplication, background extraction, source evidence and retry.
- Per-field confidence from six signals (grounding, format, cross-field rules, self-report, with router and memory slots reserved), configurable thresholds, and plain-language reasons for every flagged field.
- Versioned per-organization workflow configuration: document types, typed fields and cross-field rules in a safe rule grammar; new organizations default to reviewing every document.
- Field-level accept and edit as append-only corrections, review tasks with an SLA, a filterable review queue and a per-document timeline.
- Governed actions after approval: one proposal per configured destination with a preview of exactly what will be sent, a per-type policy (auto, needs approval, forbidden), an organization kill switch and shadow mode re-checked immediately before every external call, idempotency keys, retries with backoff and a dead-letter queue with manual retry.
- Connectors with encrypted credentials and connection tests: HMAC-signed webhook, CSV export, Postgres table and Google Sheets.
- Workflow configuration API with YAML import and export, append-only versions and inline validation errors.
- Full PDF viewing with page navigation, zoom, selectable page text and download; reviewer assignment, verified amount/currency and approve/reject/reopen.
- Invoice comments, decision history and authenticated sharing with restricted visibility.
- Dashboard, review queue, category filters, paginated inbox and Insights.
- SQL-backed questions about counts, totals, categories and extracted invoice fields with citations.
- Restricted runtime database role, tenant RLS, optimistic versions and append-only history.

Public deployment is not yet verified. [Oracle Free Tier setup and the paid Render alternative](docs/deployment.md) and [the system design](SYSTEM_DESIGN.md) explain the deployment paths, operational limits and scaling choices.

## Start locally with your own organization

Start Docker Desktop, then run from this directory:

```sh
LLM_PROVIDER=rules OPENROUTER_API_KEY= make up
```

This builds the services, starts Postgres/storage, applies migrations and waits for the application. It creates `.env` from `.env.example` only when missing. It preserves existing data and does **not** create demo accounts.

1. Open [localhost:3300](http://localhost:3300) for the product homepage and choose the organization-owner entry point.
2. Create your organization with a name, unique slug, your email and a password of at least 12 characters. You become the organization admin.
3. In **Admin**, create categories such as Travel, Software or Office supplies.
4. In a separate browser profile/private window, open the homepage and choose the member or reviewer entry point. Select your organization and submit a join request.
5. As admin, approve the request in Admin. The teammate can then sign in using that organization, email and password.
6. In **Inbox**, upload a supported PDF. Fictional [single-page](examples/northwind-invoice.pdf) and [two-page](examples/multipage-invoice.pdf) invoices are available for testing.
7. After extraction, select **Full document** to inspect every PDF page. Save the category, reviewer, verified amount and currency. Add a comment and approve or reject.
8. Open **Insights** for totals and questions such as “How many invoices need review?” or “What is the total amount pending review?”

Local web: `http://localhost:3300`. API/OpenAPI: `http://localhost:8000/docs`.

```sh
make logs   # follow service logs; Ctrl-C stops following
make down   # stop services; retain database and original PDFs
```

## Pages

There are **thirteen pages**: three public entry pages, seven workspace pages and three admin settings pages. They ship together in one web application.

| Route | Access | Purpose |
| --- | --- | --- |
| `/` | Public | Product overview, workflow, features, role choices and frequently asked questions |
| `/register` | Public | Create an organization or request to join one |
| `/login` | Public | Select organization and sign in; pending accounts get an explanation |
| `/dashboard` | Approved account | Counts across all accessible invoices and recent activity |
| `/inbox` | Approved account | Upload, search, filter categories/status, paginate, inspect PDF/evidence, review, comment and manage access |
| `/review` | Approved account | Filterable queue of invoices awaiting a decision with SLA and flagged-field counts; `/review/[id]` is the keyboard-first split view for corrections and decisions |
| `/insights` | Approved account | Verified currency totals, category distribution and bounded invoice questions |
| `/actions` | Approved account | Pending approvals with a preview of exactly what will be sent, execution history and the dead-letter queue |
| `/settings/policies` | Organization admin | Kill switch, shadow mode and per-action-type policy |
| `/settings/connectors` | Organization admin | Webhook, CSV export, Postgres table and Google Sheets connectors with connection tests and export downloads |
| `/settings/workflow` | Organization admin | YAML workflow configuration: document types, fields, thresholds, rules and destinations |
| `/admin` | Organization admin | Membership and category management |

The homepage links to `/register?mode=create`, `/register?mode=join&role=member` and `/register?mode=join&role=reviewer`. These preselect the form; they do not grant permissions. Joining users remain pending until an admin approves their membership and role. Everyone uses the same `/login` page with their organization, email and password; the API checks their current membership and permissions.

Admins can manage the organization. Reviewers can verify and decide eligible invoices. Members can upload and discuss accessible invoices. Viewers have read-only access. A restricted invoice remains visible to its uploader, assigned reviewer, admins and selected teammates. A shared link always requires an approved account with access.

## Extraction providers

`rules` is the default offline provider. It reads explicitly labeled lines for every field configured for the document type (for the default invoice: `Vendor:`, `Invoice Number:`, `Invoice Date:`, `Due Date:`, `Subtotal:`, `Tax:`, `Total:`, `Currency:`, `PO Number:`). It is a limited parser, not general AI or OCR.

For varied text invoices, configure OpenRouter in your ignored `.env` or Render secrets:

```dotenv
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=your_new_private_key
OPENROUTER_MODEL=your_chosen_model_id
```

Select a currently available model that supports strict structured output, then restart the worker:

```sh
docker compose up -d --force-recreate worker
```

Only the worker receives the model key. PDF text is sent to the configured provider. The application validates exact source evidence before accepting extracted fields. Live accuracy, cost and latency depend on the selected model and require testing. Rotate any key previously disclosed in chat; keep keys out of commits and screenshots.

Supported uploads: unencrypted text-layer PDF, up to 10 MB, 10 pages and 50,000 text characters. Scanned invoices require OCR, which is not implemented. Every extracted invoice requires human review. Verified totals use exact decimals and separate currencies; they do not represent payments or accounting balances.

## Verification

With Docker running and Node.js 22.13 or newer installed:

```sh
make seed                 # optional fictional accounts for the legacy smoke suites
make lint typecheck test
make smoke
make smoke-ui
make smoke-tenants
make smoke-workspace      # fresh organization -> membership -> category -> invoice decision
(cd apps/web && npm run test:e2e:errors)
(cd apps/web && npm run test:e2e:public) # homepage, role entry links, auth navigation and mobile layout
```

`make demo` explicitly starts the stack and creates optional Northwind/Contoso sample accounts. Normal `make up` does not seed them. Existing seed passwords are preserved. Tests and sample PDFs are synthetic; automated success is not a measurement of extraction accuracy on customer invoices.

```sh
LLM_PROVIDER=mock OPENROUTER_API_KEY= make eval
```

Evaluation reports are ignored by Git. Browser tests use installed Chrome; set `PLAYWRIGHT_CHROME_PATH` if needed. The workspace smoke reports small local sequential latency samples, not a load-test capacity claim.

## Architecture and deployment

```mermaid
flowchart LR
  B[Browser] --> W[Public Next.js and same-origin proxy]
  W --> A[Private FastAPI]
  A --> P[(Postgres with tenant RLS)]
  A --> S[(Private PDF storage)]
  P --> X[Leased outbox worker]
  X --> S
  X --> P
  X -. optional .-> O[OpenRouter]
```

- [System design](SYSTEM_DESIGN.md): implemented architecture, data model, permissions, concurrency, recovery, latency targets and capacity calculations.
- [Deployment](docs/deployment.md): Oracle VM with private API/worker/Postgres and OCI PDF storage; paid Render alternative.
- [Architecture decisions](docs/adr/): tenant isolation, local storage, outbox, shared throttling, free-VM deployment, confidence scoring and governed actions.
- [Product roadmap](SPEC.md): original broader vision; not a claim that all roadmap features exist.

All eight pages deploy as one Next.js service. On Oracle, `infra/oracle/compose.yaml` adds Caddy HTTPS, separate private API/worker containers and persistent PostgreSQL. The browser uses the web service's same-origin API proxy; the API has no public port. The [deployment guide](docs/deployment.md) covers signup, free resource limits, private storage, migrations, backups and hosted checks. Oracle availability and hosted behavior remain to be verified. The existing Render Blueprint uses paid plans.

Remaining work before an unrestricted public service includes account email verification/recovery, stronger public signup abuse controls, isolated hostile-PDF parsing, operational alerts, backup restore validation and a real deployed acceptance test. There is no SSO, payment execution, ERP connector or arbitrary conversational assistant in the current application.

# OpsPilot: Product & Technical Spec

## 1. What we're building

OpsPilot is a **governed AI back-office agent** for small and mid-size businesses.

It takes in messy business documents: invoices, purchase orders, delivery notes and forms, arriving as PDFs, phone photos, emails or API uploads. It then:

1. extracts structured data from them,
2. validates that data,
3. routes uncertain fields to a human reviewer, and
4. **acts** on the result. It pushes data into the customer's systems (including legacy web portals that have no API), reconciles records, and drafts follow-ups.

Every step runs under a permission and approval layer, with a full audit trail.

This is a portfolio project for **Forward Deployed Engineer** roles. It must demonstrate:

- working with messy real-world data
- integrating with systems we don't control
- human-in-the-loop trust design
- measurable business outcomes
- reusable, config-driven deployment across multiple customers
- production-grade engineering

### Non-goals

- Not a general chatbot.
- Not an ERP or accounting system.
- No payment processing.
- The agent never sends an email or submits to an external system unless the org's action policy allows it.

## 2. Users & roles

| Role | Can do |
|---|---|
| Org admin | Configure workflows, connectors, policies and the kill switch; invite users; manage API keys |
| Reviewer | Work the review queue; approve or reject documents and actions |
| Viewer | Read-only dashboards and documents |
| Platform admin | Cross-org access (for demo and ops only) |

## 3. Domain model

Every tenant-owned table carries `org_id`. Isolation is enforced in the repository layer and covered by tests.

- **Organization**, **User**, **Membership** (role)
- **WorkflowConfig**: versioned per org. Holds document types, field schemas, validation rules, thresholds, destinations, action policies, and baseline minutes per document (used for ROI).
- **Document**: the stored file plus its source (upload / email / api), content hash, status and trace id.
- **ExtractionRun**: provider, model, prompt version, raw output, tokens, cost, latency.
- **Field**: value, confidence score, confidence signals, page number and evidence text, status (`auto` / `needs_review` / `corrected` / `approved`).
- **ReviewTask**: assignee, SLA, outcome.
- **Correction**: before and after values, reviewer, timestamp. This is the training signal for the learning loop.
- **Action**: type, connector instance, payload, human-readable preview diff, status, idempotency key, attempts, and result or error.
- **ActionPolicy**: per org and action type. One of `auto` / `needs_approval` / `forbidden`.
- **ConnectorInstance**: connector type, config, and credentials encrypted at rest.
- **AuditEvent**: append-only log of who or what did what, when, and to which entity.
- **MemoryItem**: vendor/sender profiles and few-shot examples, with embeddings stored in pgvector.
- **LLMCall**: provider, model, tokens in and out, cost, latency, document id, trace id.

**Document status machine:**
`received → queued → extracting → validating → (needs_review | auto_approved) → approved → actions_pending → completed`

A document can also move to `failed` (retryable) or `dead_lettered`. Every transition writes an AuditEvent.

**Action status machine:**
`proposed → (approved | rejected) → executing → (succeeded | failed → retrying | dead_lettered)`

## 4. Tech stack

**Frontend**
- Next.js (App Router) with strict TypeScript
- Tailwind and shadcn/ui
- TanStack Query and Zod
- react-pdf for the document viewer, Recharts for charts
- Typed API client generated from the backend's OpenAPI schema

**Backend**
- Python 3.12, FastAPI, Pydantic v2
- SQLAlchemy 2 with Alembic migrations
- Postgres 16 with pgvector
- Celery with Redis for workers and scheduled jobs
- MinIO (S3-compatible) locally; S3 or Cloudflare R2 in production
- Playwright (Python) for the browser agent
- httpx for outbound HTTP

**LLM layer**
- A provider abstraction in `apps/api/app/llm/`, with three providers:
  - Anthropic (default)
  - OpenAI-compatible (also covers local open-weight models via Ollama)
  - Mock (deterministic, used in tests and load tests)
- Model names come from env vars, e.g. `LLM_TIER1_MODEL=claude-haiku-4-5` and `LLM_TIER2_MODEL=claude-sonnet-5`.

**Auth**
- Email and password with argon2 hashing
- JWT in an httpOnly cookie
- Role-based access control
- Per-org API keys for programmatic intake

**Infrastructure**
- Docker Compose running: postgres, redis, minio, mailpit, api, worker, beat, web, legacy-portal
- GitHub Actions CI
- Deployed to Railway as the primary target. Also document a second option: a single VM running Docker Compose behind Caddy for HTTPS. This mirrors deploying into a customer's own server, which is a common FDE situation.
- OpenTelemetry tracing, structured JSON logs, a Prometheus `/metrics` endpoint; Sentry optional

**Testing**
- pytest for the backend
- Vitest for frontend units
- Playwright for end-to-end tests

### Monorepo layout

```
opspilot/
  apps/
    web/             Next.js frontend
    api/             FastAPI app, Celery workers, agent, connectors, LLM layer, prompts
    legacy-portal/   Deliberately old-style demo web app with NO API (browser-agent target)
    mcp/             MCP server (Phase 9)
  evals/             datasets/, run.py, reports/, baseline.json
  scripts/           synthetic data generator, seeding, load test, test-email sender
  docs/              adr/, engagement/, runbook.md, deployment.md, postmortems/, benchmarks.md
  infra/             Dockerfiles, deploy config
  .github/workflows/
  docker-compose.yml
  Makefile
  .env.example
  CLAUDE.md
  SPEC.md
  SYSTEM_DESIGN.md
  CONTEXT.md
  PROGRESS.md
  README.md
```

## 5. Features

### 5.1 Intake

- **Upload:** drag-and-drop, multiple files at once. Accept PDF, PNG and JPG, and convert HEIC. Check file types by content, not extension, and enforce size limits.
- **Email:** poll a dedicated IMAP mailbox per org. In development, use Mailpit plus `scripts/send_test_email.py`. Each attachment becomes a Document; the email body is kept as context.
- **API:** `POST /v1/documents` authenticated with an org API key. Send an HMAC-signed outbound webhook when a document completes.
- **Deduplication:** exact duplicates are caught by content hash per org. Near-duplicates are caught by matching (vendor, document number, total).

### 5.2 Extraction

- Render PDF pages to images and extract any text layer (pypdfium2 or pdfplumber).
- Call a vision-capable model with a JSON schema generated from the org's WorkflowConfig. Use structured output or tool calling.
- For each field, the model returns the value, the page number, and the exact evidence text it read the value from.
- Prompt templates live in `apps/api/app/prompts/` with version ids. Every ExtractionRun records the prompt version it used.

### 5.3 Validation & confidence

Confidence is **not** just the model's opinion of itself. Each field's score (0 to 1) combines these signals:

- **Grounding:** does the evidence text actually appear in the document's text or OCR?
- **Format:** type and pattern checks, such as dates, currency and ID patterns defined in the config.
- **Cross-field rules:** line items sum to the subtotal; subtotal plus tax equals the total within a tolerance.
- **Model agreement:** when a field is escalated, do the cheap and strong models agree?
- **Memory prior:** is the value consistent with the known vendor profile?
- **Self-report:** the model's own confidence, used only as a weak signal.

Signal weights are documented in an ADR. Each field has a threshold set in the config, and any field below it goes to review. The UI shows which signals failed, so reviewers can see why a field was flagged.

### 5.4 Review queue (the most important screen)

- **Split view:** the document viewer on the left (zoom, page navigation, highlight of the focused field's evidence) and the field form on the right.
- **Keyboard-first:**

  | Key | Action |
  |---|---|
  | J / K | Next / previous field |
  | Enter | Accept field |
  | E | Edit field |
  | A | Approve document |
  | R | Reject, with a reason |
  | ? | Show shortcuts |

- Each flagged field shows why it was flagged.
- Filters for document type, vendor and age. An SLA timer shows how long each task has waited, and tasks can be assigned to reviewers.
- Every edit creates a Correction.

### 5.5 Actions & governance (agent control panel)

- After a document is approved, the agent proposes Actions, for example: append a row to a Sheet, create a record in the legacy portal, mark a PO as reconciled, or draft an email to a vendor.
- Each Action shows a **human-readable preview or diff** of exactly what will change.
- ActionPolicy is set per action type: `auto`, `needs_approval` or `forbidden`.
- An **org-wide kill switch** pauses all agent execution immediately. Workers must check it before every external call.
- An org-wide **shadow mode**. The agent proposes actions and records what it *would* have done, but executes nothing. This is used during the first days at a new customer, and a report compares the agent's proposals with what humans actually did.
- Actions execute through connectors with idempotency keys and retries with exponential backoff. Failures that keep failing land in a **dead-letter queue**, which has a retry button in the UI.
- **Audit replay:** a per-document timeline covering intake, extraction runs, confidence, review edits, action proposals, approvals and executions, including screenshots for browser actions.

### 5.6 Connectors

Every connector implements a common interface:

- `describe_capabilities()`
- `test_connection()`
- `preview(action) -> Diff`
- `execute(action, idempotency_key) -> Result`

Connectors to build:

1. Webhook: POST JSON, HMAC-signed
2. Postgres table: writes into a customer database
3. Google Sheets: via a service account
4. CSV / Excel export
5. Legacy portal browser connector (Phase 7)

Credentials are encrypted at rest with a Fernet key taken from an env var.

### 5.7 Config engine (multi-customer, zero-code onboarding)

The WorkflowConfig is a versioned JSON document validated by Pydantic. It contains:

- document types
- fields: name, type, required, regex, enum and threshold
- cross-field rules, written in a small **safe rule DSL** (never `eval`)
- destinations
- action policies
- baseline minutes per document

It can be edited in the UI with a form editor, or as raw YAML with inline validation errors, and it can be imported and exported as YAML.

**Two seeded demo orgs** prove that a new customer needs no code changes:

| Org | Documents | Destinations |
|---|---|---|
| Northwind Traders | Supplier invoices | Google Sheets and a Postgres table |
| Contoso Logistics | Purchase orders and delivery notes | Legacy portal |

### 5.8 Memory & learning loop

- **Vendor/sender profiles:** aliases, typical fields, formats and historical values.
- **Few-shot retrieval:** corrections become examples. At extraction time, retrieve the top-k most relevant examples for this org (vendor match first, then pgvector similarity) and inject them into the prompt.
- **Visible improvement:** track accuracy per org per week and show an "accuracy over time" chart on the dashboard, so the loop is visibly working.
- **Isolation:** memory is strictly per org. A test must prove it never leaks across tenants.

### 5.9 Model router & cost

- Run the tier-1 (cheap, fast) model first.
- Escalate to the tier-2 (strong) model when confidence is below threshold or validation fails, re-running only the failing fields where possible.
- Log every LLM call. Compute cost from a price table in config.
- Dashboard shows cost per document, escalation rate, and a cost-vs-accuracy view.

### 5.10 Exception agent

When validation fails or data is missing, an agent loop runs with these tools:

- `search_documents`
- `get_vendor_profile`
- `find_purchase_order`
- `compare_with_history`
- `propose_field_fix`
- `draft_email`

Guardrails:

- A maximum number of steps and a timeout.
- Every tool call is logged and shown in audit replay.
- The agent can only **propose** fixes and **draft** emails. Applying a fix or sending an email always goes through ActionPolicy.
- In development, emails go to Mailpit.

### 5.11 Browser agent for legacy systems

`apps/legacy-portal` is a small, deliberately dated, server-rendered web app with **no API** and its own SQLite database. It includes realistic obstacles:

- a login page
- pagination
- a quirky date format (DD-MMM-YY)
- a multi-step form
- occasional slow responses
- a session timeout

The connector works like this:

- It uses Playwright.
- An LLM proposes the mapping from our fields to the portal's form fields once. The mapping is cached and editable in the UI.
- Execution is **deterministic** Playwright steps, not free-form clicking. After each step, the connector reads the value back to verify it.
- A screenshot of every step is saved to storage and attached to audit replay.
- When the policy is `needs_approval`, it pauses before the final submit.

Failure handling:

| Failure | Response |
|---|---|
| Missing element | Retry, then dead-letter |
| Expired session | Log in again and resume |
| Timeout | Back off and retry |

### 5.12 Dashboard & ROI

KPIs:

- documents processed
- auto-approve rate
- field accuracy (1 − corrected fields / total fields)
- median time to complete
- review queue depth
- cost per document
- **hours saved** = documents × baseline minutes − actual review time

Charts show each metric over time and can be filtered by document type.

A **weekly ROI report** runs on Celery beat and sends an HTML email to org admins, with a downloadable PDF.

### 5.13 Private mode

A per-org setting chooses the provider: `anthropic` or `openai_compatible`. With a local open-weight model via Ollama, no document data leaves the deployment. The eval report compares accuracy and cost across providers.

### 5.14 MCP server (Phase 9)

Exposes these tools:

- `search_documents`
- `get_document`
- `list_review_queue`
- `get_metrics`
- `propose_action` (still subject to ActionPolicy)

Authenticated with an org API key.

### 5.15 Security & compliance

- Tests that actively try cross-org access and must fail.
- No raw document text in production logs, with an optional PII redaction filter.
- Rate limiting on auth and intake endpoints.
- A per-org data retention setting, enforced by a scheduled purge job.
- Secrets come only from env vars and are documented in `.env.example`.
- A per-org daily LLM spend cap. The public demo org gets strict upload and spend limits, so strangers can't run up the API bill.
- Upload validation: content-type sniffing and size limits.

### 5.16 Observability & reliability

- **Tracing:** OpenTelemetry traces span API → queue → worker → LLM → connector. The trace id is stored on each Document.
- **Endpoints and logs:** structured logs, `/healthz` and `/readyz` endpoints, and a `/metrics` endpoint.
- **Load test:** 10,000 documents with the Mock provider (Locust or k6). Record throughput and latency in `docs/benchmarks.md`.
- **Chaos drill:** an env flag makes the LLM provider fail or time out. The system must degrade gracefully:
  - the queue backs up without losing data
  - retries happen
  - the UI shows a "degraded" banner

  Write up the drill in `docs/postmortems/001-llm-outage.md`.

## 6. Evals

- **Synthetic data:** `scripts/generate_synthetic.py` generates about 150 realistic synthetic documents across both document types, each with ground-truth JSON. Include variation:
  - different layouts and fonts
  - skewed and low-quality scans
  - handwriting-style fonts
  - multiple currencies
  - missing fields
  - line-item tables
- **Datasets:** stored in `evals/datasets/`. Real customer documents are added later and are gitignored.
- **Runner:** `evals/run.py` measures:
  - per-field exact match and normalized match
  - precision and recall of review flagging (did we flag the fields that were actually wrong?)
  - cost and latency

  It writes `evals/reports/<timestamp>.json` and `.md`, and compares against `evals/baseline.json`.
- **CI:**
  - The full pipeline always runs with the Mock provider, so tests are deterministic.
  - On pull requests that touch prompts or extraction, if an `ANTHROPIC_API_KEY` secret exists, run a 20-document subset against the real model.
  - Fail the build if accuracy drops more than 2 points below the baseline.
- **UI:** `/evals` shows the latest report.

## 7. Frontend pages

- `/login` and invite acceptance
- `/dashboard`
- `/inbox`: all documents, with filters and status
- `/review` (the queue) and `/review/[id]` (split view)
- `/documents/[id]`: details and audit replay timeline
- `/actions`: pending approvals, history, dead-letter queue
- `/settings/workflows`, `/settings/connectors`, `/settings/policies` (including the kill switch), `/settings/members`, `/settings/api-keys`, `/settings/privacy`
- `/evals`

**Design:** a clean, dense, keyboard-friendly operations tool. Include light and dark mode, loading skeletons, useful empty states, toast notifications, and a layout that works on a tablet.

## 8. API

- REST, versioned under `/v1`, with OpenAPI docs at `/docs`.
- Cursor pagination.
- A consistent error envelope, e.g. `{error: {code, message, details}}`.
- A request id on every response.
- The frontend uses a typed client generated from the OpenAPI schema.

## 9. Build phases

Every phase ends with:

- all tests passing, with lint and typecheck clean
- `make up` working from a clean clone
- staging redeployed and smoke-tested (from Phase 0 onward)
- README and PROGRESS.md updated
- a git commit

**Deployment track.** Deployment is not a final step bolted on at the end. The Phase 0 skeleton is deployed to a Railway **staging** environment, and every later phase keeps staging working. Pushes to `main` auto-deploy to staging after CI passes. Phase 10 promotes the app to **production**.

**Phase 0: Foundation**
- Monorepo, Docker Compose, Makefile, CI (lint, typecheck, tests)
- FastAPI skeleton with health endpoints, Postgres and Alembic
- Auth, orgs and RBAC
- Next.js shell with login and app layout
- Seed script creating the two demo orgs and their users
- First deploy of the skeleton to Railway staging, with CI auto-deploy from `main`
- `scripts/smoke_test.py`, which takes a base URL and checks health and login; extended in later phases to cover each new flow

*Done when:* `make up` locally, then log in as the demo user and see an empty dashboard. The same works on the staging URL, and the smoke test passes against it.

**Phase 1: Intake & extraction**
- Upload, storage, queue and worker
- LLM provider abstraction (Anthropic and Mock)
- Invoice extraction with evidence
- Synthetic data generator
- Eval runner v1

*Done when:* uploading a synthetic invoice produces extracted fields in the database, and `make eval` writes a report.

**Phase 2: Validation, confidence & review**
- Confidence signals and scoring
- Review queue with split view and keyboard shortcuts
- Corrections recorded

*Done when:* low-confidence fields are flagged with reasons, and a reviewer can fix and approve them entirely by keyboard.

**Phase 3: Actions, governance & connectors**
- Action proposals with preview diffs
- ActionPolicy and the kill switch
- Webhook, CSV, Postgres and Google Sheets connectors
- Idempotency, retries and the dead-letter queue
- Audit log and replay timeline

*Done when:* an approved invoice lands in a Sheet only after approval, and the kill switch blocks execution.

**Phase 4: Config engine & multi-customer**
- WorkflowConfig editor with YAML import and export
- Second org and document type (Contoso)
- Email intake
- Dashboard KPIs

*Done when:* Contoso documents flow end to end with no code changes, only config.

**Phase 5: Learning loop, router & cost**
- Memory and few-shot retrieval
- Model router
- LLM cost tracking
- CI eval gate
- Accuracy-over-time chart

*Done when:* an eval shows accuracy improving after corrections are ingested, and cost per document is visible.

**Phase 6: Exception agent**
- Tool-using agent loop with guardrails
- Email drafts sent to Mailpit
- Agent steps shown in audit replay

**Phase 7: Legacy portal & browser agent**
- The legacy-portal app
- Playwright connector with field mapping, step verification, screenshots and an approval pause

*Done when:* an approved Contoso document is entered into the portal, with screenshots in the replay.

**Phase 8: Hardening**
- Private mode (Ollama)
- OpenTelemetry tracing and metrics
- Security items from 5.15
- Load test and benchmarks
- Chaos drill and postmortem

**Phase 9: Polish & launch**
- MCP server
- Weekly ROI report
- Optional voice-note intake (transcribe, then create a task)
- Demo seed data
- README with GIF placeholders and a Mermaid architecture diagram
- A demo org with a read-only login for recruiters

**Phase 10: Production go-live**

Promote to production and verify every item below on the **live URL**. Mark each item done in PROGRESS.md only after verifying it.

*Infrastructure*
- [ ] Production environment on Railway with all services running: web, api, worker, beat, legacy-portal
- [ ] Managed Postgres with pgvector, Redis, and an S3-compatible bucket (Cloudflare R2 or S3)
- [ ] Automatic daily database backups, with **one restore actually tested**
- [ ] Custom domain with HTTPS (optional; the Railway subdomain is fine)

*Configuration*
- [ ] All production secrets set in Railway, and `.env.example` matches what production uses
- [ ] Migrations run automatically on deploy, as a release step
- [ ] Production settings: debug off, CORS locked to the web origin, secure cookies, rate limits on
- [ ] Per-org daily LLM spend caps enforced; the public demo org has strict limits

*Release process*
- [ ] Pushes to `main` deploy to staging; a tagged release deploys to production, only after CI and the eval gate pass
- [ ] Rollback procedure documented in `docs/deployment.md` and **tested once**

*Demo*
- [ ] Demo org seeded, with a read-only recruiter login
- [ ] Demo data resets nightly

*Monitoring*
- [ ] Sentry capturing errors from web, api and worker
- [ ] An external uptime monitor on `/healthz`
- [ ] Logs searchable in Railway
- [ ] A cost dashboard showing LLM spend

*Verification and docs*
- [ ] `scripts/smoke_test.py` passes against production. It covers login, upload, extraction, review, action approval and the audit replay.
- [ ] Security check: no secrets in the repo or logs, dependencies scanned (`pip-audit`, `npm audit`), and cross-tenant access tests passing
- [ ] `docs/deployment.md` complete for both Railway and the single-VM Docker Compose option
- [ ] README updated with the live demo link, recruiter login, and real metrics (or honest `[TODO]` placeholders)

*Done when:* every box above is checked, and Claude has walked me through a complete live demo on the production URL: upload a document, review it, approve an action, and show the audit replay and the dashboard.

## 10. Engagement kit (`docs/engagement/`)

Create these **templates**, with headings and guidance prompts only and no invented content. The developer fills them in with a real customer.

- `discovery.md`: current workflow, stakeholders, pain points, volumes, systems involved, constraints
- `success-plan.md`: target metrics, baseline measurements, timeline, risks
- `weekly-update-template.md`
- `handoff-runbook.md`
- `field-feedback.md`: product gaps observed during deployment

## 11. README

The README should include:

- a one-line pitch and a demo GIF placeholder
- the problem
- a Mermaid architecture diagram
- features
- a metrics table, filled **only** from eval reports and real deployment measurements
- a quickstart
- tradeoffs and what was cut, with reasons
- a roadmap

## 12. Honesty rule

Never fabricate metrics, customer names, quotes or testimonials anywhere in the repo, UI or docs. Use `[TODO: real number]` placeholders until something is actually measured. The demo org names (Northwind Traders, Contoso Logistics) are clearly fictional sample names.

## 13. System design requirements by phase

`SYSTEM_DESIGN.md` is authoritative for architecture. Where it adds detail beyond this spec, implement it in these phases:

| Phase | Implement from SYSTEM_DESIGN.md |
|---|---|
| 0 | Postgres row-level security with a per-request `app.current_org` setting; append-only grants on `audit_events`; cross-tenant isolation test suite skeleton |
| 1 | Transactional outbox and dispatcher; separate queues (`extraction`, `actions`, `browser`, `maintenance`); stuck-job reaper; config version pinning on documents; file stored before the `202` is returned; conditional-update state transitions |
| 2 | Multi-signal confidence scoring with weights documented in an ADR; prompt-injection test documents in the eval set |
| 3 | Idempotency keys and connector-side existence checks; policy and kill-switch check immediately before each external call |
| 5 | Prompt caching for static prefixes; per-org spend cap enforced before each LLM call |
| 7 | Deterministic Playwright steps with read-back verification; dead-letter plus re-mapping when the UI changes |
| 8 | Circuit breaker and fallback provider; monthly partitions for `fields`, `audit_events` and `llm_calls`; hourly KPI rollups; all alerts from section 13 of the design doc |
| 9–10 | Replace every **[estimate]** in `SYSTEM_DESIGN.md` with measured numbers; write the ADRs listed in its section 14; document shadow mode as part of the deployment playbook |

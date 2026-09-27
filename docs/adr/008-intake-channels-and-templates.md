# ADR 008: Intake channels, workflow templates, near duplicates and KPIs

Status: accepted for Phase 4

## Context

Phase 3 left OpsPilot with one way in (a browser upload) and one customer shape (invoices).
A second customer with different documents, a mailbox or an integration script has to work
without code changes, only configuration. Phase 4 adds a second template, two more intake
channels, a check for documents that are the same business record in a different file, and
the KPIs the dashboard promises. The rules were: every tenant table stays behind row-level
security, every new credential is encrypted at rest, no channel bypasses the upload path
(hash de-duplication, quota, outbox, audit), and nothing here executes an external action.

## Decision

**Templates, not code, describe a customer.** `default_logistics_config()` adds purchase
orders and delivery notes next to the invoice configuration. Registration takes an optional
`template` (`invoice`, the default, or `logistics`); the seed gives Northwind the invoice
template plus a CSV export destination and Contoso the logistics template. Document types
are detected by counting occurrences of each type's `detect` keywords, with a bonus for a
keyword in the first 200 characters (the heading), so a delivery note that quotes a "PO
Number" is not read as a purchase order. The rules provider still extracts purely from the
configured labels; purchase orders and delivery notes needed no provider change.

**Near duplicates force a human.** An exact duplicate never gets past upload (unique content
hash per tenant). After extraction the worker compares the new document's counterparty
(`vendor` or `supplier`), primary identifier (the type's first required identifier field) and
`total` with other documents of the same tenant and type, using those documents' effective,
corrected values. A match is recorded in `document_links` in both directions, adds
"Possible duplicate of <filename>" to the identifier field, flags that field and forces
`needs_review` even under a threshold policy. Custom types without an identifier field skip
the check; types without a `total` compare the first two elements only.

**API keys act as their creator.** `POST /v1/settings/api-keys` returns `opk_<prefix>_<secret>`
once; the database keeps the eight-character prefix and the SHA-256 of the whole key. A key
authenticates only `POST /v1/documents` and `GET /v1/documents/{id}`; `app.auth` checks the
matched route before it looks at the key, so a Bearer header on any other route is a 401.
Lookup is by prefix and the hash comparison is constant time. Because the prefix has to be
looked up before the tenant is known, `api_keys` carries a second, SELECT-only RLS policy
keyed on `app.api_key_prefix`, which exposes exactly the row whose prefix the caller
presented and keeps the table under `FORCE ROW LEVEL SECURITY`. Documents uploaded with a
key belong to the key's creator, are audited with the creator as actor and `api_key_id` in
the detail, carry `source = api`, and count against a 60-uploads-per-15-minutes budget per
key kept in the existing `login_attempts` table. A key stops working the moment its creator's
membership is no longer active or the key is revoked.

**Email intake polls, it does not listen.** One inbox per organization (`email_inboxes`)
with an `imap` backend for customers (host, port, username, folder, optional since date;
password Fernet-encrypted like connector credentials) and a `mailpit` backend for
development (`<slug>@opspilot.local` through the Mailpit HTTP API at `MAILPIT_API_URL`,
refused outside development). The worker loop checks every 15 seconds for inboxes whose
`next_poll_at` has passed and leases them with `FOR UPDATE SKIP LOCKED`, so an inbox is
polled at most once per 60 seconds however many workers run. Each PDF attachment goes through
`document_service.upload` with `source = email`, `source_ref = "<from> <subject>"` and the
plain-text body (capped at 20,000 characters) in `context_text`; the system is the audit actor
and the message uid is in the detail. `email_messages` records each processed uid per tenant,
so a message seen twice (a crash after upload but before the record, or a mailbox that does
not honour the read flag) creates nothing new: the second pass finds the row or the content
hash. IMAP hosts must pass the same address guard as webhook destinations outside
development, and the socket connects to the checked address while TLS verifies the host name
(the webhook pinning approach). Mailpit specifics were verified against a live v1.31: search
is `GET /api/v1/search?query=to:"<address>" is:unread` (the list endpoint ignores `query`),
detail is `GET /api/v1/message/{ID}` (does not mark read), parts are
`GET /api/v1/message/{ID}/part/{PartID}`, and `PUT /api/v1/messages {"IDs": [...], "Read": true}`
marks messages read.

**KPIs are computed from what the caller may see.** `GET /v1/metrics/overview?days=&document_type=`
scopes every query by `accessible_document_clause`. Processed documents are those created
in the range that are not queued, extracting, validating or failed; auto-approved ones never
received a review task; field accuracy is one minus edited fields over assessed fields of
the latest run; time to complete is review task completion minus opening (zero for
auto-approved documents, open tasks excluded from the median); hours saved is processed
documents times the configuration's `baseline_minutes` minus actual review minutes, floored
at zero. `cost_per_document` is null until Phase 5 meters LLM calls. Three queries produce
the whole response (per-document rows, per-day field counts, queue depth); the daily series
is filled in Python so every day in the range has a point.

**Synthetic data is generated, not hand-written.** `scripts/generate_synthetic.py` renders
labeled text PDFs for all three types with a seeded generator (label casing and order, noise
lines, four currencies, five date formats, five perturbations) and a ground-truth manifest.
The 150-document set is gitignored and rebuilt on demand; a 12-document sample and two
Contoso examples are committed. `evals/run.py` reports per document type and adds type
detection to the baseline.

## Consequences

- A second template proves the configuration engine but the seed only upgrades an untouched
  default configuration; an edited organization keeps its edits, so existing local databases
  may still show Contoso on invoices until re-seeded.
- Email intake cannot see a mailbox until an administrator configures it; there is no
  catch-all. Polling every 15 seconds costs one small query per organization per tick.
- API keys have one scope (`documents:write`) and a fixed budget; per-key scopes and limits
  are stored but not yet configurable.
- Near-duplicate detection compares one identity triple. Documents that differ in the
  identifier (a re-issued invoice with a new number) are not linked; that is deliberate.
- Marking a message read is the only write email intake makes to a customer system; it is
  not an Action because it is part of reading the mailbox, not an effect on the outside world.

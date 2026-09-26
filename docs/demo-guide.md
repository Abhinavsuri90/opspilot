# OpsPilot demo and interview guide

OpsPilot is a **working invoice intake and extraction prototype**, not the completed agent platform in `SPEC.md`. Its strongest current story is an end-to-end, tenant-isolated document workflow with explicit evidence and a durable worker. A public Railway deployment is still pending; do not claim a live URL until the hosted smoke test passes.

## Local demo accounts and invoices

Start Docker Desktop, then run `LLM_PROVIDER=mock OPENROUTER_API_KEY= make up` from the repository root. Open `http://localhost:3300/login`. These seeded accounts use the password in your ignored `.env` under `DEMO_PASSWORD` when they are first created; later seed runs preserve existing passwords unless explicitly reset.

| Organization | Email | Seeded role | Current UI permissions |
| --- | --- | --- | --- |
| `northwind` (Northwind Traders) | `northwind@example.com` | Admin | View invoices; upload; retry failed extractions; view the read-only Admin member directory. |
| `contoso` (Contoso Logistics) | `contoso@example.com` | Reviewer | View invoices; upload; retry failed extractions. Review editing and approval are still planned. |

Upload these **fictional, text-layer PDFs** from `examples/demo/`. Each has a different invoice number, vendor, date, and total so its result is easy to recognize.

| Suggested organization | PDF | Vendor | Invoice number | Date | Total |
| --- | --- | --- | --- | --- | --- |
| Northwind | [northwind-harbor-supply.pdf](../examples/demo/northwind-harbor-supply.pdf) | Harbor Supply Co | `NW-DEMO-2026-101` | 2026-09-05 | $187.40 |
| Northwind | [northwind-maple-office.pdf](../examples/demo/northwind-maple-office.pdf) | Maple Office Goods | `NW-DEMO-2026-102` | 2026-09-11 | $942.15 |
| Contoso | [contoso-cedar-freight.pdf](../examples/demo/contoso-cedar-freight.pdf) | Cedar Freight LLC | `CT-DEMO-2026-201` | 2026-09-17 | $356.80 |
| Contoso | [contoso-blue-ridge-parts.pdf](../examples/demo/contoso-blue-ridge-parts.pdf) | Blue Ridge Parts | `CT-DEMO-2026-202` | 2026-09-23 | $1284.32 |

## Company-by-company walkthrough

1. Sign in with organization `northwind`, email `northwind@example.com`, and its seeded password. The **Dashboard** shows recent documents; **Admin** shows Northwind's read-only member directory. Open **Inbox** and upload `examples/demo/northwind-harbor-supply.pdf`. Watch it move from **Queued** through **Extracting** to **Needs review**; open the result and compare all four fields with the table above. Each field includes source text and a page number.
2. Upload `examples/demo/northwind-maple-office.pdf` while still in Northwind. Confirm both Northwind invoices appear. The worker validates that extracted evidence exists on the cited PDF page.
3. Sign out, then sign in with organization `contoso`, email `contoso@example.com`, and its seeded password. Contoso has a reviewer role, so the **Admin** link is absent and direct `/admin` visits show an access message. Open **Inbox**. The two `northwind-*.pdf` filenames should **not** appear. Previously uploaded Contoso documents may already be present if you have run the demo before.
4. Upload `examples/demo/contoso-cedar-freight.pdf` and `examples/demo/contoso-blue-ridge-parts.pdf`. Check that their results show the expected `CT-DEMO` invoice numbers and reach **Needs review**. Sign out and return to Northwind: the two `contoso-*.pdf` filenames should **not** appear there.
5. Open the [latest CI runs](https://github.com/Abhinavsuri90/opspilot/actions/workflows/ci.yml) and the [deployment readiness review](deployment-readiness-review.md). State which tests ran and which production checks remain.

The signed-in organization controls where an upload is stored; the filenames are suggested demo groupings, not a restriction on which file an organization can upload. Uploading the exact same PDF again intentionally opens its existing result. To make a fresh fictional invoice, change at least the invoice number:

```sh
python3 scripts/generate_demo_invoice.py /tmp/opspilot-new-invoice.pdf \
  --invoice-number NW-DEMO-NEW-001 --vendor 'Harbor Supply Co' \
  --invoice-date 2026-09-26 --total '$219.75'
```

The local worker uses a deterministic mock provider by default; this walkthrough does not need an OpenRouter key or measure live model accuracy.

For an automated browser check of all four PDFs, both organizations, and the admin role, keep the mock stack running and run `LLM_PROVIDER=mock OPENROUTER_API_KEY= make smoke-tenants`. The test reuses identical uploads rather than creating duplicate documents.

## Architecture to explain

| Decision | Why it is there | Tradeoff |
| --- | --- | --- |
| Postgres row-level security plus a restricted application role | Tenant isolation is enforced below API filters as well as in repository queries. | Migration and bootstrap need a separate owner role. |
| Transactional outbox and a polling worker | The document row and extraction request commit together; worker claims survive API restarts. | Polling adds latency and requires lease/retry handling. |
| S3-compatible object storage | PDF bytes stay out of Postgres while metadata and audit records remain queryable. | Bucket availability and retention need separate operations checks. |
| Same-origin `/api` proxy in Next.js | Browser cookies work with a private API service on a separate internal address. | The web server must bound and forward request bodies carefully. |
| Evidence checks after extraction | Returned values must be backed by exact PDF text on a valid page. | Scanned PDFs and semantic normalization need a later OCR/review design. |

## Honest resume wording

> Built an invoice extraction prototype with Next.js, FastAPI, Postgres row-level security, S3-compatible storage, and a durable outbox worker. Added evidence validation, tenant isolation tests, browser smoke coverage, and Docker-based CI.

After a public deployment is verified, add the host and live demo URL. Add accuracy or latency numbers only when measured on a named dataset and model; the current synthetic mock evaluation is a parser/workflow check, not an AI accuracy benchmark.

## Questions to practice

1. **How does OpsPilot prevent one organization from reading another's invoice?** Explain authenticated membership, transaction-scoped tenant context, RLS, and cross-tenant tests.
2. **What happens if the API commits an upload and the worker stops?** Explain the outbox event, lease claim, retry, and idempotent document identity.
3. **Why is a model response not accepted directly?** Explain schema-constrained output, exact evidence checks, page checks, and the remaining need for human review.

## Current limits

The inbox can display extraction results and retry failed jobs, but reviewers cannot edit/approve fields yet. Scanned PDFs need OCR. No external action connector runs. The OpenRouter adapter has contract tests with fake responses; live model accuracy and cost have not been measured. The [deployment guide](deployment.md) lists the hosted verification steps still required.

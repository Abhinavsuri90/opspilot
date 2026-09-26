# OpsPilot demo and interview guide

OpsPilot is a **working invoice intake and extraction prototype**, not the completed agent platform in `SPEC.md`. Its strongest current story is an end-to-end, tenant-isolated document workflow with explicit evidence and a durable worker. A public Railway deployment is still pending; do not claim a live URL until the hosted smoke test passes.

## Five-minute demo

1. Run `LLM_PROVIDER=mock OPENROUTER_API_KEY= make up` and open `http://localhost:3300`. Sign in to `northwind` with the local demo credentials in your ignored `.env`.
2. Open **Inbox**, download the fictional sample invoice, and upload it. The page shows the document moving through queued/extracting to `needs_review`.
3. Open the result and point to each extracted value, its source text, and page number. Explain that the worker checks model output against text actually present in the PDF.
4. Sign out. If showing tenant isolation, sign in to the second seeded organization and show that its inbox does not reveal Northwind's document.
5. Open the [latest CI run](https://github.com/Abhinavsuri90/opspilot/actions/workflows/ci.yml) and the [deployment readiness review](deployment-readiness-review.md). State which tests ran and which production checks remain.

The local worker uses a deterministic mock by default. Generate a fresh fictional invoice number for a second extraction: repeated identical uploads intentionally return the existing document.

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

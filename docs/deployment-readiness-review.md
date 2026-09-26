# Deployment readiness review

Reviewed 2026-09-26 for the first public demo. This is a code and local integration review, not a completed Railway deployment or an external security assessment.

Local verification: backend Ruff, strict mypy, and 24 Postgres tests; frontend lint, typecheck, and 10 tests; production web build; nonroot API release-image import; live API smoke; browser login, fresh upload/extraction, retry UI, and logout; synthetic mock eval. The production npm dependency audit reported zero advisories at the time of review.

## Problems addressed in this iteration

| Finding | Change |
| --- | --- |
| Separate web/API domains could block `SameSite=Lax` login cookies | Browser calls same-origin `/api`; the web server proxies to a private API and forwards cookies, Origin, status, and request IDs. |
| API URL was fixed into the web bundle at build time | `API_INTERNAL_URL` is a server-only runtime setting. The same image can be promoted between environments. |
| Railway Bucket URLs differ from local S3Mock | S3 addressing style is configurable: `path` locally, `virtual` for new Railway Buckets. |
| Railway Postgres URLs select an uninstalled driver | Hosted `postgres://` and `postgresql://` URLs are normalized to the installed psycopg 3 driver. |
| API process ignored Railway's assigned port | The release image binds `${PORT:-8000}` and runs as a nonroot user without test dependencies. |
| Health checks could pass before migrations | `/readyz` checks required database tables; local startup now migrates before waiting for API/web health. |
| Local support services were exposed on all interfaces | Compose publishes development ports on `127.0.0.1` only. |
| Worker could claim a document twice after a lease expired | Completion and failure lock the outbox claim and document before committing; stale claims have a retry ceiling. |
| Invalid or scanned PDFs failed only after being queued | Intake parses the PDF before storing it, with page, text, and size limits and clearer upload errors. |
| Repeated uploads could grow storage without a demo limit | A per-organization cap is checked under a transaction advisory lock. |
| Failed documents could not be retried because uploads deduplicate | Authenticated retry endpoint, audit entry, Inbox action, and two-manual-retry limit. |
| Inbox stopped refreshing while worker status was `extracting` | Polling now tracks the actual queued/extracting states and stops after a final state. |
| Browser smoke could pass by reading an old deduplicated result | It downloads the hosted fictional PDF, changes the invoice number without changing PDF offsets, uploads a fresh file, and waits for its own result. |
| Demo PDF was unavailable from a hosted web service | The sample is copied into the release web image and linked from the Inbox. |
| A missing OpenRouter key left the worker looping as if healthy | The worker validates the configured provider at startup and exits on invalid configuration. |
| Reseeding silently changed existing demo passwords and roles | Seed preserves existing users unless credential reset is explicitly requested. |
| Cross-site state-changing requests lacked an explicit origin check | The API checks the configured web origin, and the web proxy forwards the browser Origin header. |

## Still required before wider use

- **Public deployment:** create or share a Railway project, configure private API/worker/Postgres/Bucket, run the migration job, and pass the browser smoke on the public web URL. The [deployment runbook](deployment.md) has the exact setup. No public URL has been verified yet.
- **Live model:** rotate the key previously shared in chat, store the replacement only in the worker's secret environment, run the live synthetic eval, and compare cost and field accuracy. Current evaluation results are from generated documents and the deterministic mock.
- **Operations:** enable backups and test a restore, configure worker/pending-job and usage alerts, and verify the actual Railway Bucket with upload/download. A deployment health check does not monitor the bucket or worker continuously.
- **Security and scale:** add a distributed login rate limit or an edge WAF before sharing a public demo account widely. The web proxy bounds upload bodies; the private API still relies on FastAPI multipart parsing before its own file-size check. Set retention/deletion policy and privacy controls before accepting real customer documents.
- **Product scope:** scanned PDFs/OCR, human review edits and approval, action connectors, confidence calibration, and production deployment remain future phases. The Inbox's `needs_review` state is a holding state, not a completed review workflow.

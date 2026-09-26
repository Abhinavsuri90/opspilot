# Current handoff

## Last updated

2026-09-26. Check `git log -1 --oneline` for the latest commit.

## Current status

The local app supports authenticated, tenant-isolated PDF invoice intake, S3-compatible storage, a Postgres outbox worker, evidence-bearing extraction, and an inbox with failed-job retry. Browser requests use a same-origin web proxy to the private API. The worker defaults to a deterministic mock. OpenRouter is optional and has fake-HTTP contract coverage; no live model call has been made. The sample and 20-invoice eval set are fictional text-layer PDFs. Public staging, OCR, human review/approval, and actions are pending.

## Next step

Obtain a Railway project link/access from the owner, then follow `docs/deployment.md`: provision Postgres and Bucket, run the migration/bootstrap job, deploy private API and worker plus public web, and run the browser smoke against its public URL. Keep the worker on mock until that path is verified. Rotate the OpenRouter key previously shared in chat; place a new key only in a secret environment, then run the live synthetic eval. Do not claim live model accuracy or production readiness until those checks pass.

## Verification

`make up`, backend Ruff/mypy/24 tests, frontend lint/typecheck/10 tests and production build, `make smoke`, `make smoke-ui` with a fresh invoice, and `make eval` passed locally on 2026-09-26. The nonroot release API image built and imported successfully. The mock eval reported 100% exact field match and 100% grounding on generated documents only. Production npm audit showed zero advisories at the time of review. Check GitHub CI after pushing the new commits.

## Environment and decisions

- Local web: `http://localhost:3300`; API: `http://localhost:8000`; repository: https://github.com/Abhinavsuri90/opspilot.
- `.env.example` lists variable names. `.env` is ignored. API and worker use the restricted `opspilot_app` database role; migrations use the owner role. The OpenRouter key is passed only to the worker.
- Local storage uses Adobe S3Mock (ADR 002); the worker polls the Postgres outbox directly (ADR 003). Redis dispatch remains a target design. See `README.md`, `SYSTEM_DESIGN.md`, `SPEC.md`, `docs/deployment.md`, and `docs/deployment-readiness-review.md`.
- On this Mac, if Docker Desktop's credential helper hangs during image pulls, set `DOCKER_CONFIG=/private/tmp/opspilot-docker-config` for Compose. This is a local workaround, not a repository requirement.

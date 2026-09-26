# Current handoff

## Last updated

2026-09-26. Check `git log -1 --oneline` for the latest commit.

## Current status

The local app supports authenticated, tenant-isolated PDF invoice intake, S3-compatible storage, a Postgres outbox worker, evidence-bearing extraction, and an inbox. The worker defaults to a deterministic mock. OpenRouter is optional and has fake-HTTP contract coverage; no live model call has been made. The sample and 20-invoice eval set are fictional text-layer PDFs. Public staging, OCR, human review/approval, and actions are pending.

## Next step

Rotate the OpenRouter key previously shared in chat. Put a new key only in ignored `.env` with `LLM_PROVIDER=openrouter`, restart the worker, upload a newly generated fictional invoice, and run the live synthetic eval. Compare results and cost with the mock baseline, then provision staging storage/Postgres/web/API/worker and verify the workflow on a public URL. Do not claim live model accuracy or production readiness until those checks pass.

## Verification

`make up`, backend Ruff/mypy/seven tests, frontend lint/typecheck/two tests/build, `make smoke`, `make smoke-ui`, and `make eval` passed locally on 2026-09-26. The mock eval reported 100% exact field match and 100% grounding on generated documents only. CI status for the latest commit should be checked on GitHub after pushing.

## Environment and decisions

- Local web: `http://localhost:3300`; API: `http://localhost:8000`; repository: https://github.com/Abhinavsuri90/opspilot.
- `.env.example` lists variable names. `.env` is ignored. API and worker use the restricted `opspilot_app` database role; migrations use the owner role. The OpenRouter key is passed only to the worker.
- Local storage uses Adobe S3Mock (ADR 002); the worker polls the Postgres outbox directly (ADR 003). Redis dispatch remains a target design. See `README.md`, `SYSTEM_DESIGN.md`, `SPEC.md`, and `docs/deployment.md`.
- On this Mac, if Docker Desktop's credential helper hangs during image pulls, set `DOCKER_CONFIG=/private/tmp/opspilot-docker-config` for Compose. This is a local workaround, not a repository requirement.

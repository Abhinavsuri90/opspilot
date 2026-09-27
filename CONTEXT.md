# Handoff

## 1. Last updated

2026-09-27, mid-session. Latest commit `7ffb822` (spec wording; no code change). Uncommitted work in progress: see section 4.

## 2. Current status

Full project evaluation completed on 2026-09-27 (score 5.5/10: engineering about 7, spec completeness about 3). All ten local check suites were green at commit `7ffb822`: Ruff, mypy, 80 API tests, ESLint, TypeScript, 16 web tests, API smoke, public browser suite, fresh-company browser workflow, extraction eval. GitHub CI green on the last three commits.

The owner then chose to implement the rest of SPEC.md before deploying. Build order: fixes + Phase 2 → 3 → 4 → 5 → 6 to 9 → Phase 10 Oracle go-live. One commit per phase, every check suite green before each commit.

**In progress right now:** Phase 2 backend (confidence engine, workflow config schema, safe rule DSL, corrections, review tasks, review queue and timeline endpoints, migration 0006) plus the twelve review bugs; and the frontend review fixes (inbox polling bug, filter-aware empty state, cross-tab session handling, shared session hook, middleware cookie gate, proxy header passthrough, Zod register schema, component split, jsdom unit tests).

## 3. Exact next step

1. When the backend stream finishes: rebuild, run `make lint typecheck test`, then `make gen-client` to refresh `apps/web/lib/schema.d.ts`.
2. When the frontend fixes finish: run the web checks and the browser suites (`cd apps/web && npm run test:e2e:public && node scripts/e2e-workspace.mjs`).
3. Build the Phase 2 review split view (`/review`, `/review/[id]`) against the new endpoints; brief is drafted in the session scratchpad and mirrored in section 5.
4. Update SYSTEM_DESIGN.md, README.md, PROGRESS.md; commit `feat: ...` without any AI attribution; push.
5. Start Phase 3 (actions, policies, kill switch, connectors). Design notes are in section 5.

## 4. Files in play

- `apps/api/app/workflow_config.py`, `rules.py`, `confidence.py`, `review_service.py`, `prompts/`: new Phase 2 modules.
- `apps/api/alembic/versions/0006_*.py`: field confidence columns, `field_corrections`, `review_tasks`, `audit_events.document_id`, `documents.document_type`, missing indexes, workflow_configs INSERT grant.
- `apps/api/app/worker.py`, `llm/provider.py`, `document_service.py`, `invoice_workflows.py`, `main.py`, `config.py`, `login_throttle.py`, `onboarding.py`: pipeline, new endpoints and review fixes.
- `apps/web/app/**`, `components/workspace/*`, `lib/*`, `middleware.ts`, `vitest.config.ts`: frontend fixes.
- `docs/adr/006-confidence-scoring.md`: signal weights.

## 5. Decisions and deviations

- New organizations default to `review_policy: always`; threshold-based auto-approval is opt-in per org. Reason: safe first-day behavior at a customer; keeps existing flows and tests valid.
- `extracted_fields` stays immutable (INSERT-only); reviewer actions are append-only `field_corrections`; the effective value is the latest correction. Reason: evidence must never be rewritten.
- `Settings.environment` default flips to `production`; local, CI and tests set `development` explicitly. Reason: fail closed.
- Postgres outbox instead of Celery/Redis (ADR 003). Redis in the dev Compose file is unused and will be removed; Mailpit stays for Phase 4 email intake and Phase 6 drafts.
- Oracle Always Free VM instead of Railway (ADR 005). SPEC.md still says Railway in places; treat the spec as the roadmap, `docs/deployment.md` as the runbook.
- Phase 3 design notes: `org_settings` (kill switch, shadow mode), `action_policies`, `connector_instances` (Fernet-encrypted credentials), `actions` with idempotency key, outbox topics `propose_actions` and `execute_action`, policy and kill-switch check immediately before execution in the worker, dead-letter after 5 attempts with a retry endpoint.

## 6. Environment

- Local web http://localhost:3300, API http://localhost:8000/docs. No staging or production URL exists yet.
- External accounts: GitHub repo `Abhinavsuri90/opspilot` with Actions CI. Oracle Cloud account not yet created (guide in `docs/deployment.md`, Part 1 steps given to the owner). Render account exists but is not to be used (paid plans).
- Env var names: see `.env.example` (DATABASE_URL, DATABASE_OWNER_URL, APP_DB_PASSWORD, JWT_SECRET, COOKIE_SECURE, WEB_ORIGIN, ENVIRONMENT, S3_*, LLM_PROVIDER, OPENROUTER_API_KEY, OPENROUTER_MODEL, MAX_DOCUMENTS_PER_ORG, plus the new EXTRACTION_TIMEOUT_SECONDS and UPLOAD_PARSE_TIMEOUT_SECONDS). Never store values here.
- Demo logins exist only after `make demo` locally (Northwind and Contoso admins; password from DEMO_PASSWORD in the ignored `.env`).

## 7. How to run and test

```sh
LLM_PROVIDER=rules OPENROUTER_API_KEY= make up      # start local stack
make lint typecheck test                            # backend + web gates
cd apps/web && npm run test:e2e:public && node scripts/e2e-workspace.mjs
make eval                                           # extraction eval report
make gen-client                                     # after any API change
```

## 8. Known issues and gotchas

- The local Northwind org reached 99 of 100 documents because Postgres tests never cleaned up; the fix (teardown cleanup) is part of the current backend stream. If `make test` returns 409 quota errors, that is why.
- Running the API test suite and the browser suites at the same time can trip the shared login throttle; run them sequentially.
- The `gh` CLI is not installed; use the GitHub REST API or the web UI to check CI.
- The local assistant-instructions file is intentionally untracked through a local git exclude and must never be committed.
- Git history before `7ffb822` still contains the old tooling file; rewriting history is the owner's call.

## 9. Open questions for the owner

- Confirm the Oracle home region choice before creating the account (cannot be changed later).
- Decide whether to rewrite git history to remove the old tooling file (force push; CI run links in PROGRESS.md would point at rewritten commits).
- OpenRouter: a fresh key is needed before any live-model evaluation; the key shared in an earlier chat must be revoked.

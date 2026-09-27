# Current handoff

Updated 2026-09-27. Branch `main`; the previous committed/pushed head was `7343bf6`. The working tree contains Phase 5 backend, frontend, local demo and documentation changes that must be committed and checked in CI. See `git status` for the exact list. Never commit `.env` or any real model key.

## What the app is

OpsPilot is an organization-scoped invoice operations workspace. A person creates an organization and becomes its admin; members and reviewers request to join, and the admin approves them. Approved teammates upload text-based PDFs, inspect source evidence, correct fields, set categories and verified amounts, discuss, decide and optionally approve connector actions. Dashboard and Insights show authorized counts and currency-separated totals. The default `rules` provider works without an API key; OpenRouter is optional.

## Implemented scope

- Phases 0–4: committed foundation, tenant isolation, intake, confidence and human review, governed actions/connectors, multiple intake channels, templates, KPIs and browser workflows.
- Phase 5 in the current uncommitted tree: migration 0012; model-call ledger and local price table; prompt v3; optional tier-1/tier-2 router; tenant-scoped vendor profiles and correction examples with local hash embeddings/pgvector; daily estimated-spend cap; cost/escalation/weekly-accuracy APIs; synthetic eval and learning comparison. Frontend has corresponding dashboard tiles, accuracy chart, model-call timeline, cap setting and admin `/evals` report. ADR 009 explains design limits.
- Product clarity: public homepage explains the six core spaces; `/guide` gives each role a route through the invoice lifecycle and a page map.
- Local demo: `make demo` starts with `rules`, seeds fictional Northwind and Contoso admin/reviewer/member accounts, then uploads four example PDFs through the real API. Each org should have an approved document, one awaiting review, two categories, verified money and comments. This actual end-to-end seed has **not** run in this session because Docker Desktop did not start.

## Verification in this session

- Local Python environment: Ruff clean; mypy clean; 314 API tests pass, **59 Postgres tests skip** because no `DATABASE_OWNER_URL`/running DB.
- Web: ESLint, TypeScript, 150 unit tests, Next production build and Playwright public browser smoke pass. The public smoke covers owner/member/reviewer entry links, sign-in, protected redirect and 390/320px overflow.
- Synthetic mock eval (150 documents): exact match 95.5%, grounded 100%, flag precision 75%, flag recall 100%, type detection 100%. Held-out learning delta is 0.0 percentage points; do not claim improved accuracy from this.
- Docker commands failed because the Docker daemon is unavailable. Starting Docker Desktop through `open` and the nested executable also failed on this machine. Therefore full Postgres integration, API/browser workflow suites and demo activity remain unverified locally. CI after push is the next available full integration gate.

## Immediate next steps

1. Review this diff and `git diff --check`; run local static/test gates once more after any edits.
2. Commit in coherent backend and web/demo/docs commits. The user previously authorized GitHub push; push to `origin/main` and inspect the GitHub CI run. Fix failures and repeat. The browser-smoke job starts with `make demo`, then runs `make eval` and the new learning UI smoke, so it verifies the seed and report on its Docker stack.
3. When Docker Desktop is working, run `make demo` and smoke the seeded accounts, categories, PDFs, approvals, actions and Insights. If the demo seed fails, fix it before telling the owner the project is ready for their local test.
4. The owner explicitly paused deployment. Do not provision Oracle/Render or present a live URL as verified.

## Known product limits and roadmap

- Text-layer PDFs only, maximum 10 MB/10 pages/50,000 characters. No OCR or image formats. The default organization policy requires review; threshold auto-approval is opt-in.
- The daily spend cap is a soft estimate from recorded calls and local model prices, not an atomic financial limit. Provider prices and real model accuracy have not been independently verified. Any model key previously put in chat should be rotated before use.
- Phase 6 exception-agent tool loop, Phase 7 legacy portal/browser connector, Phase 8 private Ollama/observability/retention/load/chaos hardening, Phase 9 MCP/ROI/voice and Phase 10 public go-live are not complete. Do not describe the original `SPEC.md` roadmap as implemented. The broader public-service gaps in README remain.

## Useful commands

```sh
LLM_PROVIDER=rules OPENROUTER_API_KEY= make up
make demo
make lint typecheck test
make eval
make smoke-workspace
(cd apps/web && npm run test:e2e:public)
make down
```

`make up` does not create demo accounts. `make demo` does. The ignored `.env` supplies local secrets and `DEMO_PASSWORD`; never print or commit its contents. After backend edits, `docker compose build api` is required because source is copied into the image. Docker browser suites and API DB tests should run sequentially because their logins share a throttle. User-facing guide: README and `/guide`. Architecture: `SYSTEM_DESIGN.md`. Historical work: `PROGRESS.md`.

.PHONY: setup web-deps up demo down logs migrate seed test lint typecheck eval gen-dataset send-test-email gen-client smoke smoke-ui smoke-tenants smoke-workspace smoke-review lock-api

setup:
	@test -f .env || cp .env.example .env

web-deps:
	cd apps/web && npm ci --no-audit --no-fund

lock-api:
	sh infra/refresh-api-lock.sh

up: setup
	docker compose build
	docker compose up -d postgres s3mock mailpit
	$(MAKE) migrate
	docker compose up -d --wait --wait-timeout 90 api worker web

demo: up
	$(MAKE) seed

down:
	docker compose down

logs:
	docker compose logs -f

migrate: setup
	docker compose run --rm admin alembic upgrade head

seed: setup
	docker compose run --rm admin python /workspace/scripts/seed.py

test: setup web-deps
	# The background worker shares the database and would claim documents the
	# tests queue; pause it so the test process owns the outbox, then restore it.
	docker compose stop worker
	docker compose run --rm admin pytest -q -p no:cacheprovider || (docker compose up -d worker; exit 1)
	docker compose up -d worker
	cd apps/web && npm test

lint: setup web-deps
	docker compose run --rm api ruff check app tests alembic /workspace/scripts /workspace/evals
	cd apps/web && npm run lint

typecheck: setup web-deps
	docker compose run --rm api mypy app tests /workspace/scripts /workspace/evals
	cd apps/web && npm run typecheck

eval:
	@mkdir -p evals/reports
	docker compose run --rm -v "$(CURDIR)/evals/reports:/workspace/evals/reports" worker python -m evals.run

gen-dataset: setup
	docker compose run --rm -v "$(CURDIR)/evals/datasets:/workspace/evals/datasets" -v "$(CURDIR)/examples:/workspace/examples" worker python /workspace/scripts/generate_synthetic.py --output /workspace/evals/datasets/generated --sample /workspace/evals/datasets/sample --examples /workspace/examples

send-test-email: setup
	docker compose run --rm admin python /workspace/scripts/send_test_email.py --host mailpit --org $(or $(ORG),northwind)

gen-client: setup web-deps
	docker compose run --rm api python /workspace/scripts/export_openapi.py > apps/web/lib/openapi.json
	cd apps/web && npm run gen-client

smoke: setup
	docker compose run --rm admin python /workspace/scripts/smoke_test.py http://api:8000

smoke-ui: setup web-deps
	cd apps/web && node --env-file=../../.env scripts/e2e-smoke.mjs

smoke-tenants: setup web-deps
	cd apps/web && node --env-file=../../.env scripts/e2e-tenants.mjs

smoke-workspace: setup web-deps
	cd apps/web && node scripts/e2e-workspace.mjs

smoke-review: setup web-deps
	cd apps/web && node scripts/e2e-review.mjs

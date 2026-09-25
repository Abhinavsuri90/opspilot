.PHONY: setup web-deps up down logs migrate seed test lint typecheck eval gen-client smoke smoke-ui

setup:
	@test -f .env || cp .env.example .env

web-deps:
	cd apps/web && npm ci --no-audit --no-fund

up: setup
	docker compose up --build -d
	$(MAKE) migrate
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
	docker compose run --rm admin pytest -q
	cd apps/web && npm test

lint: setup web-deps
	docker compose run --rm api ruff check app tests alembic /workspace/scripts
	cd apps/web && npm run lint

typecheck: setup web-deps
	docker compose run --rm api mypy app tests /workspace/scripts
	cd apps/web && npm run typecheck

eval:
	@echo 'Extraction eval starts in Phase 1.'

gen-client: setup web-deps
	docker compose run --rm api python /workspace/scripts/export_openapi.py > apps/web/lib/openapi.json
	cd apps/web && npx openapi-typescript lib/openapi.json -o lib/schema.d.ts

smoke: setup
	docker compose run --rm admin python /workspace/scripts/smoke_test.py http://api:8000

smoke-ui: setup web-deps
	@set -a; . ./.env; set +a; cd apps/web && npm run test:e2e

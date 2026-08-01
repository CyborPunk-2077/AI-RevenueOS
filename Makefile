.DEFAULT_GOAL := help
SHELL := /bin/bash
COMPOSE := docker compose
BACKEND := cd backend &&

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-24s\033[0m %s\n", $$1, $$2}'

.PHONY: bootstrap
bootstrap: ## Install every toolchain from a clean clone
	pnpm install
	$(BACKEND) pip install -e ".[dev]"
	pre-commit install

.PHONY: up
up: ## Start the local stack
	$(COMPOSE) up -d --build
	@echo "API  http://localhost:8000/v1/docs"
	@echo "Web  http://localhost:3000"

.PHONY: down
down: ## Stop the local stack
	$(COMPOSE) down

.PHONY: reset
reset: ## Destroy and recreate local state
	$(COMPOSE) down -v && $(MAKE) up && sleep 8 && $(MAKE) migrate seed

.PHONY: worker
worker: ## Run a worker pool locally: make worker pool=comms
	$(BACKEND) python src/scripts/run_worker.py --pool $(or $(pool),general)

.PHONY: beat
beat: ## Run Celery Beat locally
	$(BACKEND) celery -A infrastructure.celery.app beat -l info

.PHONY: worker-health
worker-health: ## Probe a worker pool: make worker-health pool=ai
	$(BACKEND) python src/scripts/worker_health.py --pool $(or $(pool),general)

.PHONY: queues
queues: ## Show queue depths and registered workers
	$(BACKEND) python src/scripts/queue_status.py

.PHONY: dlq
dlq: ## List recent dead letters
	$(BACKEND) python src/scripts/queue_status.py --dead-letters

.PHONY: logs
logs: ## Tail service logs
	$(COMPOSE) logs -f --tail=100

.PHONY: migrate
migrate: ## Apply migrations to head
	$(BACKEND) alembic upgrade head

.PHONY: migrate-down
migrate-down: ## Roll back one migration
	$(BACKEND) alembic downgrade -1

.PHONY: migration
migration: ## Create a migration: make migration m="add table"
	$(BACKEND) alembic revision --autogenerate -m "$(m)"

.PHONY: seed
seed: ## Seed plans, permissions and industry templates
	$(BACKEND) python src/scripts/seed.py

.PHONY: lint
lint: ## Lint backend and frontend
	$(BACKEND) ruff check src tests
	$(BACKEND) ruff format --check src tests
	pnpm lint

.PHONY: format
format: ## Auto-format
	$(BACKEND) ruff format src tests && $(BACKEND) ruff check --fix src tests
	pnpm prettier --write .

.PHONY: typecheck
typecheck: ## Type check backend and frontend
	$(BACKEND) mypy
	pnpm typecheck

.PHONY: arch
arch: ## Enforce module boundaries
	$(BACKEND) lint-imports

.PHONY: test
test: ## Run the full backend suite
	$(BACKEND) pytest

.PHONY: test-unit
test-unit: ## Unit tests only
	$(BACKEND) pytest tests/unit -q

.PHONY: test-integration
test-integration: ## Integration and E2E tests (requires PostgreSQL)
	$(BACKEND) pytest tests/integration tests/e2e -q

.PHONY: test-workers
test-workers: ## Worker tier tests: real Postgres, real Redis, real Celery worker
	$(BACKEND) pytest tests/integration/test_worker_runtime.py -q

.PHONY: coverage
coverage: ## Coverage report against the module bars
	$(BACKEND) pytest --cov --cov-report=term-missing --cov-report=xml

.PHONY: security
security: ## SAST, dependency and secret scanning
	$(BACKEND) pip-audit || true
	$(BACKEND) bandit -r src -ll || true
	gitleaks detect --no-banner || true

.PHONY: e2e
e2e: ## Playwright browser journeys
	pnpm test:e2e

.PHONY: a11y
a11y: ## Automated accessibility checks
	pnpm a11y

.PHONY: load
load: ## k6 load profiles
	k6 run infra/k6/normal.js

.PHONY: verify
verify: lint typecheck arch test ## Everything CI runs on a pull request

.PHONY: evidence
evidence: ## Regenerate the acceptance evidence matrix
	$(BACKEND) python src/scripts/generate_evidence.py

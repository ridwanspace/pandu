.PHONY: help infra dev api worker web up down test lint type arch unit integration contract coverage evals migrate fmt

help: ## Show targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

infra: ## Start postgres + redis only (for the native dev loop)
	docker compose up -d postgres redis

dev: infra ## Dev loop: infra in docker, api + web natively (run worker/web in other terminals)
	cd backend && uv run alembic upgrade head && uv run uvicorn app.api:app --reload --port 8000

worker: ## Run the arq ingestion worker natively
	cd backend && uv run arq app.worker.WorkerSettings

web: ## Run the Next.js dev server
	cd frontend && pnpm dev

up: ## Full containerized stack
	docker compose --profile app up -d --build

down: ## Stop everything
	docker compose --profile app --profile observability down

# ── Quality gates (mirrors CI) ───────────────────────────────────────────────
lint: ## ruff lint + format check + bandit
	cd backend && uv run ruff check src tests && uv run ruff format --check src tests && uv run bandit -c pyproject.toml -q -r src

fmt: ## Auto-format
	cd backend && uv run ruff check --fix src tests && uv run ruff format src tests

type: ## mypy --strict
	cd backend && uv run mypy

arch: ## import-linter architecture contracts
	cd backend && uv run lint-imports

unit: ## Unit tests (no I/O)
	cd backend && uv run pytest tests/unit tests/architecture -q

integration: ## Integration tests (testcontainers; needs docker)
	cd backend && uv run pytest tests/integration -q -m integration

contract: ## OpenAPI contract tests (schemathesis)
	cd backend && uv run pytest tests/contract -q

coverage: ## Layered gate: 100% on domain+application (unit tests only)
	cd backend && uv run pytest tests/unit tests/architecture -q \
		--cov=src/app --cov-report=term-missing:skip-covered
	cd backend && uv run coverage report \
		--include="src/app/modules/*/domain/*,src/app/modules/*/application/*,src/app/shared/domain/*" \
		--fail-under=100

coverage-full: ## Overall gate: 85% across unit+integration+contract (needs docker)
	cd backend && uv run pytest tests/unit tests/architecture tests/integration tests/contract -q \
		--cov=src/app --cov-report=term-missing:skip-covered
	cd backend && uv run coverage report --fail-under=85

test: lint type arch unit ## The fast gate (what pre-push should run)

migrate: ## Apply migrations
	cd backend && uv run alembic upgrade head

evals: ## Retrieval metrics + ragas suite on the golden dataset (costs tokens)
	cd backend && uv run --group eval python -m evals.run

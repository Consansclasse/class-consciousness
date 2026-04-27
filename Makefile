.PHONY: help install dev test lint typecheck build migrate seed clean

help:
	@echo "Targets:"
	@echo "  install    Install all deps (uv sync + pnpm install)"
	@echo "  dev        Run api + web in parallel"
	@echo "  test       Run all tests"
	@echo "  lint       Lint all code"
	@echo "  typecheck  Type-check all code"
	@echo "  migrate    Run Alembic migrations"
	@echo "  seed       Seed dev corpus (1 work)"
	@echo "  clean      Remove caches and build artifacts"

install:
	uv sync
	pnpm install
	pre-commit install

dev:
	pnpm dev

test:
	uv run pytest
	pnpm test

lint:
	uv run ruff check .
	pnpm lint

typecheck:
	uv run mypy apps/api/src packages/corpus-tools/src
	pnpm typecheck

build:
	pnpm build

migrate:
	@if [ ! -f apps/api/alembic.ini ]; then \
		echo "Alembic non initialisé (phase 0). Skip."; \
	else \
		cd apps/api && uv run alembic upgrade head; \
	fi

seed:
	@if [ ! -d corpus/_seed ]; then \
		echo "Pas de corpus de seed (phase 0). Skip."; \
	else \
		uv run cc-corpus ingest corpus/_seed/*.tei.xml; \
	fi

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

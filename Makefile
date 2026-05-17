.PHONY: help install dev test test-e2e test-eval test-eval-deepeval test-eval-ragas \
        smoke lint typecheck build migrate seed ingest reset clean \
        logs logs-api logs-web logs-db logs-qdrant logs-redis \
        agent-status agent-bootstrap agent-preflight api-check web-check \
        db-snapshot db-restore

COMPOSE := docker compose -f infra/docker-compose.yml

help:
	@echo "Targets:"
	@echo "  install            Install all deps (uv sync + pnpm install + pre-commit)"
	@echo "  agent-bootstrap    One-shot setup for a fresh Claude Code session"
	@echo "  dev                Run api + web in parallel (host mode)"
	@echo "  test               Run all tests (pytest + vitest, marker expensive exclu)"
	@echo "  test-e2e           Run Playwright E2E suite"
	@echo "  test-eval          Run RAG eval suites (DeepEval + RAGAS, coûteux ~\$$4-5)"
	@echo "  agent-preflight    Check API keys + services up before expensive tests"
	@echo "  smoke              Quick health check of the 5 services"
	@echo "  lint               Lint all code (ruff + biome)"
	@echo "  typecheck          Type-check all code (mypy + astro check)"
	@echo "  migrate            Run Alembic migrations"
	@echo "  seed               Seed dev corpus"
	@echo "  reset              Reset DB + Qdrant + Redis (dev only)"
	@echo "  logs               Tail logs from all services"
	@echo "  logs-api|web|db    Tail logs from one service"
	@echo "  agent-status       Show docker ps + alembic head + browsers"
	@echo "  api-check FILE=    Lint+typecheck a single API file"
	@echo "  web-check FILE=    Lint+typecheck a single web file"
	@echo "  db-snapshot        pg_dump current dev DB to ops/snapshots/"
	@echo "  db-restore SNAP=   Restore a snapshot"
	@echo "  clean              Remove caches"

install:
	uv sync --all-packages --all-extras
	pnpm install
	pre-commit install

agent-bootstrap: install
	$(COMPOSE) up -d
	@echo "Waiting for healthchecks..."
	@sleep 5
	-cd apps/web && pnpm exec playwright install --with-deps chromium
	@if [ ! -f apps/web/.claude/agents/planner.md ] && [ ! -f .claude/agents/planner.md ]; then \
		echo "→ Initialising Playwright Agents (planner/generator/healer)…"; \
		cd apps/web && pnpm exec playwright init-agents --loop=claude || true; \
	else \
		echo "→ Playwright Agents already initialised, skipping."; \
	fi
	-$(MAKE) migrate
	-$(MAKE) seed
	$(MAKE) smoke
	@echo "✅ Agent bootstrap complete."

dev:
	pnpm dev

test:
	uv run pytest
	pnpm test

test-e2e:
	cd apps/web && pnpm exec playwright test

# Suites eval RAG (DeepEval + RAGAS sur 12 golden questions Bilan n°1).
# Coûte ~$3-5 par run (API Anthropic). Marker @pytest.mark.expensive,
# exclus du `make test` par défaut. Nécessite ANTHROPIC_API_KEY + cc-embed up.
test-eval: agent-preflight
	uv run pytest apps/api/tests/eval -v --no-cov -m expensive

test-eval-deepeval: agent-preflight
	uv run pytest apps/api/tests/eval/test_rag_deepeval.py -v --no-cov -m expensive

test-eval-ragas: agent-preflight
	uv run pytest apps/api/tests/eval/test_rag_ragas.py -v --no-cov -m expensive

# Pre-flight : vérifie env vars + services up avant les tests coûteux.
agent-preflight:
	@test -n "$$ANTHROPIC_API_KEY" || (echo "❌ ANTHROPIC_API_KEY manquant (source .env ou export)"; exit 1)
	@$(COMPOSE) ps --status running --services 2>/dev/null | grep -q postgres || (echo "❌ Postgres down — lance 'make agent-bootstrap'"; exit 1)
	@echo "✅ pre-flight OK : ANTHROPIC_API_KEY présent, Postgres up"

smoke:
	@echo "→ API /health"
	@curl -sf http://localhost:8000/health | head -c 200 && echo
	@echo "→ Web /"
	@curl -sf -o /dev/null -w "HTTP %{http_code}\n" http://localhost:3000/
	@echo "→ Postgres"
	@$(COMPOSE) exec -T postgres pg_isready -U cc -q && echo "ok"
	@echo "→ Qdrant"
	@curl -sf http://localhost:6333/healthz | head -c 200 && echo
	@echo "→ Redis"
	@$(COMPOSE) exec -T redis redis-cli ping

lint:
	uv run ruff check .
	pnpm lint

typecheck:
	uv run mypy apps/api/src packages/corpus-tools/src
	pnpm typecheck

build:
	pnpm build

migrate:
	@if [ ! -d apps/api/alembic/versions ] || [ -z "$$(ls -A apps/api/alembic/versions 2>/dev/null)" ]; then \
		echo "Aucune migration Alembic (phase 0). Skip."; \
	else \
		cd apps/api && uv run alembic upgrade head; \
	fi

seed:
	@if [ ! -d corpus/_seed ]; then \
		echo "Pas de corpus de seed. Skip."; \
	else \
		uv run cc-corpus ingest corpus/_seed/*.tei.xml; \
	fi

ingest:
	@test -n "$(FILES)" || (echo "Usage: make ingest FILES='corpus/_seed/*.tei.xml'"; exit 1)
	uv run cc-corpus ingest $(FILES)

reset:
	@curl -sf -X POST http://localhost:8000/__debug/reset || \
		(echo "API down or endpoint not available. Falling back to compose reset."; \
		 $(COMPOSE) down -v && $(COMPOSE) up -d)

logs:
	$(COMPOSE) logs -f --tail=200

logs-api:
	$(COMPOSE) logs -f --tail=200 api

logs-web:
	$(COMPOSE) logs -f --tail=200 web

logs-db:
	$(COMPOSE) logs -f --tail=200 postgres

logs-qdrant:
	$(COMPOSE) logs -f --tail=200 qdrant

logs-redis:
	$(COMPOSE) logs -f --tail=200 redis

agent-status:
	@echo "═══ Services ═══"
	@$(COMPOSE) ps
	@echo ""
	@echo "═══ Alembic ═══"
	@if [ -d apps/api/alembic/versions ] && [ -n "$$(ls -A apps/api/alembic/versions 2>/dev/null)" ]; then \
		cd apps/api && uv run alembic current 2>/dev/null || echo "(no head)"; \
	else \
		echo "(no migrations yet)"; \
	fi
	@echo ""
	@echo "═══ Git ═══"
	@git log --oneline -5
	@echo ""
	@echo "═══ Playwright browsers ═══"
	@cd apps/web && pnpm exec playwright --version 2>/dev/null || echo "(not installed)"
	@echo ""
	@echo "═══ Chrome DevTools MCP RSS (watchdog) ═══"
	@pid=$$(pgrep -f chrome-devtools-mcp 2>/dev/null | head -1); \
	if [ -n "$$pid" ]; then \
		rss=$$(ps -o rss= -p $$pid 2>/dev/null); \
		echo "pid=$$pid rss=$${rss}KB"; \
		if [ "$$rss" -gt 512000 ]; then \
			echo "⚠️  RSS > 500MB — consider restarting (memory leak Issue #1192)"; \
		fi; \
	else \
		echo "(not running)"; \
	fi

api-check:
	@if [ -z "$(FILE)" ]; then \
		uv run ruff check apps/api/src; \
		uv run mypy apps/api/src; \
	else \
		uv run ruff check $(FILE); \
		uv run mypy $(FILE); \
	fi

web-check:
	@if [ -z "$(FILE)" ]; then \
		pnpm --filter web lint && pnpm --filter web typecheck; \
	else \
		pnpm exec biome check $(FILE); \
	fi

db-snapshot:
	@mkdir -p ops/snapshots
	@stamp=$$(date +%Y%m%d-%H%M%S); \
	$(COMPOSE) exec -T postgres pg_dump -U cc -Fc class_consciousness > ops/snapshots/cc-$$stamp.dump; \
	echo "Snapshot ops/snapshots/cc-$$stamp.dump"

db-restore:
	@test -n "$(SNAP)" || (echo "Usage: make db-restore SNAP=ops/snapshots/cc-YYYYMMDD-HHMMSS.dump"; exit 1)
	@$(COMPOSE) exec -T postgres pg_restore -U cc -d class_consciousness --clean --if-exists < $(SNAP)
	@echo "Restored from $(SNAP)"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

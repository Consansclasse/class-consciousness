.PHONY: help install dev test test-e2e test-eval test-eval-deepeval test-eval-ragas \
        smoke lint typecheck build migrate seed ingest reset clean \
        restart-web restart-api \
        logs logs-api logs-web logs-db logs-qdrant logs-redis \
        agent-status agent-bootstrap agent-preflight api-check web-check \
        db-snapshot db-restore \
        embed-gpu embed-gpu-stop sandbox-up sandbox-down sandbox-logs sandbox-seed

COMPOSE := docker compose -f infra/docker-compose.yml

# Sandbox prod-like, embeddings/reranking délégués au GPU local (override .gpu).
# La prod reste CPU (ADR-0008) : ces fichiers ne sont JAMAIS déployés.
SANDBOX := docker compose -p cc-sandbox --env-file infra/.env.sandbox \
	-f docker-compose.prod.yml -f infra/docker-compose.sandbox.yml \
	-f infra/docker-compose.sandbox.gpu.yml
EMBED_GPU_VENV := .venv-embed-gpu

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

# Sous Colima/macOS, inotify ne traverse pas le bind mount → `astro dev` et
# `uvicorn --reload` ne rechargent PAS sur édition hôte. Forcer le rechargement
# du code en redémarrant le conteneur concerné (~1-2 s).
restart-web:
	$(COMPOSE) restart web

restart-api:
	$(COMPOSE) restart api

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

# ─── Local GPU (OBLIGATOIRE en local — voir feedback_local_gpu_mandatory) ───
# cc-embed natif sur l'hôte, device=cuda, port 8011 (8001 pris par artedusa).
# Refuse de démarrer si CUDA indisponible : jamais de fallback CPU silencieux.
embed-gpu:
	@test -x $(EMBED_GPU_VENV)/bin/python || (echo "❌ venv GPU absent ($(EMBED_GPU_VENV)). Crée-le : uv venv $(EMBED_GPU_VENV) && uv pip install --python $(EMBED_GPU_VENV)/bin/python --index-url https://download.pytorch.org/whl/cu124 torch && uv pip install --python $(EMBED_GPU_VENV)/bin/python transformers accelerate fastapi 'uvicorn[standard]' pydantic pydantic-settings structlog"; exit 1)
	@$(EMBED_GPU_VENV)/bin/python -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)" || (echo "❌ CUDA indisponible dans le venv GPU — refus de fallback CPU en local"; exit 1)
	@curl -sf http://localhost:8011/health >/dev/null 2>&1 && { echo "✅ cc-embed GPU déjà up (:8011)"; exit 0; } || true
	@mkdir -p .hf-cache
	@CC_EMBED_HOST=0.0.0.0 CC_EMBED_PORT=8011 CC_EMBED_DEVICE=cuda CC_EMBED_RERANK_DEVICE=cuda \
		HF_HOME=$(CURDIR)/.hf-cache PYTHONPATH=$(CURDIR)/apps/embed-server/src USER=ccembed \
		nohup $(EMBED_GPU_VENV)/bin/python -m cc_embed > .embed-gpu.log 2>&1 &
	@echo "→ cc-embed GPU démarré (log .embed-gpu.log). Attente du health…"
	@for i in $$(seq 1 40); do curl -sf http://localhost:8011/health >/dev/null 2>&1 && { curl -s http://localhost:8011/health; echo; exit 0; }; sleep 3; done; echo "❌ timeout health :8011 — voir .embed-gpu.log"; exit 1

embed-gpu-stop:
	@pkill -f "cc_embed" 2>/dev/null && echo "cc-embed GPU arrêté" || echo "(aucun process cc-embed)"

# Stack sandbox : démarre d'ABORD le GPU embed (dépendance), puis les conteneurs.
sandbox-up: embed-gpu
	$(SANDBOX) up -d
	@echo "✅ Sandbox up — web https://cc.localhost | api https://api.cc.localhost | mails http://localhost:8026"

sandbox-down:
	$(SANDBOX) down

sandbox-logs:
	$(SANDBOX) logs -f --tail=200

# Ingestion du corpus RÉEL (repo class-consciousness-corpus, monté sur
# /app/corpus-prod) DANS la sandbox (Postgres + Qdrant cc-sandbox), via le
# cc-embed GPU. Lancé depuis l'hôte. Pour ingérer la fixture de test à la place :
# SANDBOX_SEED_GLOB=/app/corpus/_seed/*.tei.xml make sandbox-seed
# NB : on n'utilise PAS `cc-corpus` (qui POST /admin/ingest, route montée
# seulement si CC_API_ENV=dev — absente en sandbox prod-like → 404). On appelle
# directement `ingest_issue`, qui prend ses connexions des globals de l'app
# (Postgres/Qdrant cc-sandbox + embed GPU :8011). Idempotent par SHA256.
SANDBOX_SEED_GLOB ?= /app/corpus-prod/bilan/*.tei.xml
define SANDBOX_SEED_PY
import asyncio, glob, os
from pathlib import Path
from cc_api.services.ingest import ingest_issue
from cc_api.clients.embed import get_embed_client
from cc_api.clients.qdrant import get_qdrant
async def main():
    files = sorted(glob.glob(os.environ["SANDBOX_SEED_GLOB"]))
    if not files:
        print(f"Aucun .tei.xml pour {os.environ['SANDBOX_SEED_GLOB']}"); return
    # Clients partagés pour tout le batch : ingest_issue ne ferme que ce qu'il
    # crée (owns_embed), donc sans partage le 1er appel ferme le client global.
    embed = get_embed_client(); qdrant = get_qdrant()
    ok = dup = err = chunks = 0
    try:
        for f in files:
            try:
                r = await ingest_issue(Path(f), embed=embed, qdrant=qdrant)
                print(f"✓ {Path(f).name}: {r.n_articles} art, {r.n_chunks} chunks, dup={r.was_duplicate}")
                dup += r.was_duplicate; ok += (not r.was_duplicate); chunks += r.n_chunks
            except Exception as exc:
                err += 1; print(f"✗ {Path(f).name}: {type(exc).__name__}: {str(exc)[:120]}")
    finally:
        await embed.aclose()
    print(f"--- BILAN : {ok} ingéré(s), {dup} doublon(s), {err} échec(s), {chunks} chunks sur {len(files)} fichier(s)")
asyncio.run(main())
endef
export SANDBOX_SEED_PY
export SANDBOX_SEED_GLOB
sandbox-seed:
	@$(SANDBOX) exec -T -e SANDBOX_SEED_GLOB="$(SANDBOX_SEED_GLOB)" api /app/.venv/bin/python -c "$$SANDBOX_SEED_PY"

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

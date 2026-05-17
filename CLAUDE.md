# CLAUDE.md — class-consciousness

Archive open-source de la théorie marxiste avec RAG sourcé. Monorepo `pnpm` + `uv`. Toutes les réponses Claude Code se font en **français**.

## Stack

- **Backend** : FastAPI 0.115 + SQLAlchemy async + Alembic — `apps/api/` (port 8000).
- **Frontend** : Astro 5 + îlots React — `apps/web/` (port 3000).
- **DB** : Postgres 17 (`cc` / `class_consciousness`, port 5432).
- **Vecteurs** : Qdrant (port 6333) — embeddings + reranking via `cc-embed` (Qwen3-Embedding-0.6B / Qwen3-Reranker-0.6B, CPU).
- **Cache** : Redis 7 (port 6379).
- **LLM** : Anthropic Claude Opus 4.7 (`ANTHROPIC_MODEL`).
- **Proxy** : Caddy (ports 80/443).

## Lancer / tester

| Commande | Effet |
|---|---|
| `make agent-bootstrap` | Bootstrap complet (install + docker + migrate + seed + smoke). |
| `make dev` | API + Web en parallèle (hot-reload). |
| `make logs` / `make logs-api` | Tail logs unifiés JSON. |
| `make smoke` | Vérification rapide santé des 5 services. |
| `make test` | pytest + vitest. |
| `make agent-status` | État services + migrations + browsers Playwright. |

## Sous-CLAUDE.md

- `apps/api/CLAUDE.md` — conventions FastAPI, routers, Alembic, structlog.
- `apps/web/CLAUDE.md` — conventions Astro, locators Playwright, accessibilité.
- `.claude/AGENT_GUIDE.md` — principes non-négociables, décisions verrouillées, sources corpus.
- `.claude/rules/` — règles d'or attachées (RAG sourcé, branche unique).

## Règles dures

1. **Aucune phrase sans citation littéralement vérifiée** dans les sorties RAG.
2. **Branche `main` uniquement** — jamais de feature branches ni de PR.
3. **Pas de commit non sollicité** — l'utilisateur commit lui-même.
4. **Pas de mocks** : tests = vrais services via testcontainers.
5. **Conventional Commits** obligatoires quand commit demandé, en français.

Plus de détails : `.claude/AGENT_GUIDE.md`.

# CLAUDE.md — apps/api (cc-api)

Backend FastAPI Python 3.12. Toutes les opérations DB sont **async** (asyncpg + SQLAlchemy 2.0 `AsyncSession`).

## Arborescence

```
src/cc_api/
├── main.py            # app FastAPI, mount routers
├── core/              # settings, logging, sécurité, deps DI
├── clients/           # qdrant.py, redis.py, anthropic.py, voyage.py
├── models/            # SQLAlchemy ORM
├── schemas/           # Pydantic v2
├── services/          # logique métier (RAG, ingestion, etc.)
└── routers/           # endpoints HTTP
```

## Ajouter un endpoint

1. Schema Pydantic dans `schemas/`.
2. Service dans `services/` (async, prend `AsyncSession` + clients en deps).
3. Router dans `routers/` avec `@router.get(...)` et response_model.
4. Mount dans `main.py` : `app.include_router(...)`.
5. Test pytest dans `tests/integration/test_<router>.py` — utilise la fixture `app` du `conftest.py`.

## Logging

`structlog` JSON, configuré dans `core/logging.py`. Toujours `logger = structlog.get_logger(__name__)`. Niveau via `CC_API_LOG_LEVEL` env.

## Migrations Alembic

```bash
cd apps/api
uv run alembic revision --autogenerate -m "description"
uv run alembic upgrade head
```

Migrations dans `apps/api/alembic/versions/`. La première migration installe les extensions Postgres requises par Postgres MCP Pro : `pg_stat_statements`, `hypopg`.

## Tests

- `pytest -q` (rapide), `pytest --cov` (avec couverture).
- **Pas de mocks DB ou Qdrant** : `conftest.py` lance des testcontainers Postgres+Qdrant éphémères.
- Marquer `@pytest.mark.skip(reason="phase 0")` les tests dont le code n'existe pas encore.

## Endpoint debug `/__debug/*`

Activé uniquement si `CC_API_ENV=dev`. Sert de vue panoptique pour l'IA :
- `GET /__debug/state` — counts par table + collections Qdrant + Redis keys + git sha + Alembic head.
- `GET /__debug/logs?service=api&n=200` — tail logs JSON.
- `POST /__debug/seed` — fixtures académiques reproductibles.
- `POST /__debug/reset` — drop+recreate (refuse si non-dev).

## Conventions

- Async partout. Pas de `def` sync sur les routes ou services.
- Settings : `cc_api.core.settings.Settings` (pydantic-settings, lit env `CC_API_*`).
- Imports : `from cc_api.X import Y` (jamais `from src...`).
- Type hints obligatoires (mypy strict via pyproject).

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Endpoint debug — vue panoptique pour l'agent IA.

Activé uniquement si `CC_API_ENV=dev`. Garde-fou strict sur les routes destructives.
"""
from __future__ import annotations

import os
import subprocess
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import text

from cc_api.clients.db import get_session_maker
from cc_api.clients.qdrant import get_qdrant
from cc_api.clients.redis import get_redis
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings

router = APIRouter(prefix="/__debug", tags=["debug"], include_in_schema=False)
log = get_logger(__name__)


def _ensure_dev() -> None:
    if not settings.is_dev:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"__debug routes disabled (CC_API_ENV={settings.env})",
        )


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd="/app", stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "unknown"


def _alembic_head() -> str:
    try:
        result = subprocess.check_output(
            ["alembic", "current"], cwd="/app/apps/api", stderr=subprocess.DEVNULL
        ).decode().strip()
        return result or "(none)"
    except Exception:
        return "unknown"


@router.get("/state")
async def state() -> dict[str, Any]:
    """Vue panoptique de l'état de l'app."""
    _ensure_dev()

    # Postgres : counts par table
    tables: dict[str, int] = {}
    try:
        async with get_session_maker()() as session:
            rows = await session.execute(
                text(
                    "SELECT schemaname || '.' || tablename AS t "
                    "FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')"
                )
            )
            table_names = [r[0] for r in rows]
            for t in table_names:
                count = await session.execute(text(f'SELECT count(*) FROM {t}'))
                tables[t] = int(count.scalar() or 0)
    except Exception as exc:
        tables = {"_error": str(exc)}

    # Qdrant : collections + counts
    qdrant_state: dict[str, Any] = {}
    try:
        client = get_qdrant()
        cols = await client.get_collections()
        for c in cols.collections:
            info = await client.get_collection(c.name)
            vectors_config = info.config.params.vectors
            dims: int | None
            if hasattr(vectors_config, "size"):
                dims = vectors_config.size  # type: ignore[union-attr]
            else:
                dims = None
            qdrant_state[c.name] = {
                "vectors_count": info.points_count,
                "dims": dims,
            }
    except Exception as exc:
        qdrant_state = {"_error": str(exc)}

    # Redis : nb clés + sample
    redis_state: dict[str, Any] = {}
    try:
        r = get_redis()
        size = await r.dbsize()
        sample = []
        async for key in r.scan_iter(count=10):
            ttl = await r.ttl(key)
            sample.append({"key": key, "ttl": ttl})
            if len(sample) >= 10:
                break
        redis_state = {"size": size, "sample": sample}
    except Exception as exc:
        redis_state = {"_error": str(exc)}

    return {
        "env": settings.env,
        "git": _git_sha(),
        "alembic": _alembic_head(),
        "postgres": {"tables": tables},
        "qdrant": qdrant_state,
        "redis": redis_state,
    }


@router.get("/logs")
async def logs(
    service: str = Query("api", pattern=r"^(api|web|postgres|qdrant|redis|caddy)$"),
    n: int = Query(200, ge=1, le=2000),
) -> dict[str, Any]:
    """Tail des logs JSON d'un service via docker compose."""
    _ensure_dev()
    try:
        out = subprocess.check_output(
            [
                "docker", "compose", "-f", "/app/infra/docker-compose.yml",
                "logs", "--tail", str(n), "--no-color", service,
            ],
            stderr=subprocess.STDOUT,
            timeout=10,
        ).decode(errors="replace")
        return {"service": service, "n": n, "lines": out.splitlines()}
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.output.decode(errors="replace"))
    except FileNotFoundError:
        # docker CLI absent dans le conteneur — fallback : lire stdout du process courant n'est pas trivial
        raise HTTPException(status_code=501, detail="docker CLI not available inside API container")


@router.post("/seed")
async def seed() -> dict[str, Any]:
    """Seeds reproductibles (fixtures académiques minimales)."""
    _ensure_dev()
    # TODO chantier ultérieur : appeler cc_corpus.ingest sur corpus/_seed/
    log.info("debug.seed.called")
    return {"status": "noop", "reason": "seed pipeline not implemented yet (phase 0)"}


@router.post("/reset")
async def reset() -> dict[str, Any]:
    """Drop+recreate DB schemas + collections Qdrant + flush Redis. Dev only."""
    _ensure_dev()
    if os.getenv("CC_API_ENV", "dev") != "dev":
        raise HTTPException(status_code=403, detail="reset refused outside dev")

    results: dict[str, Any] = {}

    # Postgres : drop all + recreate public schema
    try:
        async with get_session_maker()() as session:
            await session.execute(text("DROP SCHEMA public CASCADE"))
            await session.execute(text("CREATE SCHEMA public"))
            await session.commit()
        results["postgres"] = "dropped+recreated public schema"
    except Exception as exc:
        results["postgres"] = f"error: {exc}"

    # Qdrant : delete all collections
    try:
        client = get_qdrant()
        cols = await client.get_collections()
        for c in cols.collections:
            await client.delete_collection(c.name)
        results["qdrant"] = f"deleted {len(cols.collections)} collections"
    except Exception as exc:
        results["qdrant"] = f"error: {exc}"

    # Redis : flush
    try:
        r = get_redis()
        await r.flushdb()
        results["redis"] = "flushed"
    except Exception as exc:
        results["redis"] = f"error: {exc}"

    log.warning("debug.reset.executed", results=results)
    return results

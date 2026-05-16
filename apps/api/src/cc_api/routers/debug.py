# SPDX-License-Identifier: AGPL-3.0-or-later
"""Endpoint debug — vue panoptique pour l'agent IA.

Activé uniquement si `CC_API_ENV=dev`. Garde-fou strict sur les routes destructives.
"""

from __future__ import annotations

import subprocess
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text

from cc_api.clients.db import get_session_maker
from cc_api.clients.qdrant import get_qdrant
from cc_api.clients.redis import get_redis
from cc_api.core.logging import get_logger
from cc_api.core.security import require_dev
from cc_api.core.settings import settings

router = APIRouter(
    prefix="/__debug",
    tags=["debug"],
    include_in_schema=False,
    dependencies=[Depends(require_dev)],
)
log = get_logger(__name__)


def _git_sha() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd="/app", stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
    except Exception:
        return "unknown"


def _alembic_head() -> str:
    try:
        result = (
            subprocess.check_output(
                ["alembic", "current"], cwd="/app/apps/api", stderr=subprocess.DEVNULL
            )
            .decode()
            .strip()
        )
        return result or "(none)"
    except Exception:
        return "unknown"


@router.get("/state")
async def state() -> dict[str, Any]:
    """Vue panoptique de l'état de l'app."""
    # Postgres : counts par table
    tables: dict[str, int | str] = {}
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
                count = await session.execute(text(f"SELECT count(*) FROM {t}"))  # noqa: S608
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
    try:
        out = subprocess.check_output(
            [
                "docker",
                "compose",
                "-f",
                "/app/infra/docker-compose.yml",
                "logs",
                "--tail",
                str(n),
                "--no-color",
                service,
            ],
            stderr=subprocess.STDOUT,
            timeout=10,
        ).decode(errors="replace")
        return {"service": service, "n": n, "lines": out.splitlines()}
    except subprocess.CalledProcessError as exc:
        raise HTTPException(status_code=500, detail=exc.output.decode(errors="replace"))
    except FileNotFoundError:
        # docker CLI absent dans le conteneur — fallback non-trivial
        raise HTTPException(status_code=501, detail="docker CLI not available inside API container")


@router.post("/seed")
async def seed() -> dict[str, Any]:
    """Seeds reproductibles : ingère la fixture canonique TEI.

    L'ingestion requiert le serveur cc-embed (embeddings) joignable ; à défaut,
    `ingest_issue` lèvera une erreur explicite.
    """
    from pathlib import Path

    candidates = [
        Path("/app/corpus/_seed/bilan-001.tei.xml"),
        Path(__file__).resolve().parents[4] / "corpus" / "_seed" / "bilan-001.tei.xml",
    ]
    fixture = next((p for p in candidates if p.exists()), None)
    if fixture is None:
        log.warning("debug.seed.fixture_missing", candidates=[str(p) for p in candidates])
        return {"status": "skipped", "reason": "fixture TEI introuvable"}

    from cc_api.services.ingest import ingest_issue

    ref = await ingest_issue(fixture)
    log.info("debug.seed.done", issue_id=ref.issue_id, n_chunks=ref.n_chunks)
    return {
        "status": "ok",
        "issue_id": ref.issue_id,
        "slug": ref.slug,
        "ark": ref.ark,
        "n_articles": ref.n_articles,
        "n_chunks": ref.n_chunks,
        "was_duplicate": ref.was_duplicate,
    }


@router.post("/reset")
async def reset() -> dict[str, Any]:
    """Drop+recreate DB schemas + collections Qdrant + flush Redis. Dev only."""
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

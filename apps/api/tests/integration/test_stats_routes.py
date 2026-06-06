# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration de l'observabilité — /admin/rag/stats et /metrics.

La base est un vrai testcontainer Postgres (règle « pas de mock DB »). On seede
des RagInteraction puis on vérifie que les agrégats exposés sont cohérents.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from cc_api.models import RagInteraction


@pytest_asyncio.fixture
async def stats_env(monkeypatch: pytest.MonkeyPatch, migrated_db: str) -> AsyncIterator[None]:
    """Pointe la DB applicative vers le testcontainer et purge les caches."""
    from cc_api.clients import db as db_module
    from cc_api.core.settings import settings

    parsed = urlparse(migrated_db)
    monkeypatch.setattr(settings, "postgres_host", parsed.hostname or "localhost")
    monkeypatch.setattr(settings, "postgres_port", parsed.port or 5432)
    monkeypatch.setattr(settings, "postgres_user", parsed.username or "cc")
    monkeypatch.setattr(settings, "postgres_password", parsed.password or "cc")
    monkeypatch.setattr(settings, "postgres_db", (parsed.path or "/cc_test").lstrip("/"))
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()


def _interaction(
    *,
    refused_reason: str | None = None,
    incomplete: bool = False,
    latency_ms: int = 1000,
    cited: list[str] | None = None,
    gen_input: int = 0,
    gen_output: int = 0,
) -> RagInteraction:
    """Construit une RagInteraction de test au schéma usage complet."""
    return RagInteraction(
        question="Question de test.",
        answer=None if refused_reason else "Réponse.",
        incomplete=incomplete,
        refused_reason=refused_reason,
        model="claude-sonnet-4-6",
        latency_ms=latency_ms,
        latencies={},
        usage={
            "generation": {
                "input_tokens": gen_input,
                "output_tokens": gen_output,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "model": "claude-sonnet-4-6",
            },
            "judge": {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "model": "claude-haiku-4-5",
            },
        },
        sentences=[],
        cited_source_ids=cited or [],
        retrieval_count=0,
        rerank_count=0,
    )


async def test_rag_stats_aggregates_interactions(
    stats_env: None, clean_db: None, client: Any, db_session: Any
) -> None:
    """GET /admin/rag/stats agrège fidèlement les lignes rag_interactions."""
    db_session.add_all(
        [
            _interaction(latency_ms=1000, cited=["bilan-1/a:0"], gen_input=500, gen_output=200),
            _interaction(latency_ms=3000, cited=["bilan-1/a:0", "bilan-1/b:1"]),
            _interaction(refused_reason="no_relevant_chunks", latency_ms=200),
        ]
    )
    await db_session.commit()

    res = client.get("/admin/rag/stats")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 3
    assert data["refused"] == 1
    assert data["refusalRate"] == round(1 / 3, 4)
    assert data["byRefusedReason"] == {"no_relevant_chunks": 1}
    assert data["totalTokens"] == 700
    assert data["latencyP50Ms"] == 1000
    # bilan-1/a:0 est cité par deux interactions → en tête du classement.
    assert data["topCited"][0] == {"sourceId": "bilan-1/a:0", "count": 2}


async def test_rag_stats_empty(stats_env: None, clean_db: None, client: Any) -> None:
    """Sans interaction, les stats sont nulles — aucune division par zéro."""
    res = client.get("/admin/rag/stats")
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["total"] == 0
    assert data["refusalRate"] == 0.0
    assert data["latencyP50Ms"] is None
    assert data["topCited"] == []


def test_metrics_endpoint_exposes_prometheus(client: Any) -> None:
    """/metrics répond au format d'exposition Prometheus."""
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    assert "cc_rag_requests_total" in res.text

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /admin/rag — statistiques agrégées de l'historique RAG.

Rend l'app « queryable » : au lieu de fouiller des logs JSON dispersés, on
interroge directement la table `rag_interactions` — volume, taux de refus,
latence, passages les plus cités, coût en tokens. Dev-only, comme /admin/ingest.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text

from cc_api.clients.db import get_session_maker
from cc_api.core.security import require_dev
from cc_api.schemas.stats import CitedSource, RagStatsResponse

admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_dev)])


# Volume, refus, réponses partielles et latences en une passe.
_SUMMARY_SQL = text(
    """
    SELECT
        count(*) AS total,
        count(refused_reason) AS refused,
        count(*) FILTER (WHERE incomplete) AS incomplete,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS p50,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS p95
    FROM rag_interactions
    """
)

_REFUSALS_SQL = text(
    """
    SELECT refused_reason, count(*) AS n
    FROM rag_interactions
    WHERE refused_reason IS NOT NULL
    GROUP BY refused_reason
    """
)

# Déplie le tableau JSONB des source_ids cités pour les compter un à un.
_TOP_CITED_SQL = text(
    """
    SELECT sid AS source_id, count(*) AS n
    FROM rag_interactions, jsonb_array_elements_text(cited_source_ids) AS sid
    GROUP BY sid
    ORDER BY n DESC, sid
    LIMIT 10
    """
)

# Somme des tokens des deux appels LLM ; COALESCE absorbe les `usage` vides.
_TOKENS_SQL = text(
    """
    SELECT COALESCE(SUM(
        COALESCE((usage->'generation'->>'input_tokens')::bigint, 0)
        + COALESCE((usage->'generation'->>'output_tokens')::bigint, 0)
        + COALESCE((usage->'judge'->>'input_tokens')::bigint, 0)
        + COALESCE((usage->'judge'->>'output_tokens')::bigint, 0)
    ), 0) AS total_tokens
    FROM rag_interactions
    """
)


@admin_router.get("/rag/stats", response_model=RagStatsResponse)
async def rag_stats() -> RagStatsResponse:
    """Agrégats de l'historique RAG — socle d'observabilité du closed-loop."""
    async with get_session_maker()() as session:
        summary = (await session.execute(_SUMMARY_SQL)).one()
        refusals = (await session.execute(_REFUSALS_SQL)).all()
        top_cited = (await session.execute(_TOP_CITED_SQL)).all()
        total_tokens = (await session.execute(_TOKENS_SQL)).scalar_one()

    total = int(summary.total)
    refused = int(summary.refused)
    return RagStatsResponse(
        total=total,
        refused=refused,
        incomplete=int(summary.incomplete),
        refusal_rate=round(refused / total, 4) if total else 0.0,
        by_refused_reason={row.refused_reason: int(row.n) for row in refusals},
        latency_p50_ms=int(summary.p50) if summary.p50 is not None else None,
        latency_p95_ms=int(summary.p95) if summary.p95 is not None else None,
        total_tokens=int(total_tokens),
        top_cited=[CitedSource(source_id=row.source_id, count=int(row.n)) for row in top_cited],
    )

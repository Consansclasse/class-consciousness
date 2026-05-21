# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas des statistiques d'observabilité RAG (`/admin/rag/stats`).

Agrégats de la table `rag_interactions` : ce que l'on peut « interroger » sur
l'app elle-même, au-delà du corpus — le cœur du closed-loop.
"""

from __future__ import annotations

from cc_api.schemas.corpus import _CamelModel


class CitedSource(_CamelModel):
    """Un passage du corpus et son nombre d'occurrences en citation."""

    source_id: str
    count: int


class RagStatsResponse(_CamelModel):
    """Vue agrégée de l'historique des requêtes à l'assistant RAG."""

    total: int  # nombre total d'interactions enregistrées
    refused: int  # interactions soldées par un refus
    incomplete: int  # réponses partielles (mode partiel)
    refusal_rate: float  # refused / total, arrondi (0.0 si aucune interaction)
    by_refused_reason: dict[str, int]  # répartition des refus par cause
    latency_p50_ms: int | None  # latence médiane (None si aucune interaction)
    latency_p95_ms: int | None  # latence au 95ᵉ centile
    total_tokens: int  # tokens cumulés (génération + juge, entrée + sortie)
    top_cited: list[CitedSource]  # passages les plus cités, décroissant

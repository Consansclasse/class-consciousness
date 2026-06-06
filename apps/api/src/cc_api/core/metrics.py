# SPDX-License-Identifier: AGPL-3.0-or-later
"""Métriques Prometheus du pipeline RAG — exposées sur /metrics.

Alimentées à chaque requête /qa (cf. routers/qa.py). Observabilité temps-réel,
complémentaire de la table `rag_interactions` (historique interrogeable) et des
logs structlog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from prometheus_client import Counter, Histogram

from cc_api.core.settings import settings

if TYPE_CHECKING:
    from cc_api.services.rag import RagResult

rag_requests_total = Counter(
    "cc_rag_requests_total",
    "Requêtes à l'assistant RAG, par issue (answered | partial | refused).",
    ["outcome"],
)
rag_sentence_verdicts_total = Counter(
    "cc_rag_sentence_verdicts_total",
    "Verdicts d'ancrage produits, par type.",
    ["verdict"],
)
rag_route_total = Counter(
    "cc_rag_route_total",
    "Décisions de routage de complexité (G3), par route (simple | complexe).",
    ["route"],
)
rag_latency_seconds = Histogram(
    "cc_rag_latency_seconds",
    "Latence bout-en-bout du pipeline RAG.",
    buckets=(1, 2, 5, 10, 20, 40, 60, 90, 120, float("inf")),
)
rag_tokens_total = Counter(
    "cc_rag_tokens_total",
    "Tokens LLM consommés, par modèle et direction (input | output).",
    ["model", "direction"],
)
rag_quota_redis_errors_total = Counter(
    "cc_rag_quota_redis_errors_total",
    "Pannes Redis du quota — le quota bascule alors en fail-open.",
)
rag_billing_errors_total = Counter(
    "cc_rag_billing_errors_total",
    "Échecs d'enregistrement d'usage Stripe (pay-as-you-go) — best-effort, "
    "la réponse RAG n'en est jamais bloquée ; l'usage non facturé est perdu.",
)


def record_rag_result(result: RagResult) -> None:
    """Incrémente les métriques Prometheus depuis un RagResult — in-memory,
    ne peut pas échouer (appelé à chaque requête /qa)."""
    if result.refused_reason is not None:
        outcome = "refused"
    elif result.incomplete:
        outcome = "partial"
    else:
        outcome = "answered"
    rag_requests_total.labels(outcome=outcome).inc()
    rag_latency_seconds.observe(result.latency_ms / 1000)

    # Routage de complexité (G3) — n'instrumente que les routes réelles, pas
    # "off" (routage désactivé) ni None (non déterminée).
    if result.route and result.route != "off":
        rag_route_total.labels(route=result.route).inc()

    for sentence in result.sentences:
        rag_sentence_verdicts_total.labels(verdict=sentence.verdict.value).inc()

    gen = result.generation_usage
    rag_tokens_total.labels(model=result.model, direction="input").inc(gen.input_tokens)
    rag_tokens_total.labels(model=result.model, direction="output").inc(gen.output_tokens)
    if result.citation_report is not None:
        judge = result.citation_report.judge_usage
        judge_model = settings.anthropic_judge_model
        rag_tokens_total.labels(model=judge_model, direction="input").inc(judge.input_tokens)
        rag_tokens_total.labels(model=judge_model, direction="output").inc(judge.output_tokens)

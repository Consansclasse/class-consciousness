# SPDX-License-Identifier: AGPL-3.0-or-later
"""Évaluation RAGAS v2 du pipeline RAG sur les 12 golden questions Bilan n°1.

LLM judge : Claude Opus 4.7 via `LangchainLLMWrapper(ChatAnthropic(...))`.

Métriques (cibles 2026 production-grade) :
- `Faithfulness` ≥ 0.9 — la réponse colle au contexte récupéré.
- `AnswerRelevancy` ≥ 0.85 — la réponse répond bien à la question.
- `ContextPrecision` ≥ 0.8 — les chunks récupérés sont pertinents (sans
  référence externe, en mode `ContextPrecisionWithoutReference`).

Coûts : ~12 questions x 3 métriques RAGAS x 1-2 appels Claude judge ≈ 50 appels.
À ~$0.05 / appel ≈ $2-3 par run complet.

Toutes les fonctions sont marquées `@pytest.mark.expensive`.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from cc_api.services.rag import answer_question

pytestmark = pytest.mark.expensive


def _build_ragas_llm() -> Any:
    """Wrapper LangChain ChatAnthropic vers RAGAS BaseRagasLLM."""
    from langchain_anthropic import ChatAnthropic
    from ragas.llms import LangchainLLMWrapper

    model_name = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    chat = ChatAnthropic(
        model_name=model_name,
        anthropic_api_key=os.environ["ANTHROPIC_API_KEY"],
        temperature=0.0,
        timeout=60,
        max_retries=3,
        stop=None,
    )
    return LangchainLLMWrapper(cast(Any, chat))


async def _collect_test_cases(
    questions: list[dict[str, Any]],
    qdrant_client: Any,
    embed: Any,
    reranker: Any,
    anthropic: Any,
) -> tuple[list[dict[str, Any]], int]:
    """Exécute le pipeline RAG sur chaque question et collecte les cas évaluables."""
    cases: list[dict[str, Any]] = []
    n_refused = 0
    for q in questions:
        result = await answer_question(
            q["question"],
            qdrant=qdrant_client,
            embed=embed,
            reranker=reranker,
            anthropic=anthropic,
        )
        if result.refused_reason is not None or result.answer is None:
            n_refused += 1
            continue
        cases.append(
            {
                "user_input": q["question"],
                "response": result.answer,
                "retrieved_contexts": [c.text for c in result.reranked],
            }
        )
    return cases, n_refused


@pytest.mark.asyncio
async def test_ragas_faithfulness(
    seeded_real_corpus: dict[str, Any],
    qdrant_client: Any,
    real_embed_client: Any,
    real_rerank_client: Any,
    real_anthropic_client: Any,
    golden_questions: dict[str, Any],
) -> None:
    """Faithfulness RAGAS ≥ 0.9 en moyenne sur les questions in-corpus."""
    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics import Faithfulness

    cases, n_refused = await _collect_test_cases(
        golden_questions["questions"],
        qdrant_client,
        real_embed_client,
        real_rerank_client,
        real_anthropic_client,
    )
    refusal_rate = n_refused / len(golden_questions["questions"])
    print(
        f"\n[ragas/faithfulness] {len(cases)} évaluables, {n_refused} refusés ({refusal_rate:.1%})"
    )
    assert len(cases) >= 6, f"Trop de refus ({n_refused}) pour évaluer sérieusement"

    llm = _build_ragas_llm()
    metric = Faithfulness(llm=llm)
    scores: list[float] = []
    for c in cases:
        sample = SingleTurnSample(
            user_input=c["user_input"],
            response=c["response"],
            retrieved_contexts=c["retrieved_contexts"],
        )
        score = await metric.single_turn_ascore(sample)
        scores.append(float(score))

    avg = sum(scores) / len(scores)
    formatted = [f"{s:.2f}" for s in scores]
    print(f"[ragas/faithfulness] avg = {avg:.3f} (cible ≥ 0.9), scores = {formatted}")
    assert avg >= 0.9, f"Faithfulness RAGAS moyenne {avg:.3f} < 0.9"


@pytest.mark.asyncio
async def test_ragas_context_precision_without_reference(
    seeded_real_corpus: dict[str, Any],
    qdrant_client: Any,
    real_embed_client: Any,
    real_rerank_client: Any,
    real_anthropic_client: Any,
    golden_questions: dict[str, Any],
) -> None:
    """LLMContextPrecisionWithoutReference RAGAS ≥ 0.8 — les chunks récupérés
    sont pertinents pour la question (sans nécessiter une référence externe)."""
    from ragas.dataset_schema import SingleTurnSample
    from ragas.metrics import LLMContextPrecisionWithoutReference

    cases, n_refused = await _collect_test_cases(
        golden_questions["questions"],
        qdrant_client,
        real_embed_client,
        real_rerank_client,
        real_anthropic_client,
    )
    assert len(cases) >= 6, f"Trop de refus ({n_refused})"

    llm = _build_ragas_llm()
    metric = LLMContextPrecisionWithoutReference(llm=llm)
    scores: list[float] = []
    for c in cases:
        sample = SingleTurnSample(
            user_input=c["user_input"],
            response=c["response"],
            retrieved_contexts=c["retrieved_contexts"],
        )
        score = await metric.single_turn_ascore(sample)
        scores.append(float(score))
    avg = sum(scores) / len(scores)
    print(f"[ragas/context_precision] avg = {avg:.3f} (cible ≥ 0.8)")
    assert avg >= 0.8, f"ContextPrecision RAGAS moyenne {avg:.3f} < 0.8"

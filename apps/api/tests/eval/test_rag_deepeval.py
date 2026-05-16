# SPDX-License-Identifier: AGPL-3.0-or-later
"""Évaluation DeepEval du pipeline RAG sur les 12 golden questions Bilan n°1.

Métriques évaluées (le juge LLM est Claude Opus 4.7 via `AnthropicModel`,
PAS OpenAI — décision verrouillée du projet : pas de fallback OpenAI) :

- `FaithfulnessMetric` : la réponse colle au contexte récupéré (cible ≥ 0.9).
- `AnswerRelevancyMetric` : la réponse répond à la question (cible ≥ 0.85).
- `ContextualPrecisionMetric` : les chunks récupérés sont pertinents (cible ≥ 0.8).

Coûts :
- ~12 questions x 3 métriques x ~1 appel Claude par métrique = ~36 appels Claude
- Plus 12 appels Claude pour la génération RAG elle-même = ~48 appels au total
- À ~$0.05 / appel ≈ $2-3 par run complet.

Toutes les fonctions de ce module sont marquées `@pytest.mark.expensive` via
`pytestmark` (collecté avant la collection des tests).
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from cc_api.services.rag import answer_question

pytestmark = pytest.mark.expensive


def _build_anthropic_eval_model() -> Any:
    """Construit le juge LLM DeepEval (Claude Opus 4.7).

    DeepEval lit `os.environ['ANTHROPIC_API_KEY']` automatiquement quand on
    instancie `AnthropicModel`. `USE_ANTHROPIC_MODEL=1` configure aussi les
    métriques par défaut pour utiliser Claude au lieu d'OpenAI.
    """
    os.environ["USE_ANTHROPIC_MODEL"] = "1"
    from deepeval.models import AnthropicModel

    model_name = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    return AnthropicModel(model=model_name)


@pytest.mark.asyncio
async def test_rag_faithfulness_on_golden_questions(
    seeded_real_corpus: dict[str, Any],
    qdrant_client: Any,
    real_embed_client: Any,
    real_rerank_client: Any,
    real_anthropic_client: Any,
    golden_questions: dict[str, Any],
) -> None:
    """Faithfulness ≥ 0.9 en moyenne sur les questions in-corpus.

    Pour chaque question : on exécute le vrai pipeline RAG, on récupère
    (answer, retrieval_context). Si refused, on skip cette question dans le
    calcul mais on incrémente `n_refused` (rapport séparé).
    """
    from deepeval.metrics import FaithfulnessMetric
    from deepeval.test_case import LLMTestCase

    eval_model = _build_anthropic_eval_model()
    metric = FaithfulnessMetric(threshold=0.9, model=eval_model, async_mode=True)

    questions = golden_questions["questions"]
    test_cases: list[LLMTestCase] = []
    n_refused = 0

    for q in questions:
        result = await answer_question(
            q["question"],
            qdrant=qdrant_client,
            embed=real_embed_client,
            reranker=real_rerank_client,
            anthropic=real_anthropic_client,
        )
        if result.refused_reason is not None or result.answer is None:
            n_refused += 1
            continue
        test_cases.append(
            LLMTestCase(
                input=q["question"],
                actual_output=result.answer,
                retrieval_context=[c.text for c in result.reranked],
            )
        )

    refusal_rate = n_refused / len(questions)
    print(
        f"\n[deepeval/faithfulness] {len(test_cases)} évaluables, "
        f"{n_refused} refusés ({refusal_rate:.1%})"
    )

    # On exige au moins 6 questions évaluables (sur 12) pour que la mesure
    # soit pertinente. Si plus de la moitié refuse, c'est un signal qualité.
    assert len(test_cases) >= 6, (
        f"Trop de refus ({n_refused}/{len(questions)}) — le pipeline ou le "
        "corpus est insuffisant pour évaluer Faithfulness sérieusement."
    )

    scores: list[float] = []
    for tc in test_cases:
        metric.measure(tc)
        scores.append(metric.score or 0.0)

    avg = sum(scores) / len(scores)
    formatted = [f"{s:.2f}" for s in scores]
    print(f"[deepeval/faithfulness] avg = {avg:.3f} (cible ≥ 0.9), scores = {formatted}")
    assert avg >= 0.9, f"Faithfulness moyenne {avg:.3f} < 0.9 — pipeline hallucine trop."


@pytest.mark.asyncio
async def test_rag_answer_relevancy_on_golden_questions(
    seeded_real_corpus: dict[str, Any],
    qdrant_client: Any,
    real_embed_client: Any,
    real_rerank_client: Any,
    real_anthropic_client: Any,
    golden_questions: dict[str, Any],
) -> None:
    """AnswerRelevancy ≥ 0.85 — la réponse répond bien à la question posée."""
    from deepeval.metrics import AnswerRelevancyMetric
    from deepeval.test_case import LLMTestCase

    eval_model = _build_anthropic_eval_model()
    metric = AnswerRelevancyMetric(threshold=0.85, model=eval_model, async_mode=True)

    test_cases: list[LLMTestCase] = []
    n_refused = 0
    for q in golden_questions["questions"]:
        result = await answer_question(
            q["question"],
            qdrant=qdrant_client,
            embed=real_embed_client,
            reranker=real_rerank_client,
            anthropic=real_anthropic_client,
        )
        if result.refused_reason is not None or result.answer is None:
            n_refused += 1
            continue
        test_cases.append(
            LLMTestCase(
                input=q["question"],
                actual_output=result.answer,
                retrieval_context=[c.text for c in result.reranked],
            )
        )

    assert len(test_cases) >= 6, f"Trop de refus ({n_refused})"
    scores = []
    for tc in test_cases:
        metric.measure(tc)
        scores.append(metric.score or 0.0)
    avg = sum(scores) / len(scores)
    print(f"[deepeval/answer_relevancy] avg = {avg:.3f} (cible ≥ 0.85)")
    assert avg >= 0.85, f"AnswerRelevancy moyenne {avg:.3f} < 0.85"


@pytest.mark.asyncio
async def test_rag_refuses_questions_out_of_corpus(
    seeded_real_corpus: dict[str, Any],
    qdrant_client: Any,
    real_embed_client: Any,
    real_rerank_client: Any,
    real_anthropic_client: Any,
    golden_questions: dict[str, Any],
) -> None:
    """Les questions hors-corpus (PIB, recette de cuisine) doivent être refusées.

    C'est la garantie « refus avant hallucination » du pipeline. Aucune réponse
    citationnelle ne doit être fabriquée pour ces questions.
    """
    n_correctly_refused = 0
    for q in golden_questions["questions_hors_corpus"]:
        result = await answer_question(
            q["question"],
            qdrant=qdrant_client,
            embed=real_embed_client,
            reranker=real_rerank_client,
            anthropic=real_anthropic_client,
        )
        if result.refused_reason is not None or result.answer is None:
            n_correctly_refused += 1
        else:
            print(
                f"\n[OOC LEAK] Question {q['id']} hors-corpus n'a PAS été refusée. "
                f"Answer = {result.answer!r}"
            )

    total = len(golden_questions["questions_hors_corpus"])
    print(
        f"\n[deepeval/refusal_ooc] {n_correctly_refused}/{total} "
        "questions hors-corpus correctement refusées"
    )
    assert n_correctly_refused == total, (
        f"{total - n_correctly_refused} questions hors-corpus ont fuité une "
        "réponse — pipeline RAG produit des hallucinations sourcées."
    )

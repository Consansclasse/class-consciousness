# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du pipeline RAG complet — règle d'or.

Aucune phrase produite par le pipeline ne doit exister sans être ancrée dans le
corpus source. Ces tests valident :

1. Chaque phrase a une citation valide, ses citations directes sont littérales
   ET le juge sémantique la déclare ENTAILED → réponse retournée (`SUPPORTED`).
2. Phrase sans citation, ou jugée NOT_ENTAILED / CONTRADICTED → refus
   `refused_reason="unverified_citations"`, aucune réponse non vérifiée exposée.
3. La structure `Citation` exposée porte les bons identifiants (source_id, ARK,
   offsets) — base pour exports CSL-JSON ultérieurs.

Le LLM Anthropic (génération ET juge) est simulé via `httpx.MockTransport` : la
génération et le juge sont en tool-use forcé, le mock renvoie donc des blocs
`tool_use` structurés. Le reranker et l'embedding sont simulés de même.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest_asyncio
from anthropic import AsyncAnthropic
from cc_api.clients.anthropic import AnthropicClient
from cc_api.clients.embed import LocalRerankClient
from cc_api.core.settings import settings
from cc_api.services.ingest import ingest_issue
from cc_api.services.rag import (
    RerankedChunk,
    _reciprocal_rank_fusion,
    _select_diverse,
    answer_question,
    keyword_search,
)

FIXTURE_SLUG = "fixture-de-test-pipeline-ingestion"
FIRST_CHUNK_FRAGMENT = "Premier paragraphe de la fixture de test"


def _phrase(texte: str, citations: list[str], citations_directes: list[str] | None = None) -> dict:
    """Construit une phrase structurée telle qu'émise par `rediger_reponse`."""
    return {
        "texte": texte,
        "citations": citations,
        "citations_directes": citations_directes or [],
    }


def _make_mock_anthropic(
    paragraphes: list[list[dict]],
    judge_verdict: str = "ENTAILED",
    decompose_ok: bool = True,
) -> AnthropicClient:
    """AnthropicClient mock pour les TROIS passages, en tool-use.

    - Décomposition (`decomposer_question`) → renvoie la question telle quelle.
    - Génération (`rediger_reponse`) → renvoie `paragraphes`.
    - Juge (`rendre_verdicts`) → attribue `judge_verdict` à chaque phrase soumise.

    `decompose_ok=False` simule une décomposition cassée (réponse sans bloc
    tool_use) pour tester la dégradation gracieuse.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        tool_name = body["tool_choice"]["name"]
        usage = {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        if tool_name == "decomposer_question" and not decompose_ok:
            return httpx.Response(
                200,
                json={
                    "id": "msg_mock",
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "text", "text": "sortie cassée"}],
                    "model": "claude-sonnet-4-6",
                    "stop_reason": "end_turn",
                    "usage": usage,
                },
            )
        if tool_name == "rediger_reponse":
            # Schéma plat : liste de phrases, chacune tagguée par `paragraphe`.
            tool_input: dict[str, Any] = {
                "phrases": [
                    {**ph, "paragraphe": pi}
                    for pi, para in enumerate(paragraphes)
                    for ph in para
                ]
            }
        elif tool_name == "decomposer_question":
            # Décomposition mockée : on renvoie la question telle quelle →
            # recherche identique à un pipeline sans décomposition.
            tool_input = {"sous_questions": [body["messages"][0]["content"][0]["text"]]}
        else:
            payload = body["messages"][0]["content"][0]["text"]
            indices = [int(n) for n in re.findall(r"### Phrase (\d+)", payload)]
            tool_input = {
                "verdicts": [
                    {"index": i, "verdict": judge_verdict, "justification": "test"}
                    for i in indices
                ]
            }
        return httpx.Response(
            200,
            json={
                "id": "msg_mock",
                "type": "message",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "tu_mock", "name": tool_name, "input": tool_input}
                ],
                "model": "claude-sonnet-4-6",
                "stop_reason": "tool_use",
                "usage": usage,
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://api.anthropic.com")
    anth = AsyncAnthropic(api_key="sk-mock", http_client=http_client)
    return AnthropicClient(api_key="sk-mock", model="claude-sonnet-4-6", client=anth)


def _make_mock_rerank(base_score: float = 1.0) -> LocalRerankClient:
    """LocalRerankClient sur httpx.MockTransport — score décroissant depuis
    `base_score`. `base_score` bas (< seuil de pertinence) simule un corpus qui
    ne couvre pas la question."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        documents = body["documents"]
        top_k = body.get("top_k") or len(documents)
        n = min(top_k, len(documents))
        return httpx.Response(
            200,
            json={
                "results": [
                    {"index": i, "score": max(0.0, base_score - i * 0.05)} for i in range(n)
                ],
                "model": "Qwen/Qwen3-Reranker-4B",
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport)
    return LocalRerankClient("http://embed-mock", client=http_client)


@pytest_asyncio.fixture
async def seeded_corpus(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Ingère la fixture canonique et expose les source_ids attendus."""
    ref = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )
    yield {
        "ref": ref,
        "issue_slug": ref.slug,
        "article_slug": FIXTURE_SLUG,
        "source_ids": [f"{ref.slug}/{FIXTURE_SLUG}:{i}" for i in range(ref.n_chunks)],
    }


async def test_every_sentence_has_verified_citation(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Cas nominal : citations directes littérales + juge ENTAILED → réponse."""
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [
        [
            _phrase(
                f"Le texte affirme : « {FIRST_CHUNK_FRAGMENT} ».",
                [source_id_0],
                [FIRST_CHUNK_FRAGMENT],
            ),
        ]
    ]

    result = await answer_question(
        "Que dit le premier paragraphe de la fixture ?",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes, judge_verdict="ENTAILED"),
    )

    rejected = [s.text for s in result.sentences if s.verdict.value != "SUPPORTED"]
    assert result.refused_reason is None, f"Refus inattendu — phrases : {rejected}"
    assert result.citation_report is not None
    assert result.citation_report.all_verified is True
    assert all(s.verdict.value == "SUPPORTED" for s in result.sentences)
    assert result.answer is not None
    assert FIRST_CHUNK_FRAGMENT in result.answer
    assert source_id_0 in result.sentences[0].citations


async def test_decomposition_failure_degrades_gracefully(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
    monkeypatch: Any,
) -> None:
    """Si la décomposition échoue, le pipeline retombe sur la seule question
    et répond normalement — la décomposition est un bonus, pas un point dur."""
    from cc_api.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "rag_decomposition_enabled", True)
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [
        [
            _phrase(
                f"Le texte affirme : « {FIRST_CHUNK_FRAGMENT} ».",
                [source_id_0],
                [FIRST_CHUNK_FRAGMENT],
            )
        ]
    ]

    result = await answer_question(
        "Que dit le premier paragraphe ?",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes, decompose_ok=False),
    )

    assert result.refused_reason is None
    assert result.answer is not None
    assert result.citation_report is not None
    assert result.citation_report.all_verified is True


async def test_refuses_when_sentence_has_no_citation(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Une phrase sans citation → verdict UNSOURCED → refus, aucune réponse."""
    paragraphes = [[_phrase("Le matérialisme est une doctrine philosophique.", [])]]

    result = await answer_question(
        "Qu'est-ce que le matérialisme ?",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.citation_report is not None
    assert result.citation_report.all_verified is False
    assert any(s.verdict.value == "UNSOURCED" for s in result.sentences)


async def test_refuses_when_judge_says_not_entailed(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Le juge déclare la phrase NOT_ENTAILED → NOT_SUPPORTED → refus."""
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [[_phrase("Une analyse non soutenue par le passage.", [source_id_0])]]

    result = await answer_question(
        "Question piège",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes, judge_verdict="NOT_ENTAILED"),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.citation_report is not None
    assert result.citation_report.n_rejected >= 1
    assert any(s.verdict.value == "NOT_SUPPORTED" for s in result.sentences)


async def test_refuses_when_judge_flags_contradiction(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Le juge déclare la phrase CONTRADICTED → verdict CONTRADICTED, flaggée."""
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [[_phrase("Une phrase qui détourne le sens du passage.", [source_id_0])]]

    result = await answer_question(
        "Question piège sur le sens",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes, judge_verdict="CONTRADICTED"),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.citation_report is not None
    assert result.citation_report.n_contradicted >= 1
    assert len(result.citation_report.flagged_sentences) >= 1


async def test_refuses_when_direct_quote_not_literal(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Une citation directe absente mot pour mot du chunk → QUOTE_UNVERIFIED."""
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [
        [
            _phrase(
                "Le texte affirme : « une citation inventée de toutes pièces ».",
                [source_id_0],
                ["une citation inventée de toutes pièces"],
            )
        ]
    ]

    result = await answer_question(
        "Question",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.citation_report is not None
    assert any(s.verdict.value == "QUOTE_UNVERIFIED" for s in result.sentences)


async def test_citations_expose_canonical_source_id_and_ark(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Les chunks reranked exposent `source_id` canonique + payload complet."""
    paragraphes = [[_phrase("Texte non vérifiable.", ["irrelevant"])]]
    result = await answer_question(
        "Question quelconque pour exercer le pipeline",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes),
    )

    assert len(result.reranked) >= 1
    valid_source_ids = set(seeded_corpus["source_ids"])
    required_payload_keys = (
        "issue_slug",
        "issue_ark",
        "issue_title",
        "article_slug",
        "article_ark",
        "article_title",
        "author_name",
        "chunk_idx",
        "char_start",
        "char_end",
        "text",
    )

    for chunk in result.reranked:
        assert chunk.source_id in valid_source_ids
        for key in required_payload_keys:
            assert key in chunk.payload, f"clé manquante dans payload : {key}"
        assert isinstance(chunk.payload["char_start"], int)
        assert isinstance(chunk.payload["char_end"], int)
        assert chunk.payload["char_start"] < chunk.payload["char_end"]
        assert chunk.text == chunk.payload["text"]


async def test_partial_mode_keeps_verified_drops_rejected(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Mode partiel : 1 phrase vérifiée + 1 non sourcée → 200, answer = phrase
    vérifiée seule + incomplete=True."""
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [
        [
            _phrase(
                f"Le texte affirme : « {FIRST_CHUNK_FRAGMENT} ».",
                [source_id_0],
                [FIRST_CHUNK_FRAGMENT],
            ),
            _phrase("Une phrase libre sans citation aucune.", []),
        ]
    ]

    result = await answer_question(
        "Test mode partiel",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes, judge_verdict="ENTAILED"),
    )

    assert result.refused_reason is None, "le pipeline doit basculer en mode partiel"
    assert result.incomplete is True
    assert result.answer is not None
    assert FIRST_CHUNK_FRAGMENT in result.answer
    assert "phrase libre sans citation" not in result.answer
    assert any("phrase libre sans citation" in s for s in result.dropped_sentences)


async def test_partial_mode_refuses_when_zero_sentences_verified(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Si AUCUNE phrase n'est vérifiée → refus complet 422."""
    paragraphes = [[_phrase("Première phrase libre.", []), _phrase("Deuxième phrase libre.", [])]]

    result = await answer_question(
        "Test refus complet",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.incomplete is False


async def test_partial_mode_disabled_returns_full_refusal(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
    monkeypatch: Any,
) -> None:
    """`rag_partial_mode_enabled=False` → refus 422 même si une phrase est vérifiée."""
    from cc_api.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "rag_partial_mode_enabled", False)

    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [
        [
            _phrase(
                f"Le texte affirme : « {FIRST_CHUNK_FRAGMENT} ».",
                [source_id_0],
                [FIRST_CHUNK_FRAGMENT],
            ),
            _phrase("Une phrase libre sans citation aucune.", []),
        ]
    ]

    result = await answer_question(
        "Test mode partiel désactivé",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes, judge_verdict="ENTAILED"),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.incomplete is False


async def test_refuses_when_no_relevant_chunks(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
    monkeypatch: Any,
) -> None:
    """Si aucun chunk n'atteint le seuil de pertinence (rerank trop bas), le
    pipeline refuse avec `no_relevant_chunks` — le corpus ne couvre pas la
    question — sans appeler la génération. (Le seuil n'a de sens que reranking
    activé.)"""
    from cc_api.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "rag_rerank_enabled", True)
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [[_phrase("ne devrait jamais être généré.", [source_id_0])]]

    result = await answer_question(
        "Question totalement hors corpus",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(base_score=0.1),
        anthropic=_make_mock_anthropic(paragraphes),
    )

    assert result.refused_reason == "no_relevant_chunks"
    assert result.answer is None
    assert result.reranked == []


async def test_refuses_when_no_chunks_retrieved(
    clean_db: None,
    clean_qdrant: None,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Si Qdrant ne retourne aucun chunk → refus `no_chunks_retrieved` AVANT le LLM."""
    from cc_api.services.ingest import COLLECTION
    from qdrant_client.http.models import Distance, VectorParams

    await qdrant_client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=settings.embed_dim, distance=Distance.COSINE),
    )

    result = await answer_question(
        "Question sur un corpus vide",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic([[_phrase("ne devrait pas être appelé", [])]]),
    )

    assert result.refused_reason == "no_chunks_retrieved"
    assert result.answer is None
    assert result.retrieved == []
    assert result.reranked == []


# ---------------------------------------------------------------------------
# Sélection diversifiée (MMR) — déterministe, sans service
# ---------------------------------------------------------------------------


def _reranked(article: str, score: float) -> RerankedChunk:
    return RerankedChunk(
        source_id=f"bilan-1/{article}:0",
        text="texte",
        retrieval_score=score,
        rerank_score=score,
        payload={"issue_slug": "bilan-1", "article_slug": article},
    )


def test_select_diverse_spreads_across_articles() -> None:
    """Avec un poids de diversité > 0, la sélection couvre plusieurs articles
    au lieu de prendre les 3 meilleurs scores du même article."""
    chunks = [
        _reranked("article-a", 0.90),
        _reranked("article-a", 0.80),
        _reranked("article-a", 0.70),
        _reranked("article-b", 0.60),
        _reranked("article-b", 0.50),
    ]
    selected = _select_diverse(chunks, k=3, diversity_weight=0.1)
    articles = {c.payload["article_slug"] for c in selected}
    assert articles == {"article-a", "article-b"}
    assert [c.rerank_score for c in selected] == [0.90, 0.80, 0.60]


def test_select_diverse_weight_zero_keeps_pure_score_order() -> None:
    """Poids 0 → sélection par score brut (kill-switch de la diversité)."""
    chunks = [
        _reranked("article-a", 0.90),
        _reranked("article-a", 0.80),
        _reranked("article-a", 0.70),
        _reranked("article-b", 0.60),
    ]
    selected = _select_diverse(chunks, k=3, diversity_weight=0.0)
    assert [c.rerank_score for c in selected] == [0.90, 0.80, 0.70]
    assert {c.payload["article_slug"] for c in selected} == {"article-a"}


# ---------------------------------------------------------------------------
# Recherche hybride — RRF (déterministe) + recherche mots-clés (Postgres)
# ---------------------------------------------------------------------------


def test_reciprocal_rank_fusion_favours_ids_in_multiple_lists() -> None:
    """Un id présent dans plusieurs listes classées remonte au-dessus d'un id
    mieux classé mais présent dans une seule."""
    scores = _reciprocal_rank_fusion([["a", "b", "c"], ["b", "d"], ["b", "a"]])
    ranked = sorted(scores, key=lambda p: scores[p], reverse=True)
    assert ranked[0] == "b"  # présent dans les 3 listes
    assert set(ranked) == {"a", "b", "c", "d"}


async def test_keyword_search_matches_seeded_chunk(
    seeded_corpus: dict[str, Any],
    db_session: Any,
) -> None:
    """La recherche plein-texte Postgres retrouve un chunk par mot-clé."""
    hits = await keyword_search(db_session, "fixture parsing", limit=10)
    assert len(hits) >= 1
    pids = {pid for pid, _ in hits}
    assert all(isinstance(pid, str) and pid for pid in pids)
    # Les ranks sont décroissants.
    ranks = [rank for _, rank in hits]
    assert ranks == sorted(ranks, reverse=True)


async def test_keyword_search_empty_query_returns_nothing(
    seeded_corpus: dict[str, Any],
    db_session: Any,
) -> None:
    """Une requête sans terme exploitable ne ramène rien (pas d'erreur)."""
    assert await keyword_search(db_session, "   ", limit=10) == []


async def test_hybrid_pipeline_with_session_answers(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
    db_session: Any,
) -> None:
    """Pipeline complet avec session DB : la recherche hybride (vecteur +
    mots-clés, fusion RRF) est exercée et la réponse est produite."""
    source_id_0 = seeded_corpus["source_ids"][0]
    paragraphes = [
        [
            _phrase(
                f"Le texte affirme : « {FIRST_CHUNK_FRAGMENT} ».",
                [source_id_0],
                [FIRST_CHUNK_FRAGMENT],
            )
        ]
    ]

    result = await answer_question(
        "Que dit le premier paragraphe de la fixture ?",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(paragraphes),
        session=db_session,
    )

    assert result.refused_reason is None
    assert result.answer is not None
    assert result.citation_report is not None
    assert result.citation_report.all_verified is True

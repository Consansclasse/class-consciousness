# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du pipeline RAG complet — règle d'or.

Aucune phrase produite par le pipeline ne doit exister sans citation
littéralement vérifiable dans le corpus source. Ces tests valident :

1. Chaque phrase a au moins une citation `[CITE:source_id]` ET le texte de la
   phrase est littéralement (substring ou fuzzy ≥ 95) présent dans le chunk
   pointé → réponse retournée.
2. Si le LLM produit une phrase non sourcée OU non vérifiable → refus
   `refused_reason="unverified_citations"`, aucune réponse n'est exposée.
3. La structure `Citation` exposée porte les bons identifiants (source_id,
   ARK, offsets caractères) — base pour exports CSL-JSON ultérieurs.

Le LLM Anthropic et le reranker cc-embed sont simulés via `httpx.MockTransport`
(transport, pas mock métier) pour produire des réponses déterministes sans
coût API. L'embedding est simulé via le `mock_embed_client` du conftest.
"""

from __future__ import annotations

import json
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
from cc_api.services.rag import answer_question

FIXTURE_SLUG = "fixture-de-test-pipeline-ingestion"
# Premier chunk de la fixture _seed/bilan-001.tei.xml :
FIRST_CHUNK_FRAGMENT = "Premier paragraphe de la fixture de test. Il valide le parsing TEI P5"


def _make_mock_anthropic(response_text: str) -> AnthropicClient:
    """Crée un AnthropicClient dont l'API messages retourne `response_text`."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "msg_mock",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": response_text}],
                "model": "claude-opus-4-7",
                "stop_reason": "end_turn",
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0,
                },
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://api.anthropic.com")
    anth = AsyncAnthropic(api_key="sk-mock", http_client=http_client)
    return AnthropicClient(api_key="sk-mock", model="claude-opus-4-7", client=anth)


def _make_mock_rerank() -> LocalRerankClient:
    """LocalRerankClient sur httpx.MockTransport — top_k docs, score décroissant."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        documents = body["documents"]
        top_k = body.get("top_k") or len(documents)
        n = min(top_k, len(documents))
        return httpx.Response(
            200,
            json={
                "results": [{"index": i, "score": float(1.0 - i * 0.1)} for i in range(n)],
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
        "article_slug": FIXTURE_SLUG,  # fallback : article slug = slugify(title)
        "source_ids": [f"{ref.slug}/{FIXTURE_SLUG}:{i}" for i in range(ref.n_chunks)],
    }


async def test_every_sentence_has_verified_citation(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Cas nominal : LLM cite un fragment littéral du contexte → réponse renvoyée."""
    source_id_0 = seeded_corpus["source_ids"][0]
    # Le LLM cite littéralement deux fragments distincts du 1er chunk.
    # Chaque phrase doit avoir sa propre citation (règle d'or par phrase).
    mock_response = (
        f"Premier paragraphe de la fixture de test. [CITE:{source_id_0}] "
        f"Il valide le parsing TEI P5. [CITE:{source_id_0}]"
    )

    result = await answer_question(
        "Que dit le premier paragraphe de la fixture ?",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(mock_response),
    )

    unverified = [s.sentence for s in result.sentences if s.verdict.value != "SOURCED_VERIFIED"]
    assert result.refused_reason is None, (
        f"Refus inattendu : {result.refused_reason} — phrases problématiques : {unverified}"
    )
    assert result.answer == mock_response
    assert result.citation_report is not None
    assert result.citation_report.all_verified is True
    assert all(s.verdict.value == "SOURCED_VERIFIED" for s in result.sentences)
    assert len(result.sentences) >= 1
    # La phrase doit citer le source_id attendu.
    assert source_id_0 in result.sentences[0].citations


async def test_refuses_when_sentence_has_no_citation(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Si le LLM produit une phrase sans `[CITE:...]` → refus, aucune réponse."""
    # Phrase plausible mais sans citation explicite.
    mock_response = "Le matérialisme est une doctrine philosophique fondamentale."

    result = await answer_question(
        "Qu'est-ce que le matérialisme ?",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(mock_response),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.citation_report is not None
    assert result.citation_report.all_verified is False
    assert result.citation_report.n_unsourced == 1
    assert any("aucune citation" in s.reason for s in result.sentences)


async def test_refuses_when_paraphrase_not_in_chunk(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Si le LLM paraphrase grossièrement (fuzzy < 95) → refus."""
    source_id_0 = seeded_corpus["source_ids"][0]
    # Paraphrase qui ne contient AUCUN fragment littéral du chunk source.
    mock_response = (
        "La théorie marxiste analyse les rapports de production capitalistes "
        f"selon une dialectique historique. [CITE:{source_id_0}]"
    )

    result = await answer_question(
        "Que dit Bilan sur la dialectique ?",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(mock_response),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.citation_report is not None
    # La phrase est sourced (a un CITE) mais unverified (fuzzy < 95)
    assert result.citation_report.n_sourced_unverified >= 1


async def test_citations_expose_canonical_source_id_and_ark(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Les chunks reranked exposent `source_id` canonique + payload complet
    (issue_slug, article_slug, article_ark, char_start/end), suffisant pour
    construire un export CSL-JSON par la suite.

    On ne contrôle pas quel chunk sera top reranked (dépend de la similarité
    cosinus déterministe sur la query). On vérifie seulement que la STRUCTURE
    du `RerankedChunk` est correcte pour tous les chunks retournés.
    """
    # mock_response arbitraire : on teste le pipeline AVANT verify_citations.
    mock_response = "Texte non vérifiable. [CITE:irrelevant]"
    result = await answer_question(
        "Question quelconque pour exercer le pipeline",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(mock_response),
    )

    # Le pipeline a peut-être refusé (citation invalide), mais reranked est rempli.
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
        # source_id canonique appartient au corpus seedé.
        assert chunk.source_id in valid_source_ids, (
            f"source_id inattendu : {chunk.source_id} ∉ {valid_source_ids}"
        )
        # Payload Qdrant complet (suffisant pour CSL-JSON).
        for key in required_payload_keys:
            assert key in chunk.payload, f"clé manquante dans payload : {key}"
        # Offsets cohérents.
        assert isinstance(chunk.payload["char_start"], int)
        assert isinstance(chunk.payload["char_end"], int)
        assert chunk.payload["char_start"] < chunk.payload["char_end"]
        # Le `text` du payload est cohérent avec chunk.text.
        assert chunk.text == chunk.payload["text"]


async def test_partial_mode_keeps_verified_drops_unsourced(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Mode partiel par défaut : si 1 phrase vérifiée + 1 phrase non sourcée,
    on retourne 200 avec answer = phrase vérifiée seule + incomplete=True."""
    source_id_0 = seeded_corpus["source_ids"][0]
    # 1 phrase vérifiée + 1 phrase libre sans citation.
    mock_response = (
        f"Premier paragraphe de la fixture de test. [CITE:{source_id_0}] "
        "Voici une phrase libre sans citation aucune."
    )

    result = await answer_question(
        "Test mode partiel",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(mock_response),
    )

    assert result.refused_reason is None, "le pipeline doit basculer en mode partiel, pas refuser"
    assert result.incomplete is True
    assert result.answer is not None
    assert "Premier paragraphe de la fixture de test." in result.answer
    # La phrase non vérifiée NE DOIT PAS être dans answer.
    assert "phrase libre sans citation" not in result.answer
    # Elle doit en revanche apparaître dans dropped_sentences.
    assert any("phrase libre sans citation" in s for s in result.dropped_sentences)


async def test_partial_mode_refuses_when_zero_sentences_verified(
    seeded_corpus: dict[str, Any],
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Si AUCUNE phrase n'est vérifiée, le mode partiel ne sauve rien :
    refus complet 422 (refused_reason=unverified_citations)."""
    # 2 phrases sans citation, aucune ne peut être conservée.
    mock_response = "Première phrase libre. Deuxième phrase libre."

    result = await answer_question(
        "Test refus complet",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(mock_response),
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
    """Quand `settings.rag_partial_mode_enabled=False`, on retombe sur le
    comportement strict 422 même si certaines phrases sont vérifiées."""
    from cc_api.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "rag_partial_mode_enabled", False)

    source_id_0 = seeded_corpus["source_ids"][0]
    mock_response = (
        f"Premier paragraphe de la fixture de test. [CITE:{source_id_0}] "
        "Voici une phrase libre sans citation aucune."
    )

    result = await answer_question(
        "Test mode partiel désactivé",
        qdrant=qdrant_client,
        embed=mock_embed_client,
        reranker=_make_mock_rerank(),
        anthropic=_make_mock_anthropic(mock_response),
    )

    assert result.refused_reason == "unverified_citations"
    assert result.answer is None
    assert result.incomplete is False


async def test_refuses_when_no_chunks_retrieved(
    clean_db: None,
    clean_qdrant: None,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Si Qdrant ne retourne aucun chunk (collection absente ou vide), le
    pipeline refuse avec `refused_reason="no_chunks_retrieved"` AVANT d'appeler
    le LLM (économie de coût API)."""
    # Pas d'ingestion : la collection `bilan` n'existe pas → Qdrant lèvera
    # une erreur OU retournera vide. On crée une collection vide pour simuler.
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
        anthropic=_make_mock_anthropic("ne devrait pas être appelé"),
    )

    assert result.refused_reason == "no_chunks_retrieved"
    assert result.answer is None
    assert result.retrieved == []
    assert result.reranked == []

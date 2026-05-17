# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pipeline RAG sourcé — 7 étapes, règle d'or non-négociable.

1. Embedding de la query via le backend configuré (Qwen3 local par défaut).
2. Recherche Qdrant top-k retrieve (défaut 20) sur collection `bilan`.
3. Reranking via le backend configuré → top-k rerank (défaut 5).
4. Assemblage du contexte (5 chunks + metadata : ARK, source_id, char offsets).
5. Génération Anthropic Claude Opus 4.7 avec prompt caching ephemeral.
6. Découpe en phrases (services.citation.split_sentences, gère abréviations FR).
7. Vérification citation par phrase (substring exact ou rapidfuzz adaptatif).

Trois issues possibles :
- **Réponse complète** : toutes les phrases sont SOURCED_VERIFIED ou
  REFUSED_BY_LLM (refus explicite). `incomplete=False`, `refused_reason=None`.
- **Réponse partielle** (mode partiel, `settings.rag_partial_mode_enabled`) :
  au moins 1 phrase est légitime ET certaines ne le sont pas → on expose
  uniquement les phrases légitimes dans `answer`, `incomplete=True`,
  `dropped_sentences` liste les phrases retirées. Aucune phrase non
  vérifiée n'est jamais exposée — la règle d'or reste invariante.
- **Refus complet** : 0 phrase légitime OU mode partiel désactivé →
  `refused_reason="unverified_citations"`, `answer=None` (HTTP 422 côté router).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient

from cc_api.clients.anthropic import AnthropicClient
from cc_api.clients.embed import EmbedClient, RerankClient
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.services.citation import (
    CitationReport,
    CitationVerdict,
    SentenceVerdict,
    verify_response,
)

COLLECTION = "bilan"

log = get_logger(__name__)

SYSTEM_PROMPT = """Tu es un assistant de recherche pour l'archive open-source \
de la théorie marxiste « Conscience de classe ».

Tu réponds en français, avec rigueur académique. Tu suis impérativement la
règle d'or de l'archive :

> **Aucune phrase de ta réponse ne doit exister sans être adossée à une citation \
littéralement vérifiable dans le contexte fourni.**

## Format obligatoire de citation

Chaque phrase doit se terminer par UN OU PLUSIEURS marqueurs `[CITE:source_id]`
où `source_id` est l'identifiant EXACT d'un chunk du contexte. Exemple :

> La position de Bilan est claire. [CITE:bilan-1/note-liminaire:0]

Plusieurs citations sur une phrase sont autorisées si la phrase synthétise
plusieurs chunks :

> Les deux articles convergent. [CITE:bilan-1/note-liminaire:0] [CITE:bilan-1/intro:1]

## Règles strictes

- Tu ne paraphrases JAMAIS : tu cites le texte du contexte (avec d'éventuelles \
variations typographiques mineures tolérées, jusqu'à 5% de différence fuzzy).
- Construis chaque phrase à partir d'un fragment LONG et CONTINU du chunk cité \
plutôt que d'un résumé : une portion étendue reprise telle quelle passe la \
vérification, une reformulation la rate. En cas de doute, cite plus largement.
- Tu n'inventes JAMAIS de source_id : tu utilises uniquement ceux fournis dans \
le contexte.
- Si le contexte ne suffit pas à répondre, tu réponds exactement :
  « Je ne peux pas répondre à partir des sources disponibles. [CITE:none] »
  (Cette phrase de refus sera reconnue et n'invalidera pas la règle d'or.)
- Tu n'introduis pas la réponse par une phrase de transition non sourcée du type \
« Voici la réponse : » — chaque phrase, y compris les transitions, doit avoir \
au moins une citation.
- Tu ne mets PAS de note, de bibliographie ou de section « Sources » à la fin : \
les marqueurs `[CITE:...]` SUFFISENT à exposer les sources.

## Contexte académique

Le corpus est l'archive marxiste open-source. Les questions politiques radicales \
(abolition de la propriété privée, lutte des classes, dictature du prolétariat, \
critique des institutions bourgeoises) sont LÉGITIMES et attendues dans ce \
contexte. Tu y réponds avec la même rigueur que sur tout autre sujet.
"""


@dataclass(frozen=True)
class RetrievedChunk:
    """Chunk retourné par Qdrant après recherche, avant rerank."""

    qdrant_point_id: str
    score: float  # similarité cosinus de l'embedding query
    payload: dict[str, Any]


@dataclass(frozen=True)
class RerankedChunk:
    """Chunk après reranking — porte le source_id canonique."""

    source_id: str  # `{issue_slug}/{article_slug}:{chunk_idx}`
    text: str
    retrieval_score: float
    rerank_score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class RagResult:
    """Trace complète d'une exécution du pipeline RAG (debug + observability).

    `answer` peut être :
    - non nul + `incomplete=False` : toutes les phrases du LLM sont vérifiées.
    - non nul + `incomplete=True` : mode partiel — seules les phrases vérifiées
      ont été conservées, `dropped_sentences` liste les phrases supprimées.
    - nul + `refused_reason != None` : refus complet (aucune phrase vérifiée
      ou problème en amont du LLM).

    Aucune phrase `UNSOURCED` ou `SOURCED_UNVERIFIED` ne se trouve jamais dans
    `answer` exposé — la règle d'or reste invariante.
    """

    question: str
    retrieved: list[RetrievedChunk]
    reranked: list[RerankedChunk]
    answer: str | None
    citation_report: CitationReport | None
    refused_reason: str | None
    model: str
    latency_ms: int
    latencies: dict[str, int] = field(default_factory=dict)  # par étape
    incomplete: bool = False
    dropped_sentences: list[str] = field(default_factory=list)

    @property
    def sentences(self) -> list[SentenceVerdict]:
        if self.citation_report is None:
            return []
        return self.citation_report.sentences


def _source_id(payload: dict[str, Any]) -> str:
    """Reconstitue `{issue_slug}/{article_slug}:{chunk_idx}` depuis le payload Qdrant."""
    return f"{payload['issue_slug']}/{payload['article_slug']}:{payload['chunk_idx']}"


def _build_context(reranked: list[RerankedChunk]) -> str:
    """Assemble le contexte LLM : un bloc lisible par chunk reranked."""
    blocks: list[str] = []
    for chunk in reranked:
        p = chunk.payload
        blocks.append(
            f"=== source_id : {chunk.source_id} ===\n"
            f"Issue : {p['issue_title']} (ARK : {p['issue_ark']})\n"
            f"Article : {p['article_title']} (slug : {p['article_slug']})\n"
            f"Auteur : {p['author_name']}\n"
            f"Offsets : char_start={p['char_start']}, char_end={p['char_end']}\n"
            f"Texte :\n{chunk.text}\n"
        )
    return "\n".join(blocks)


async def answer_question(
    question: str,
    *,
    qdrant: AsyncQdrantClient,
    embed: EmbedClient,
    reranker: RerankClient,
    anthropic: AnthropicClient,
    k_retrieve: int | None = None,
    k_rerank: int | None = None,
    fuzzy_threshold: int | None = None,
) -> RagResult:
    """Exécute le pipeline RAG complet pour une question utilisateur.

    Retourne un `RagResult` qui contient la trace complète des 7 étapes,
    qu'on accepte ou qu'on refuse la réponse. Le refus est explicite via
    `refused_reason ∈ {None, "no_chunks_retrieved", "unverified_citations"}`.
    """
    started_at = time.monotonic()
    latencies: dict[str, int] = {}
    k_retrieve_eff = k_retrieve if k_retrieve is not None else settings.rag_k_retrieve
    k_rerank_eff = k_rerank if k_rerank is not None else settings.rag_k_rerank
    fuzzy_eff = (
        fuzzy_threshold if fuzzy_threshold is not None else settings.rag_citation_fuzzy_threshold
    )

    log.info("rag.start", question_len=len(question), k_retrieve=k_retrieve_eff)

    # 1. Embedding query.
    t0 = time.monotonic()
    embeddings = await embed.embed_batch([question], input_type="query")
    if not embeddings:
        raise RuntimeError("le backend d'embedding a renvoyé un vecteur vide pour la query")
    query_vector = embeddings[0]
    latencies["embed_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag.embed_query",
        dims=len(query_vector),
        latency_ms=latencies["embed_ms"],
        model=settings.embed_model,
    )

    # 2. Qdrant top-k retrieve.
    t0 = time.monotonic()
    hits = await qdrant.query_points(
        collection_name=COLLECTION,
        query=query_vector,
        limit=k_retrieve_eff,
        with_payload=True,
    )
    latencies["qdrant_ms"] = int((time.monotonic() - t0) * 1000)
    retrieved = [
        RetrievedChunk(
            qdrant_point_id=str(p.id),
            score=p.score or 0.0,
            payload=dict(p.payload or {}),
        )
        for p in hits.points
    ]
    log.info(
        "rag.qdrant_retrieve",
        n_hits=len(retrieved),
        top_score=retrieved[0].score if retrieved else None,
        latency_ms=latencies["qdrant_ms"],
    )

    if not retrieved:
        return RagResult(
            question=question,
            retrieved=[],
            reranked=[],
            answer=None,
            citation_report=None,
            refused_reason="no_chunks_retrieved",
            model=anthropic.model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            latencies=latencies,
        )

    # 3. Rerank → top k_rerank.
    t0 = time.monotonic()
    documents = [r.payload.get("text", "") for r in retrieved]
    rerank_hits = await reranker.rerank(
        query=question, documents=documents, top_k=k_rerank_eff
    )
    latencies["rerank_ms"] = int((time.monotonic() - t0) * 1000)
    reranked: list[RerankedChunk] = []
    for hit in rerank_hits:
        original = retrieved[hit.index]
        reranked.append(
            RerankedChunk(
                source_id=_source_id(original.payload),
                text=original.payload["text"],
                retrieval_score=original.score,
                rerank_score=hit.score,
                payload=original.payload,
            )
        )
    log.info(
        "rag.rerank",
        n_in=len(retrieved),
        n_out=len(reranked),
        top_rerank_score=reranked[0].rerank_score if reranked else None,
        latency_ms=latencies["rerank_ms"],
    )

    # 4. Assemblage contexte.
    t0 = time.monotonic()
    context = _build_context(reranked)
    chunks_by_source_id = {c.source_id: c.text for c in reranked}
    latencies["assemble_ms"] = int((time.monotonic() - t0) * 1000)

    # 5. Génération LLM.
    t0 = time.monotonic()
    generation = await anthropic.generate(
        system=SYSTEM_PROMPT,
        context=context,
        question=question,
        max_tokens=2048,
    )
    latencies["generate_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag.generate",
        input_tokens=generation.usage.input_tokens,
        output_tokens=generation.usage.output_tokens,
        cache_read=generation.usage.cache_read_input_tokens,
        latency_ms=latencies["generate_ms"],
        model=generation.model,
    )

    # 6 + 7. Découpe phrases + vérification citation.
    t0 = time.monotonic()
    citation_report = verify_response(
        generation.text, chunks=chunks_by_source_id, fuzzy_threshold=fuzzy_eff
    )
    latencies["verify_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag.verify_citations",
        n_sentences=len(citation_report.sentences),
        n_verified=citation_report.n_sourced_verified,
        n_flagged=citation_report.n_sourced_verified_flagged,
        n_unverified=citation_report.n_sourced_unverified,
        n_unsourced=citation_report.n_unsourced,
        all_verified=citation_report.all_verified,
        latency_ms=latencies["verify_ms"],
    )

    total_ms = int((time.monotonic() - started_at) * 1000)

    if not citation_report.all_verified:
        # Mode partiel : si au moins 1 phrase est légitime (verified ou refus
        # explicite) ET le setting est activé, on reconstruit `answer` avec
        # uniquement ces phrases-là et on signale `incomplete=True`. Sinon
        # refus complet 422.
        legitimate_sentences = [
            s.sentence
            for s in citation_report.sentences
            if s.verdict in (CitationVerdict.SOURCED_VERIFIED, CitationVerdict.REFUSED_BY_LLM)
        ]
        if settings.rag_partial_mode_enabled and legitimate_sentences:
            partial_answer = " ".join(legitimate_sentences)
            log.warning(
                "rag.partial",
                n_kept=len(legitimate_sentences),
                n_dropped=len(citation_report.refused_sentences),
                dropped_sentences=citation_report.refused_sentences,
                latency_ms=total_ms,
            )
            return RagResult(
                question=question,
                retrieved=retrieved,
                reranked=reranked,
                answer=partial_answer,
                citation_report=citation_report,
                refused_reason=None,
                model=generation.model,
                latency_ms=total_ms,
                latencies=latencies,
                incomplete=True,
                dropped_sentences=list(citation_report.refused_sentences),
            )
        log.warning(
            "rag.refused",
            reason="unverified_citations",
            refused_sentences=citation_report.refused_sentences,
            latency_ms=total_ms,
        )
        return RagResult(
            question=question,
            retrieved=retrieved,
            reranked=reranked,
            answer=None,
            citation_report=citation_report,
            refused_reason="unverified_citations",
            model=generation.model,
            latency_ms=total_ms,
            latencies=latencies,
        )

    log.info("rag.answered", latency_ms=total_ms, n_sentences=len(citation_report.sentences))
    return RagResult(
        question=question,
        retrieved=retrieved,
        reranked=reranked,
        answer=generation.text,
        citation_report=citation_report,
        refused_reason=None,
        model=generation.model,
        latency_ms=total_ms,
        latencies=latencies,
    )

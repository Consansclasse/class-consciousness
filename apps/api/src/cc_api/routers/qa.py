# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /qa — pipeline RAG sourcé en exposition HTTP.

POST /qa retourne 200 si toutes les phrases sont SOURCED_VERIFIED, sinon 422
avec `refused_reason` et la liste des phrases problématiques. Aucune réponse
non sourcée ne sort jamais — règle d'or non-négociable.

Rate limit : 10 req/min par IP via slowapi.
"""

from __future__ import annotations

from typing import cast

from anthropic import APIError
from fastapi import APIRouter, HTTPException, Request

from cc_api.clients.anthropic import get_anthropic_client
from cc_api.clients.embed import EmbedServerError, get_embed_client, get_rerank_client
from cc_api.clients.qdrant import get_qdrant
from cc_api.core.logging import get_logger
from cc_api.core.ratelimit import limiter
from cc_api.schemas.qa import Citation, QaRequest, QaResponse, Sentence
from cc_api.services.rag import RagResult, answer_question

router = APIRouter(prefix="/qa", tags=["qa"])
log = get_logger(__name__)


def _build_response(result: RagResult) -> QaResponse:
    cited_chunks = [
        Citation(
            source_id=chunk.source_id,
            issue_slug=cast(str, chunk.payload["issue_slug"]),
            issue_ark=cast(str, chunk.payload["issue_ark"]),
            article_slug=cast(str, chunk.payload["article_slug"]),
            article_ark=cast(str, chunk.payload["article_ark"]),
            article_title=cast(str, chunk.payload["article_title"]),
            author_name=cast(str, chunk.payload["author_name"]),
            chunk_idx=cast(int, chunk.payload["chunk_idx"]),
            char_start=cast(int, chunk.payload["char_start"]),
            char_end=cast(int, chunk.payload["char_end"]),
            quoted_text=chunk.text,
            retrieval_score=chunk.retrieval_score,
            rerank_score=chunk.rerank_score,
        )
        for chunk in result.reranked
    ]
    sentences = [
        Sentence(
            text=v.sentence,
            citations=v.citations,
            verdict=v.verdict.value,
            verified=(v.verdict.value == "SOURCED_VERIFIED"),
            best_score=v.best_score,
            reason=v.reason,
        )
        for v in result.sentences
    ]
    refused_sentences = result.citation_report.refused_sentences if result.citation_report else []
    return QaResponse(
        question=result.question,
        answer=result.answer,
        sentences=sentences,
        cited_chunks=cited_chunks,
        refused_reason=result.refused_reason,
        refused_sentences=refused_sentences,
        incomplete=result.incomplete,
        dropped_sentences=result.dropped_sentences,
        latency_ms=result.latency_ms,
        model=result.model,
        retrieval_count=len(result.retrieved),
        rerank_count=len(result.reranked),
    )


@router.post("", response_model=QaResponse, responses={422: {"model": QaResponse}})
@limiter.limit("10/minute")
async def post_qa(request: Request, payload: QaRequest) -> QaResponse:
    """Pipeline RAG : embed → retrieve → rerank → generate → vérifier citations.

    Le paramètre `request` est requis par slowapi pour extraire l'IP du client
    via `get_remote_address`. Il doit précéder les autres paramètres FastAPI.

    Codes de retour :
    - 200 OK + `incomplete=False` : toutes les phrases du LLM sont vérifiées.
    - 200 OK + `incomplete=True` : succès partiel — seules les phrases vérifiées
      (et les refus explicites du LLM) sont exposées dans `answer`,
      `dropped_sentences` liste les phrases retirées pour défaut de citation.
    - 422 : `refused_reason` non nul (aucune phrase n'a pu être vérifiée OU
      problème en amont du pipeline). Aucune réponse exposée.

    Aucune phrase non vérifiée n'est JAMAIS exposée dans `answer` — la règle
    d'or « aucune phrase sans citation » est invariante.
    """
    qdrant = get_qdrant()
    embed = get_embed_client()
    reranker = get_rerank_client()
    anthropic = get_anthropic_client()

    try:
        result = await answer_question(
            payload.question,
            qdrant=qdrant,
            embed=embed,
            reranker=reranker,
            anthropic=anthropic,
        )
    except EmbedServerError as exc:
        # cc-embed injoignable : dégradation gracieuse (503), pas une 500 nue.
        log.warning("qa.embed_unavailable", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=(
                "Le service d'embedding est momentanément indisponible. "
                "Réessaie dans un instant."
            ),
        ) from exc
    except APIError as exc:
        # Erreur côté API Anthropic (panne, quota, crédits épuisés) : 503 propre.
        log.warning("qa.llm_unavailable", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=(
                "Le service de génération est momentanément indisponible. "
                "Réessaie dans un instant."
            ),
        ) from exc
    response = _build_response(result)
    if result.refused_reason is not None:
        log.info(
            "qa.refused",
            question=payload.question[:80],
            reason=result.refused_reason,
            n_refused=len(response.refused_sentences),
        )
        raise HTTPException(status_code=422, detail=response.model_dump(by_alias=True, mode="json"))
    if result.incomplete:
        log.info(
            "qa.partial",
            question=payload.question[:80],
            latency_ms=result.latency_ms,
            n_kept=len(response.sentences) - len(response.dropped_sentences),
            n_dropped=len(response.dropped_sentences),
        )
        return response
    log.info(
        "qa.answered",
        question=payload.question[:80],
        latency_ms=result.latency_ms,
        n_sentences=len(response.sentences),
    )
    return response

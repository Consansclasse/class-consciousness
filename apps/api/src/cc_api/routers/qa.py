# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /qa — pipeline RAG sourcé en exposition HTTP.

POST /qa retourne 200 si toutes les phrases sont SUPPORTED, sinon 422
avec `refused_reason` et la liste des phrases problématiques. Aucune réponse
non sourcée ne sort jamais — règle d'or non-négociable.

Rate limit : 10 req/min par IP via slowapi.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any, cast

from anthropic import APIError
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from cc_api.clients.anthropic import AnthropicError, get_anthropic_client
from cc_api.clients.db import get_session_maker
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
            text=v.text,
            citations=v.citations,
            verdict=v.verdict.value,
            verified=v.verified,
            paragraphe=v.paragraphe,
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
        async with get_session_maker()() as session:
            result = await answer_question(
                payload.question,
                qdrant=qdrant,
                embed=embed,
                reranker=reranker,
                anthropic=anthropic,
                session=session,
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
    except (APIError, AnthropicError) as exc:
        # Erreur côté Anthropic — panne/quota/crédits, OU sortie structurée
        # inexploitable (génération ou juge) : 503 propre, jamais de réponse
        # non vérifiée exposée.
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


def _sse(event: str, data: dict[str, Any]) -> str:
    """Sérialise un évènement Server-Sent Events."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/stream")
@limiter.limit("10/minute")
async def post_qa_stream(request: Request, payload: QaRequest) -> StreamingResponse:
    """Pipeline RAG en Server-Sent Events.

    Le pipeline prend des dizaines de secondes (3 appels LLM + reranking). Un
    `/qa` synchrone serait coupé par le proxy. Ici on émet, au fil de l'eau :
    - `event: stage`  — progression (« Rédaction de la dissertation… ») ;
    - des commentaires `: ping` toutes les 10 s — garde la connexion vivante ;
    - `event: result` — la `QaResponse` finale (vérifiée) ;
    - `event: error`  — message d'erreur lisible.

    Aucune phrase non vérifiée n'est jamais streamée : seule la réponse finale,
    déjà passée par la vérification d'ancrage, est envoyée — la règle d'or tient.
    """

    async def event_stream() -> AsyncIterator[str]:
        queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()

        async def on_stage(label: str) -> None:
            await queue.put(("stage", label))

        async def run() -> None:
            try:
                async with get_session_maker()() as session:
                    result = await answer_question(
                        payload.question,
                        qdrant=get_qdrant(),
                        embed=get_embed_client(),
                        reranker=get_rerank_client(),
                        anthropic=get_anthropic_client(),
                        session=session,
                        on_stage=on_stage,
                    )
                await queue.put(("result", result))
            except EmbedServerError as exc:
                log.warning("qa.stream_embed_unavailable", error=str(exc))
                await queue.put((
                    "error",
                    "Le service d'embedding est momentanément indisponible.",
                ))
            except (APIError, AnthropicError) as exc:
                log.warning("qa.stream_llm_unavailable", error=str(exc))
                await queue.put((
                    "error",
                    "Le service de génération est momentanément indisponible.",
                ))
            except Exception as exc:  # garde-fou : jamais de 500 nu dans le flux
                log.warning("qa.stream_error", error=str(exc))
                await queue.put(("error", "Une erreur interne est survenue."))
            finally:
                await queue.put(("__done__", None))

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(10)
                await queue.put(("ping", None))

        run_task = asyncio.create_task(run())
        hb_task = asyncio.create_task(heartbeat())
        try:
            while True:
                kind, value = await queue.get()
                if kind == "__done__":
                    break
                if kind == "ping":
                    yield ": ping\n\n"
                elif kind == "stage":
                    yield _sse("stage", {"label": value})
                elif kind == "result":
                    response = _build_response(value)
                    log.info(
                        "qa.stream_answered",
                        question=payload.question[:80],
                        refused=value.refused_reason,
                        incomplete=value.incomplete,
                    )
                    yield _sse("result", response.model_dump(by_alias=True, mode="json"))
                elif kind == "error":
                    yield _sse("error", {"detail": value})
        finally:
            hb_task.cancel()
            await run_task

    return StreamingResponse(event_stream(), media_type="text/event-stream")

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /qa — pipeline RAG sourcé en exposition HTTP.

POST /qa retourne 200 si toutes les phrases sont SUPPORTED, sinon 422
avec `refused_reason` et la liste des phrases problématiques. Aucune réponse
non sourcée ne sort jamais — règle d'or non-négociable.

Rate limit : 10 req/min par IP via slowapi.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, cast

from anthropic import APIError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select

from cc_api.clients.anthropic import AnthropicError, GenerationUsage, get_anthropic_client
from cc_api.clients.db import get_session_maker
from cc_api.clients.embed import EmbedServerError, get_embed_client, get_rerank_client
from cc_api.clients.qdrant import get_qdrant
from cc_api.clients.stripe import get_stripe_client
from cc_api.core.deps import current_user
from cc_api.core.logging import get_logger
from cc_api.core.metrics import (
    rag_billing_errors_total,
    rag_requests_total,
    record_rag_result,
)
from cc_api.core.ratelimit import limiter
from cc_api.core.settings import settings
from cc_api.models.rag_feedback import RagFeedback
from cc_api.models.rag_interaction import RagInteraction
from cc_api.models.user import User
from cc_api.schemas.qa import Citation, FeedbackRequest, QaRequest, QaResponse, Sentence
from cc_api.services import conversation as conv_service
from cc_api.services.abonnement import get_active_abonnement, record_token_usage
from cc_api.services.quota import consume_quota, peek_quota
from cc_api.services.rag import RagResult, answer_question

router = APIRouter(prefix="/qa", tags=["qa"])
log = get_logger(__name__)


def _cited_chunks(result: RagResult) -> list[Citation]:
    """Appareil de sources d'une réponse — un Citation par chunk reranké.

    Construit une seule fois, partagé entre la réponse HTTP et la ligne
    `rag_interactions` (où il est persité pour réafficher l'historique).
    """
    return [
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


def _build_response(
    result: RagResult,
    interaction_id: int | None,
    conversation_id: int | None,
    cited_chunks: list[Citation],
) -> QaResponse:
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
        interaction_id=interaction_id,
        conversation_id=conversation_id,
    )


def _ip_hash(request: Request) -> str | None:
    """HMAC-SHA-256 (clé = `session_secret`) de l'IP cliente.

    Un hash non réversible sans la clé serveur : un dump de la table ne permet
    pas de retrouver les IP par force brute (espace IPv4 = 4 milliards, trivial
    sans clé ; HMAC le ferme). Stable d'une requête à l'autre tant que le
    secret ne tourne pas — utile pour observer un même visiteur sans jamais
    stocker son IP en clair.
    """
    client = request.client
    if client is None:
        return None
    return hmac.new(
        settings.session_secret.encode("utf-8"),
        client.host.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _build_interaction(
    result: RagResult,
    request: Request,
    user_id: int,
    conversation_id: int,
    cited_chunks: list[Citation],
) -> RagInteraction:
    """Sérialise un RagResult en ligne `rag_interactions` persistable.

    `user_id` et `conversation_id` proviennent de la résolution faite par
    l'appelant (compte connecté + fil). `usage` détaille génération et juge
    séparément, modèle compris : leurs tarifs diffèrent. `cited_chunks` persiste
    l'appareil de sources complet pour réafficher l'historique à l'identique.
    """
    judge_usage = (
        result.citation_report.judge_usage
        if result.citation_report is not None
        else GenerationUsage.zero()
    )
    return RagInteraction(
        user_id=user_id,
        conversation_id=conversation_id,
        ip_hash=_ip_hash(request),
        question=result.question,
        answer=result.answer,
        incomplete=result.incomplete,
        refused_reason=result.refused_reason,
        model=result.model,
        latency_ms=result.latency_ms,
        latencies=result.latencies,
        usage={
            "generation": {**asdict(result.generation_usage), "model": result.model},
            "judge": {**asdict(judge_usage), "model": settings.anthropic_judge_model},
        },
        sentences=[
            {
                "text": v.text,
                "verdict": v.verdict.value,
                "verified": v.verified,
                "citations": v.citations,
                "paragraphe": v.paragraphe,
                "best_score": v.best_score,
                "reason": v.reason,
            }
            for v in result.sentences
        ],
        cited_source_ids=sorted(
            {c for v in result.sentences for c in v.citations if c not in ("", "none")}
        ),
        cited_chunks=[c.model_dump(mode="json") for c in cited_chunks],
        retrieval_count=len(result.retrieved),
        rerank_count=len(result.reranked),
    )


# Plafond strict d'attente sur l'écriture de l'interaction — au-delà, on
# abandonne (best-effort) plutôt que de bloquer la réponse déjà calculée.
_PERSIST_TIMEOUT_S = 5


async def _persist_interaction(
    result: RagResult,
    request: Request,
    user_id: int,
    conversation_id_in: int | None,
    cited_chunks: list[Citation],
) -> tuple[int | None, int | None]:
    """Enregistre l'interaction dans son fil et renvoie `(interaction_id,
    conversation_id)` — `(None, None)` si l'écriture échoue/dépasse le timeout.

    Résout le fil : celui fourni (s'il appartient à l'utilisateur), sinon un fil
    neuf titré d'après la question. Tout est sous timeout : `record_rag_result`
    (Prometheus in-memory mais sait lever) comme la session DB. Best-effort —
    une panne DB ne doit jamais faire échouer la réponse déjà calculée.

    Purge de rétention : seules les interactions SANS fil (`conversation_id IS
    NULL` — lignes héritées/anonymes) sont effacées au-delà de la fenêtre.
    L'historique rattaché à un compte est permanent.
    """
    try:
        async with asyncio.timeout(_PERSIST_TIMEOUT_S):
            async with get_session_maker()() as session:
                record_rag_result(result)
                conv = await conv_service.resolve_for_message(
                    session, user_id, conversation_id_in, result.question
                )
                interaction = _build_interaction(
                    result, request, user_id, conv.id, cited_chunks
                )
                session.add(interaction)
                await conv_service.touch(session, conv.id)
                cutoff = datetime.now(UTC) - timedelta(
                    days=settings.rag_interaction_retention_days
                )
                await session.execute(
                    delete(RagInteraction).where(
                        RagInteraction.conversation_id.is_(None),
                        RagInteraction.created_at < cutoff,
                    )
                )
                await session.commit()
                return interaction.id, conv.id
    except Exception as exc:
        log.warning(
            "qa.persist_failed", error=str(exc), error_type=type(exc).__name__
        )
        return None, None


# Refus survenus AVANT l'appel au LLM de génération — quasi gratuits : ils ne
# consomment pas le quota. Tout le reste (réponse, ou refus post-génération) a
# coûté un appel LLM et consomme une unité.
_PRE_GENERATION_REFUSALS = {"no_chunks_retrieved", "no_relevant_chunks"}


async def enforce_rag_quota(request: Request) -> User:
    """Dépendance : exige un compte (401 sinon) et arbitre gratuit / pay-as-you-go.

    L'assistant n'est plus accessible anonymement : poser une question impose un
    compte. La lecture du corpus, elle, reste libre (cette dépendance n'est posée
    que sur /qa). Le quota n'est PAS consommé ici : le handler appelle
    `consume_quota` après une génération réussie — un refus amont ou une panne ne
    coûte rien.

    Modèle pay-as-you-go pur :
    - dans le quota gratuit (`rag_free_quota_per_window`) → requête gratuite ;
    - au-delà → autorisée si un abonnement PAYG est actif (sinon 402), chaque
      requête étant refacturée à l'usage ;
    - un plafond de sécurité anti-runaway (`rag_payg_daily_cap`, 0 = désactivé)
      borne malgré tout le nombre de requêtes facturables par fenêtre → 402.

    `request.state.rag_billable` signale au handler s'il doit émettre un
    meter_event après la génération.
    """
    user = await current_user(request)
    identity = f"user:{user.id}"
    state = await peek_quota(identity, limit=settings.rag_free_quota_per_window)
    if state.allowed:
        request.state.rag_billable = False
        return user

    # Quota gratuit épuisé : l'accès continue en pay-as-you-go pour un abonné actif.
    async with get_session_maker()() as session:
        abonnement = await get_active_abonnement(session, user.id)
    if abonnement is None:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "quota_exceeded",
                "limit": state.limit,
                "retryAfterS": state.retry_after_s,
                "message": (
                    "Quota gratuit de l'assistant atteint. La lecture du corpus "
                    "reste libre ; activez le paiement à l'usage pour continuer."
                ),
            },
        )
    # Garde-fou anti-runaway : borne la facture même pour un abonné.
    cap = settings.rag_payg_daily_cap
    if cap > 0:
        cap_state = await peek_quota(identity, limit=cap)
        if not cap_state.allowed:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "payg_daily_cap",
                    "limit": cap_state.limit,
                    "retryAfterS": cap_state.retry_after_s,
                    "message": (
                        "Plafond de sécurité de l'assistant atteint pour la "
                        "période. Réessayez plus tard ou contactez-nous."
                    ),
                },
            )
    request.state.rag_billable = True
    return user


async def _record_usage(
    request: Request, user_id: int, result: RagResult, interaction_id: int | None
) -> None:
    """Refacture l'usage LLM de la requête si elle est en pay-as-you-go.

    Best-effort, comme la persistance : une panne de facturation ne casse jamais
    une réponse déjà calculée. No-op si la requête est couverte par le quota
    gratuit (`request.state.rag_billable` faux) ou si la persistance a échoué
    (pas d'identifiant stable pour l'idempotence Stripe).
    """
    if not getattr(request.state, "rag_billable", False):
        return
    if interaction_id is None:  # persistance échouée → pas d'identifiant stable
        return
    tokens = result.total_usage.billable_tokens
    try:
        async with get_session_maker()() as session:
            await record_token_usage(
                session,
                user_id=user_id,
                tokens=tokens,
                identifier=f"qa-{interaction_id}",
                stripe_client=get_stripe_client(),
            )
    except Exception as exc:
        log.warning(
            "qa.billing_failed",
            error=str(exc),
            error_type=type(exc).__name__,
            tokens=tokens,
        )
        rag_billing_errors_total.inc()


@router.post("", response_model=QaResponse, responses={422: {"model": QaResponse}})
@limiter.limit("10/minute")
async def post_qa(
    request: Request,
    payload: QaRequest,
    user: Annotated[User, Depends(enforce_rag_quota)],
) -> QaResponse:
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
        rag_requests_total.labels(outcome="error").inc()
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
        rag_requests_total.labels(outcome="error").inc()
        log.warning("qa.llm_unavailable", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail=(
                "Le service de génération est momentanément indisponible. "
                "Réessaie dans un instant."
            ),
        ) from exc
    if result.refused_reason not in _PRE_GENERATION_REFUSALS:
        await consume_quota(f"user:{user.id}")
    cited = _cited_chunks(result)
    interaction_id, conversation_id = await _persist_interaction(
        result, request, user.id, payload.conversation_id, cited
    )
    await _record_usage(request, user.id, result, interaction_id)
    response = _build_response(result, interaction_id, conversation_id, cited)
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
async def post_qa_stream(
    request: Request,
    payload: QaRequest,
    user: Annotated[User, Depends(enforce_rag_quota)],
) -> StreamingResponse:
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
                if result.refused_reason not in _PRE_GENERATION_REFUSALS:
                    await consume_quota(f"user:{user.id}")
                cited = _cited_chunks(result)
                interaction_id, conversation_id = await _persist_interaction(
                    result, request, user.id, payload.conversation_id, cited
                )
                await _record_usage(request, user.id, result, interaction_id)
                await queue.put(("result", (result, interaction_id, conversation_id, cited)))
            except EmbedServerError as exc:
                rag_requests_total.labels(outcome="error").inc()
                log.warning("qa.stream_embed_unavailable", error=str(exc))
                await queue.put((
                    "error",
                    "Le service d'embedding est momentanément indisponible.",
                ))
            except (APIError, AnthropicError) as exc:
                rag_requests_total.labels(outcome="error").inc()
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
                    rag_result, interaction_id, conversation_id, cited = value
                    response = _build_response(
                        rag_result, interaction_id, conversation_id, cited
                    )
                    log.info(
                        "qa.stream_answered",
                        question=payload.question[:80],
                        refused=rag_result.refused_reason,
                        incomplete=rag_result.incomplete,
                    )
                    yield _sse("result", response.model_dump(by_alias=True, mode="json"))
                elif kind == "error":
                    yield _sse("error", {"detail": value})
        finally:
            hb_task.cancel()
            await run_task

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/interactions/{interaction_id}/feedback", status_code=201)
@limiter.limit("20/minute")
async def post_feedback(
    request: Request,
    interaction_id: int,
    payload: FeedbackRequest,
    user: Annotated[User, Depends(current_user)],
) -> dict[str, str]:
    """Enregistre le retour d'un lecteur (pouce ou signalement) sur une réponse.

    Ferme la boucle humaine du closed-loop. Exige un compte ; 404 si
    l'interaction est inconnue OU n'appartient pas à l'utilisateur — on ne
    révèle pas les interactions d'autrui. Le paramètre `request` est requis par
    slowapi (extraction de l'IP).
    """
    async with get_session_maker()() as session:
        owner_id = await session.scalar(
            select(RagInteraction.user_id).where(RagInteraction.id == interaction_id)
        )
        if owner_id is None or owner_id != user.id:
            raise HTTPException(status_code=404, detail="interaction introuvable")
        session.add(
            RagFeedback(
                rag_interaction_id=interaction_id,
                kind=payload.kind,
                comment=payload.comment,
                ip_hash=_ip_hash(request),
            )
        )
        await session.commit()
    log.info("qa.feedback", interaction_id=interaction_id, kind=payload.kind.value)
    return {"status": "recorded"}

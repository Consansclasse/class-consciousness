# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /adhesions — création de Checkout Stripe + réception webhook.

Trois endpoints :

- POST /adhesions/checkout : crée l'intent + Stripe Session → renvoie URL.
- POST /adhesions/webhook/stripe : reçoit les events Stripe (signature vérifiée).
- GET /adhesions/intent/{intent_id} : état d'une intention (consommé par
  /adherer/merci pour afficher confirmation).

Pas d'auth sur /checkout : un visiteur anonyme peut adhérer. L'authentification
nominative se fait plus tard via magic-link (table `auth_tokens`).
"""

from __future__ import annotations

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.clients.db import get_session_maker
from cc_api.clients.stripe import get_stripe_client
from cc_api.core.logging import get_logger
from cc_api.core.ratelimit import limiter
from cc_api.models.adhesion_intent import AdhesionIntent
from cc_api.schemas.adhesion import (
    AdhesionCheckoutIn,
    AdhesionCheckoutOut,
    AdhesionIntentStatusOut,
)
from cc_api.services.adhesion import AdhesionError, create_checkout, handle_stripe_event

router = APIRouter(prefix="/adhesions", tags=["adhesions"])
log = get_logger(__name__)


async def _session() -> AsyncSession:
    return get_session_maker()()


@router.post(
    "/checkout",
    response_model=AdhesionCheckoutOut,
    status_code=201,
    responses={
        422: {"description": "Données invalides ou consentement manquant"},
        429: {"description": "Trop de créations de session — rate limit"},
        502: {"description": "Stripe a refusé la création de la session"},
    },
)
@limiter.limit("20/minute")
async def post_checkout(
    request: Request, payload: AdhesionCheckoutIn
) -> AdhesionCheckoutOut:
    """Crée une intention d'adhésion + Stripe Checkout Session.

    Endpoint anonyme : chaque appel insère un User/AdhesionIntent et crée une
    Checkout Session Stripe réelle. Le rate limit (20/min par IP) borne le spam
    de sessions Stripe et la pollution des tables. `request` est requis par
    slowapi pour extraire l'IP du client.
    """
    stripe_client = get_stripe_client()
    async with await _session() as session:
        try:
            intent = await create_checkout(
                session, payload=payload, stripe_client=stripe_client
            )
        except AdhesionError as exc:
            log.warning("adhesions.checkout.error", error=str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AdhesionCheckoutOut(
        public_token=intent.public_token,
        redirect_url=intent.stripe_redirect_url,
        expires_at=intent.expires_at,
    )


@router.post(
    "/webhook/stripe",
    status_code=200,
    responses={
        400: {"description": "Signature Stripe invalide ou payload illisible"},
        503: {"description": "Webhook Stripe non configuré côté serveur"},
    },
)
async def post_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(default="", alias="Stripe-Signature"),
) -> dict[str, str]:
    """Reçoit les events Stripe — signature obligatoire.

    Renvoie toujours 200 si la signature est valide, même si l'event n'est
    pas géré (Stripe ré-essaie sinon, ce qu'on ne veut pas pour les types
    qu'on ignore volontairement comme `customer.created`).
    """
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="header Stripe-Signature manquant")

    payload = await request.body()
    try:
        stripe_client = get_stripe_client()
        event = stripe_client.construct_event(payload, stripe_signature)
    except (stripe.SignatureVerificationError, ValueError) as exc:
        log.warning("adhesions.webhook.invalid_signature", error=str(exc))
        raise HTTPException(status_code=400, detail="signature invalide") from exc
    except RuntimeError as exc:
        # Clés Stripe absentes du déploiement → impossible de vérifier la
        # signature. Faute de configuration serveur, pas du client : 503
        # explicite et journalisé plutôt qu'un 500 nu.
        log.error("adhesions.webhook.stripe_unconfigured", error=str(exc))
        raise HTTPException(
            status_code=503, detail="webhook Stripe non configuré"
        ) from exc

    async with await _session() as session:
        intent = await handle_stripe_event(session, event=event)

    return {
        "received": "true",
        "event_id": event.id,
        "intent_id": str(intent.id) if intent else "",
    }


@router.get("/intent/{token}", response_model=AdhesionIntentStatusOut)
async def get_intent(token: str) -> AdhesionIntentStatusOut:
    """État d'une intention — utilisé par /adherer/merci pour confirmation.

    Pas d'auth, mais indexé par un jeton opaque non devinable (192 bits) et non
    par l'id séquentiel : sans cela l'endpoint serait énumérable et exposerait
    tout le registre des adhésions (statuts, montants, dates). Le jeton n'est
    connu que de l'adhérent, transmis dans l'URL de retour Stripe.
    """
    async with await _session() as session:
        result = await session.execute(
            select(AdhesionIntent).where(AdhesionIntent.public_token == token)
        )
        intent = result.scalar_one_or_none()
    if intent is None:
        raise HTTPException(status_code=404, detail="intent inconnu")
    return AdhesionIntentStatusOut(
        public_token=intent.public_token,
        status=intent.status,
        tier=intent.tier,
        amount_eur_cents=intent.amount_eur_cents,
        paid_at=intent.paid_at,
    )

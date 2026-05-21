# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /abonnements — réception des webhooks Stripe Billing.

Pour l'instant un seul endpoint : le webhook de cycle de vie des abonnements.
Les endpoints utilisateur (checkout, portail de gestion, statut) seront ajoutés
avec l'intégration de l'authentification — ils requièrent un utilisateur
identifié, ce que le projet n'expose pas encore.
"""

from __future__ import annotations

from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request

from cc_api.clients.db import get_session_maker
from cc_api.clients.stripe import get_stripe_client
from cc_api.core.deps import current_user
from cc_api.core.logging import get_logger
from cc_api.core.ratelimit import limiter
from cc_api.core.settings import settings
from cc_api.models.user import User
from cc_api.schemas.abonnement import (
    AbonnementCheckoutOut,
    AbonnementPortalOut,
    AbonnementStatusOut,
)
from cc_api.services.abonnement import (
    AbonnementError,
    create_subscription_checkout,
    get_active_abonnement,
    get_latest_abonnement,
    handle_stripe_event,
)

router = APIRouter(prefix="/abonnements", tags=["abonnements"])
log = get_logger(__name__)


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
    """Reçoit les events `customer.subscription.*` — signature obligatoire.

    Renvoie toujours 200 si la signature est valide, même si l'event est d'un
    type non géré : sans cela Stripe ré-essaierait indéfiniment les types
    qu'on ignore volontairement.
    """
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="header Stripe-Signature manquant")

    payload = await request.body()
    try:
        event = get_stripe_client().construct_event(payload, stripe_signature)
    except (stripe.SignatureVerificationError, ValueError) as exc:
        log.warning("abonnements.webhook.invalid_signature", error=str(exc))
        raise HTTPException(status_code=400, detail="signature invalide") from exc
    except RuntimeError as exc:
        log.error("abonnements.webhook.stripe_unconfigured", error=str(exc))
        raise HTTPException(
            status_code=503, detail="webhook Stripe non configuré"
        ) from exc

    try:
        async with get_session_maker()() as session:
            abonnement_id = await handle_stripe_event(session, event=event)
    except AbonnementError as exc:
        # Webhook inexploitable (ex. user_id absent) → 422 : Stripe ré-essaiera
        # et l'échec reste visible dans le dashboard Stripe.
        log.error("abonnements.webhook.unprocessable", error=str(exc))
        raise HTTPException(status_code=422, detail="webhook inexploitable") from exc

    return {
        "received": "true",
        "event_id": event.id,
        "abonnement_id": str(abonnement_id) if abonnement_id else "",
    }


@router.post("/checkout", response_model=AbonnementCheckoutOut)
@limiter.limit("10/minute")
async def checkout(
    request: Request, user: Annotated[User, Depends(current_user)]
) -> AbonnementCheckoutOut:
    """Ouvre un Stripe Checkout d'abonnement pour l'utilisateur connecté."""
    try:
        url = await create_subscription_checkout(
            user=user, stripe_client=get_stripe_client()
        )
    except (AbonnementError, RuntimeError, stripe.StripeError) as exc:
        # Stripe non configuré (clé/price absents) ou en échec : service
        # d'abonnement indisponible — un 503, pas une erreur serveur nue.
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return AbonnementCheckoutOut(redirect_url=url)


@router.post("/portal", response_model=AbonnementPortalOut)
@limiter.limit("10/minute")
async def portal(
    request: Request, user: Annotated[User, Depends(current_user)]
) -> AbonnementPortalOut:
    """Ouvre le Customer Portal Stripe — résiliation, moyen de paiement."""
    async with get_session_maker()() as session:
        abonnement = await get_active_abonnement(session, user.id)
    if abonnement is None:
        raise HTTPException(status_code=404, detail="aucun abonnement actif")
    url = await get_stripe_client().create_billing_portal_session(
        customer_id=abonnement.stripe_customer_id,
        return_url=f"{settings.public_web_base}/compte",
    )
    return AbonnementPortalOut(portal_url=url)


@router.get("/me", response_model=AbonnementStatusOut)
async def me(
    request: Request, user: Annotated[User, Depends(current_user)]
) -> AbonnementStatusOut:
    """État de l'abonnement de l'utilisateur connecté."""
    async with get_session_maker()() as session:
        latest = await get_latest_abonnement(session, user.id)
        active = await get_active_abonnement(session, user.id)
    return AbonnementStatusOut(
        active=active is not None,
        status=latest.status.value if latest else None,
        current_period_end=latest.current_period_end if latest else None,
        cancel_at_period_end=latest.cancel_at_period_end if latest else False,
    )

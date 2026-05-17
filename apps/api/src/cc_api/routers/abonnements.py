# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /abonnements — réception des webhooks Stripe Billing.

Pour l'instant un seul endpoint : le webhook de cycle de vie des abonnements.
Les endpoints utilisateur (checkout, portail de gestion, statut) seront ajoutés
avec l'intégration de l'authentification — ils requièrent un utilisateur
identifié, ce que le projet n'expose pas encore.
"""

from __future__ import annotations

import stripe
from fastapi import APIRouter, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.clients.db import get_session_maker
from cc_api.clients.stripe import get_stripe_client
from cc_api.core.logging import get_logger
from cc_api.services.abonnement import handle_stripe_event

router = APIRouter(prefix="/abonnements", tags=["abonnements"])
log = get_logger(__name__)


async def _session() -> AsyncSession:
    return get_session_maker()()


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

    async with await _session() as session:
        abonnement = await handle_stripe_event(session, event=event)

    return {
        "received": "true",
        "event_id": event.id,
        "abonnement_id": str(abonnement.id) if abonnement else "",
    }

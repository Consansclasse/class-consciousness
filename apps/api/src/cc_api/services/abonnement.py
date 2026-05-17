# SPDX-License-Identifier: AGPL-3.0-or-later
"""Service abonnement — synchronise les `Abonnement` avec Stripe Billing.

`handle_stripe_event` est appelée par le router /abonnements/webhook après
vérification de signature. Idempotente : un event Stripe peut être rejoué n
fois ; l'upsert par `stripe_subscription_id` (colonne UNIQUE) garantit une
seule ligne.

Elle traite le cycle de vie d'une Subscription Stripe :
`customer.subscription.created` / `.updated` / `.deleted`. Chaque event porte
l'objet Subscription complet — on en lit le statut, la fin de période, le prix
et le `user_id` (rattaché via `subscription_data.metadata` au checkout).

Accès aux champs Stripe : par attribut (`getattr`) ou indexation. Le
`StripeObject` n'est pas un `dict` et n'expose pas `.get()`.

Pas de mock Stripe : les tests signent les events à la main (stripe-mock ne
génère pas de webhooks — c'est par design).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.core.logging import get_logger
from cc_api.models.abonnement import Abonnement, AbonnementStatus

log = get_logger(__name__)

_HANDLED_EVENTS = {
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
}

# Statuts Stripe Subscription → enum interne. `incomplete_expired` et `paused`
# n'ouvrent pas l'accès : repliés sur CANCELED / PAST_DUE.
_STATUS_MAP: dict[str, AbonnementStatus] = {
    "active": AbonnementStatus.ACTIVE,
    "trialing": AbonnementStatus.TRIALING,
    "past_due": AbonnementStatus.PAST_DUE,
    "canceled": AbonnementStatus.CANCELED,
    "incomplete": AbonnementStatus.INCOMPLETE,
    "incomplete_expired": AbonnementStatus.CANCELED,
    "unpaid": AbonnementStatus.UNPAID,
    "paused": AbonnementStatus.PAST_DUE,
}


def _epoch_to_dt(value: Any) -> datetime | None:
    """Convertit un timestamp epoch Stripe en datetime UTC (None si absent)."""
    return datetime.fromtimestamp(int(value), tz=UTC) if value else None


def _extract_user_id(sub: Any) -> int | None:
    """Lit `metadata.user_id` posé sur la Subscription au moment du checkout."""
    metadata = getattr(sub, "metadata", None)
    raw = getattr(metadata, "user_id", None) if metadata is not None else None
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _extract_price_id(sub: Any) -> str | None:
    """Lit le premier price de la Subscription (un seul item attendu)."""
    try:
        data = sub["items"]["data"]
        return str(data[0]["price"]["id"])
    except (KeyError, TypeError, IndexError):
        return None


async def handle_stripe_event(
    session: AsyncSession, *, event: stripe.Event
) -> Abonnement | None:
    """Traite un event d'abonnement Stripe — idempotent.

    Renvoie l'`Abonnement` créé ou mis à jour, ou None si l'event n'est pas un
    type géré, si le payload est inexploitable, ou si aucun utilisateur n'y est
    rattaché.
    """
    event_type = event["type"]
    if event_type not in _HANDLED_EVENTS:
        log.info("abonnement.webhook.ignored", event_type=event_type, event_id=event.id)
        return None

    sub: Any = event["data"]["object"]
    sub_id = getattr(sub, "id", None)
    if not sub_id:
        log.warning("abonnement.webhook.missing_subscription_id", event_id=event.id)
        return None

    status = _STATUS_MAP.get(getattr(sub, "status", None) or "")
    if status is None:
        log.warning(
            "abonnement.webhook.unknown_status",
            stripe_status=getattr(sub, "status", None),
            event_id=event.id,
        )
        return None

    current_period_end = _epoch_to_dt(getattr(sub, "current_period_end", None))
    cancel_at_period_end = bool(getattr(sub, "cancel_at_period_end", False))
    price_id = _extract_price_id(sub)
    canceled_at = _epoch_to_dt(getattr(sub, "canceled_at", None))

    result = await session.execute(
        select(Abonnement).where(Abonnement.stripe_subscription_id == sub_id)
    )
    abonnement = result.scalar_one_or_none()

    if abonnement is None:
        user_id = _extract_user_id(sub)
        if user_id is None:
            log.error(
                "abonnement.webhook.no_user_id", subscription_id=sub_id, event_id=event.id
            )
            return None
        if current_period_end is None or price_id is None:
            log.error(
                "abonnement.webhook.incomplete_payload",
                subscription_id=sub_id,
                event_id=event.id,
            )
            return None
        abonnement = Abonnement(
            user_id=user_id,
            stripe_customer_id=str(getattr(sub, "customer", None) or ""),
            stripe_subscription_id=sub_id,
            stripe_price_id=price_id,
            status=status,
            current_period_end=current_period_end,
            cancel_at_period_end=cancel_at_period_end,
            canceled_at=canceled_at,
        )
        session.add(abonnement)
        await session.commit()
        log.info(
            "abonnement.created",
            subscription_id=sub_id,
            user_id=user_id,
            status=status.value,
        )
        return abonnement

    abonnement.status = status
    if current_period_end is not None:
        abonnement.current_period_end = current_period_end
    abonnement.cancel_at_period_end = cancel_at_period_end
    if price_id is not None:
        abonnement.stripe_price_id = price_id
    abonnement.canceled_at = canceled_at
    await session.commit()
    log.info("abonnement.updated", subscription_id=sub_id, status=status.value)
    return abonnement

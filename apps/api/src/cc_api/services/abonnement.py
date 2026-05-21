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
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.clients.stripe import StripeClient
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.models.abonnement import Abonnement, AbonnementStatus
from cc_api.models.user import User

log = get_logger(__name__)


class AbonnementError(Exception):
    """Erreur métier d'abonnement — p. ex. abonnement non configuré côté Stripe."""


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
    """Convertit un timestamp epoch Stripe en datetime UTC ; None si absent ou
    illisible — donnée externe, on ne fait jamais confiance au format reçu."""
    try:
        return datetime.fromtimestamp(int(value), tz=UTC) if value else None
    except (TypeError, ValueError):
        return None


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
) -> int | None:
    """Traite un event d'abonnement Stripe — idempotent et résistant au désordre.

    L'upsert `INSERT … ON CONFLICT … DO UPDATE … WHERE` est atomique : il crée
    la ligne si absente, ne la met à jour que si l'event est au moins aussi
    récent que le dernier appliqué (Stripe ne garantit pas l'ordre de
    livraison), et ne fait rien sinon — deux livraisons concurrentes du même
    event ne créent jamais de doublon. Renvoie l'id de l'`Abonnement`, ou None
    (event non géré, statut inconnu, ou event plus ancien ignoré).

    Lève `AbonnementError` si l'event est inexploitable (`user_id`, `price` ou
    période absents) — anormal : on force le retry Stripe plutôt que d'encaisser
    un paiement sans rattacher de compte.
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

    user_id = _extract_user_id(sub)
    price_id = _extract_price_id(sub)
    current_period_end = _epoch_to_dt(getattr(sub, "current_period_end", None))
    if user_id is None or price_id is None or current_period_end is None:
        # Anormal : notre checkout pose toujours metadata.user_id + le price.
        # On lève pour forcer le retry Stripe — un paiement sans compte
        # rattaché ne doit jamais se perdre en silence.
        log.error(
            "abonnement.webhook.unusable_payload",
            subscription_id=sub_id,
            event_id=event.id,
            has_user_id=user_id is not None,
            has_price=price_id is not None,
            has_period=current_period_end is not None,
        )
        raise AbonnementError(f"webhook abonnement inexploitable ({sub_id})")

    event_created = _epoch_to_dt(getattr(event, "created", None)) or datetime.now(UTC)
    values: dict[str, Any] = {
        "user_id": user_id,
        "stripe_customer_id": str(getattr(sub, "customer", None) or ""),
        "stripe_subscription_id": sub_id,
        "stripe_price_id": price_id,
        "status": status,
        "current_period_end": current_period_end,
        "cancel_at_period_end": bool(getattr(sub, "cancel_at_period_end", False)),
        "canceled_at": _epoch_to_dt(getattr(sub, "canceled_at", None)),
        "last_event_at": event_created,
    }
    stmt = (
        pg_insert(Abonnement)
        .values(**values)
        .on_conflict_do_update(
            index_elements=["stripe_subscription_id"],
            set_={
                k: values[k]
                for k in (
                    "status",
                    "stripe_price_id",
                    "current_period_end",
                    "cancel_at_period_end",
                    "canceled_at",
                    "last_event_at",
                )
            },
            where=or_(
                Abonnement.last_event_at.is_(None),
                Abonnement.last_event_at <= event_created,
            ),
        )
        .returning(Abonnement.id)
    )
    abonnement_id = (await session.execute(stmt)).scalar_one_or_none()
    await session.commit()

    if abonnement_id is None:
        log.info(
            "abonnement.webhook.out_of_order_ignored",
            subscription_id=sub_id,
            event_id=event.id,
        )
        return None
    log.info(
        "abonnement.webhook.applied",
        subscription_id=sub_id,
        status=status.value,
        abonnement_id=abonnement_id,
    )
    return abonnement_id


async def create_subscription_checkout(
    *, user: User, stripe_client: StripeClient
) -> str:
    """Ouvre une Checkout Session d'abonnement et renvoie l'URL de redirection.

    Le `user_id` est propagé en metadata jusqu'à la Subscription : le webhook
    `customer.subscription.created` le relit pour créer la ligne `Abonnement`.
    """
    if not settings.stripe_price_payg:
        raise AbonnementError(
            "pay-as-you-go non configuré (STRIPE_PRICE_PAYG absent)"
        )
    created = await stripe_client.create_subscription_checkout_session(
        email=user.email,
        price_id=settings.stripe_price_payg,
        success_url=f"{settings.public_web_base}/abonnement/merci",
        cancel_url=f"{settings.public_web_base}/abonnement",
        metadata={"user_id": str(user.id)},
    )
    log.info("abonnement.checkout.created", user_id=user.id, session_id=created.id)
    return created.url


async def get_active_abonnement(
    session: AsyncSession, user_id: int
) -> Abonnement | None:
    """Renvoie l'abonnement qui ouvre l'accès aujourd'hui : statut ACTIVE ou
    TRIALING et période courante non échue. None si aucun."""
    now = datetime.now(UTC)
    result = await session.execute(
        select(Abonnement)
        .where(
            Abonnement.user_id == user_id,
            Abonnement.status.in_(
                [AbonnementStatus.ACTIVE, AbonnementStatus.TRIALING]
            ),
            Abonnement.current_period_end >= now,
        )
        .order_by(Abonnement.current_period_end.desc())
    )
    return result.scalars().first()


async def get_latest_abonnement(
    session: AsyncSession, user_id: int
) -> Abonnement | None:
    """Renvoie le dernier abonnement connu de l'utilisateur, quel que soit son
    statut — pour afficher l'état courant (y compris PAST_DUE, CANCELED)."""
    result = await session.execute(
        select(Abonnement)
        .where(Abonnement.user_id == user_id)
        .order_by(Abonnement.created_at.desc())
    )
    return result.scalars().first()


async def record_token_usage(
    session: AsyncSession,
    *,
    user_id: int,
    tokens: int,
    identifier: str,
    stripe_client: StripeClient,
) -> bool:
    """Refacture `tokens` à l'usage sur le Billing Meter de l'utilisateur.

    Émet un `meter_event` rattaché au Customer de l'abonnement pay-as-you-go
    actif. No-op (renvoie False) si `tokens <= 0` ou si l'utilisateur n'a pas
    d'abonnement actif — cas d'une requête couverte par le quota gratuit, qui
    ne se facture pas. `identifier` (l'id d'interaction RAG) garantit
    l'idempotence côté Stripe.

    Peut lever (Stripe injoignable / non configuré) : l'appelant encapsule en
    best-effort — une panne de facturation ne doit jamais casser une réponse
    déjà calculée, l'incident est journalisé et compté.
    """
    if tokens <= 0:
        return False
    abonnement = await get_active_abonnement(session, user_id)
    if abonnement is None or not abonnement.stripe_customer_id:
        return False
    await stripe_client.record_meter_event(
        event_name=settings.stripe_meter_event_name,
        customer_id=abonnement.stripe_customer_id,
        value=tokens,
        identifier=identifier,
    )
    return True

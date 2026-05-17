# SPDX-License-Identifier: AGPL-3.0-or-later
"""Service adhésion — orchestre User, AdhesionIntent, Stripe Checkout, Membership.

Deux opérations principales :

1. `create_checkout` : reçoit les données du formulaire, garantit l'existence
   d'un User (upsert idempotent par email), persiste l'AdhesionIntent en
   PENDING, ouvre une Stripe Checkout Session, renvoie l'URL de redirection.

2. `handle_stripe_event` : appelée par le router /webhook après vérification
   de signature. Idempotent (un même event Stripe peut être rejoué). Sur
   `checkout.session.completed` → crée la Membership et passe l'intent à
   COMPLETED. Sur `async_payment_failed` ou `session.expired` → FAILED/EXPIRED.

Pas de mock Stripe ici : les tests utilisent stripe-mock containerisé.
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Any

import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.clients.stripe import StripeClient
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.models.adhesion_intent import AdhesionIntent, AdhesionIntentStatus
from cc_api.models.membership import Membership, MembershipSource, MembershipTier
from cc_api.models.user import User
from cc_api.schemas.adhesion import (
    TIER_DEFAULT_AMOUNTS_CENTS,
    TIER_LABELS,
    AdhesionCheckoutIn,
)

log = get_logger(__name__)


class AdhesionError(Exception):
    """Erreur métier d'adhésion — distincte des erreurs Stripe brutes."""


def _resolve_amount(payload: AdhesionCheckoutIn) -> int:
    """Détermine le montant en centimes — défaut par tier, override si MECENE.

    Si `solidaire=True` et tier=INDIVIDUAL : montant 0. C'est le tarif solidaire
    déclaratif (cf. modèle `Membership.solidaire`).

    Pour MECENE : l'override est autorisé (≥ 500 €). Sans override → 500 €.
    """
    if payload.solidaire and payload.tier == MembershipTier.INDIVIDUAL:
        return 0
    if payload.tier == MembershipTier.MECENE and payload.amount_eur_cents_override:
        return payload.amount_eur_cents_override
    return TIER_DEFAULT_AMOUNTS_CENTS[payload.tier]


async def _upsert_user(
    session: AsyncSession,
    *,
    email: str,
    display_name: str | None,
    consent_newsletter: bool,
) -> User:
    """Crée le User s'il n'existe pas (par email), met à jour consent_data_at + display_name."""
    now = datetime.now(UTC)
    result = await session.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            display_name=display_name,
            consent_data_at=now,
            consent_newsletter_at=now if consent_newsletter else None,
        )
        session.add(user)
        await session.flush()
        log.info("user.created", user_id=user.id, email=email)
        return user

    # User existant : rafraîchit consent_data_at, met à jour display_name si fourni,
    # bascule consent_newsletter si l'utilisateur change d'avis (opt-in/out).
    user.consent_data_at = now
    if display_name and not user.display_name:
        user.display_name = display_name
    if consent_newsletter and user.consent_newsletter_at is None:
        user.consent_newsletter_at = now
    await session.flush()
    return user


async def create_checkout(
    session: AsyncSession,
    *,
    payload: AdhesionCheckoutIn,
    stripe_client: StripeClient,
) -> AdhesionIntent:
    """Crée une intention d'adhésion + une Stripe Checkout Session.

    Cas tarif solidaire (montant = 0) : on ne crée PAS de session Stripe,
    on crée directement la Membership en source=ADMIN et l'intent passe
    COMPLETED tout de suite. Stripe refuse les paiements à 0 € de toute façon.
    """
    amount = _resolve_amount(payload)
    # Jeton public opaque — identifiant de l'intent dans les URLs de retour et
    # le lookup public, à la place de l'id séquentiel énumérable.
    public_token = secrets.token_urlsafe(24)

    user = await _upsert_user(
        session,
        email=payload.email,
        display_name=payload.display_name,
        consent_newsletter=payload.consent_newsletter,
    )

    # Court-circuit pour le tarif solidaire 0 € — pas de paiement, on crée la
    # Membership directement.
    if amount == 0:
        today = date.today()
        membership = Membership(
            user_id=user.id,
            tier=payload.tier,
            solidaire=True,
            valid_from=today,
            valid_until=today + timedelta(days=365),
            amount_eur_cents=0,
            source=MembershipSource.ADMIN,
            external_reference=f"solidaire:{user.email}",
        )
        session.add(membership)
        # On persiste quand même l'intent en COMPLETED pour la cohérence d'audit.
        intent = AdhesionIntent(
            user_id=user.id,
            email=payload.email,
            tier=payload.tier,
            amount_eur_cents=0,
            solidaire=True,
            public_token=public_token,
            stripe_session_id=f"solidaire_{user.id}_{int(datetime.now(UTC).timestamp())}",
            stripe_redirect_url=f"{settings.public_web_base}/adherer/merci?solidaire=1",
            status=AdhesionIntentStatus.COMPLETED,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            paid_at=datetime.now(UTC),
        )
        session.add(intent)
        await session.commit()
        log.info("adhesion.solidaire.created", user_id=user.id, intent_id=intent.id)
        return intent

    # Pré-créer l'intent SANS stripe_session_id pour récupérer son id avant
    # l'appel Stripe (le success_url contient `intent={intent.id}` côté retour).
    intent = AdhesionIntent(
        user_id=user.id,
        email=payload.email,
        tier=payload.tier,
        amount_eur_cents=amount,
        solidaire=payload.solidaire,
        public_token=public_token,
        # Placeholder unique avant l'appel Stripe — sera remplacé.
        stripe_session_id=f"pending_{user.id}_{int(datetime.now(UTC).timestamp() * 1000)}",
        stripe_redirect_url="",
        status=AdhesionIntentStatus.PENDING,
        # 24h : marge confortable avant qu'on ne marque EXPIRED par un job.
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    session.add(intent)
    await session.flush()

    success_url = (
        f"{settings.public_web_base}/adherer/merci"
        f"?intent={public_token}&session_id={{CHECKOUT_SESSION_ID}}"
    )
    cancel_url = (
        f"{settings.public_web_base}/adherer/erreur"
        f"?intent={public_token}&session_id={{CHECKOUT_SESSION_ID}}"
    )

    try:
        created = await stripe_client.create_checkout_session(
            email=payload.email,
            amount_eur_cents=amount,
            product_label=TIER_LABELS[payload.tier],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "intent_id": str(intent.id),
                "user_id": str(user.id),
                "tier": payload.tier.value,
                "solidaire": "true" if payload.solidaire else "false",
            },
        )
    except stripe.StripeError as exc:
        log.exception("stripe.checkout.failed", error=str(exc))
        await session.rollback()
        raise AdhesionError(f"Stripe a refusé la création de la session : {exc}") from exc

    intent.stripe_session_id = created.id
    intent.stripe_redirect_url = created.url
    intent.expires_at = datetime.fromtimestamp(created.expires_at, tz=UTC)
    await session.commit()
    log.info(
        "adhesion.intent.created",
        intent_id=intent.id,
        user_id=user.id,
        tier=payload.tier.value,
        amount_eur_cents=amount,
        stripe_session_id=created.id,
    )
    return intent


async def handle_stripe_event(
    session: AsyncSession,
    *,
    event: stripe.Event,
) -> AdhesionIntent | None:
    """Traite un événement Stripe — idempotent.

    Renvoie l'AdhesionIntent affecté, ou None si l'événement ne nous concerne
    pas (autre type qu'on supporte).

    Idempotence : si l'intent est déjà COMPLETED et qu'on reçoit à nouveau
    checkout.session.completed, on ne touche rien et on renvoie l'intent.
    """
    event_type = event["type"]
    data_object: Any = event["data"]["object"]

    if event_type not in {
        "checkout.session.completed",
        "checkout.session.expired",
        "checkout.session.async_payment_failed",
    }:
        log.info("stripe.webhook.ignored", event_type=event_type, event_id=event.id)
        return None

    # `data_object` est un `StripeObject` (stripe ≥ 15) : pas de `.get()`,
    # mais l'accès attribut renvoie le champ ou lève AttributeError absorbée
    # par `getattr(..., None)`.
    stripe_session_id = getattr(data_object, "id", None)
    if not stripe_session_id:
        log.warning("stripe.webhook.missing_session_id", event_id=event.id)
        return None

    # `with_for_update` : verrou de ligne le temps de la transaction. Stripe peut
    # livrer le même webhook deux fois quasi simultanément ; sans ce verrou, deux
    # exécutions liraient toutes deux `status=PENDING`, passeraient le contrôle
    # d'idempotence et créeraient CHACUNE une Membership (double adhésion pour un
    # seul paiement). Le verrou sérialise : la 2e attend, relit `COMPLETED`, sort.
    result = await session.execute(
        select(AdhesionIntent)
        .where(AdhesionIntent.stripe_session_id == stripe_session_id)
        .with_for_update()
    )
    intent = result.scalar_one_or_none()
    if intent is None:
        log.warning(
            "stripe.webhook.unknown_session",
            stripe_session_id=stripe_session_id,
            event_id=event.id,
        )
        return None

    # Idempotence : déjà finalisé, on ne retouche rien.
    if intent.status != AdhesionIntentStatus.PENDING:
        log.info(
            "stripe.webhook.already_processed",
            intent_id=intent.id,
            current_status=intent.status.value,
            event_id=event.id,
        )
        return intent

    intent.last_event_id = event.id

    if event_type == "checkout.session.completed":
        # Vérification supplémentaire : le paiement doit être validé côté
        # Stripe. `payment_status` = "paid" ou (en async) "no_payment_required".
        payment_status = getattr(data_object, "payment_status", None)
        if payment_status not in {"paid", "no_payment_required"}:
            log.warning(
                "stripe.webhook.completed_but_unpaid",
                intent_id=intent.id,
                payment_status=payment_status,
                event_id=event.id,
            )
            return intent

        now = datetime.now(UTC)
        intent.status = AdhesionIntentStatus.COMPLETED
        intent.paid_at = now

        if intent.user_id is None:
            log.error("stripe.webhook.completed_no_user", intent_id=intent.id)
            await session.commit()
            return intent

        today = now.date()
        membership = Membership(
            user_id=intent.user_id,
            tier=intent.tier,
            solidaire=intent.solidaire,
            valid_from=today,
            valid_until=today + timedelta(days=365),
            amount_eur_cents=intent.amount_eur_cents,
            source=MembershipSource.STRIPE,
            external_reference=intent.stripe_session_id,
        )
        session.add(membership)
        await session.commit()
        log.info(
            "adhesion.membership.created",
            user_id=intent.user_id,
            intent_id=intent.id,
            membership_tier=intent.tier.value,
            stripe_session_id=intent.stripe_session_id,
        )
        return intent

    if event_type == "checkout.session.expired":
        intent.status = AdhesionIntentStatus.EXPIRED
        await session.commit()
        log.info("adhesion.intent.expired", intent_id=intent.id)
        return intent

    if event_type == "checkout.session.async_payment_failed":
        intent.status = AdhesionIntentStatus.FAILED
        await session.commit()
        log.info("adhesion.intent.failed", intent_id=intent.id)
        return intent

    return intent

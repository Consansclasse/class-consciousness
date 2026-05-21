# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client Stripe — wrapper minimal au-dessus du SDK officiel.

Pourquoi un wrapper : isoler les appels SDK pour les tester (override de
`api_base` vers stripe-mock dans les tests d'intégration) et garder un point
unique pour la signature des webhooks.

Pas de fallback. Pas de retry custom. Le SDK Stripe gère déjà retries
idempotents et timeouts via `stripe.max_network_retries`.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import stripe

from cc_api.core.logging import get_logger
from cc_api.core.settings import settings

log = get_logger(__name__)


@dataclass(frozen=True)
class CheckoutSessionCreated:
    """Réponse minimale d'une création de Checkout Session."""

    id: str
    url: str
    expires_at: int  # epoch seconds


class StripeClient:
    """Client async pour Stripe — Checkout + webhooks.

    Le SDK Stripe Python a un mode `async` sur les ressources via `*_async`
    méthodes (ex: `stripe.checkout.Session.create_async`).
    """

    def __init__(
        self,
        api_key: str | None,
        webhook_secret: str | None,
        *,
        api_base: str | None = None,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "STRIPE_SECRET_KEY manquant : exporter la variable d'env "
                "ou la passer à StripeClient"
            )
        self.api_key: str = api_key
        self.webhook_secret: str | None = webhook_secret
        # Configuration SDK globale — Stripe SDK Python est par module.
        stripe.api_key = api_key
        stripe.max_network_retries = 2
        if api_base:
            stripe.api_base = api_base
            log.info("stripe.api_base.override", api_base=api_base)

    async def create_checkout_session(
        self,
        *,
        email: str,
        amount_eur_cents: int,
        product_label: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> CheckoutSessionCreated:
        """Crée une Checkout Session pour un paiement one-shot en EUR.

        Mode `payment` (pas `subscription`) : la cotisation est annuelle mais
        chaque renouvellement crée une nouvelle adhésion explicite. Le
        consentement RGPD ne se renouvelle pas en silence.

        L'email pré-rempli évite à l'adhérent de le retaper. Les metadata sont
        renvoyées telles quelles dans le webhook → on y stocke `intent_id`,
        `tier`, `solidaire` pour rattacher la session à notre AdhesionIntent.
        """
        session: Any = await stripe.checkout.Session.create_async(
            mode="payment",
            payment_method_types=["card"],
            customer_email=email,
            line_items=[
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "eur",
                        "unit_amount": amount_eur_cents,
                        "product_data": {"name": product_label},
                    },
                },
            ],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
            locale="fr",
        )
        # L'email est volontairement hors du log — hygiène RGPD.
        log.info(
            "stripe.checkout.created",
            session_id=session.id,
            amount_eur_cents=amount_eur_cents,
        )
        return CheckoutSessionCreated(
            id=session.id,
            url=session.url,
            expires_at=session.expires_at,
        )

    async def create_subscription_checkout_session(
        self,
        *,
        email: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str],
    ) -> CheckoutSessionCreated:
        """Crée une Checkout Session en mode `subscription` (pay-as-you-go).

        Le `price_id` référence un Price *metered* adossé à un Billing Meter :
        la souscription n'a pas de montant fixe, elle facture l'usage agrégé en
        fin de période. Un line item metered se déclare **sans `quantity`** —
        Stripe rejette la quantité sur un prix à l'usage, c'est le meter qui
        porte le volume. `subscription_data.metadata` propage `user_id` jusqu'à
        la Subscription — c'est là que le webhook le relit.
        """
        session: Any = await stripe.checkout.Session.create_async(
            mode="subscription",
            customer_email=email,
            line_items=[{"price": price_id}],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata=metadata,
            subscription_data={"metadata": metadata},
            locale="fr",
        )
        # L'email est volontairement hors du log — hygiène RGPD.
        log.info(
            "stripe.subscription_checkout.created",
            session_id=session.id,
        )
        return CheckoutSessionCreated(
            id=session.id,
            url=session.url,
            expires_at=session.expires_at,
        )

    async def create_billing_portal_session(
        self, *, customer_id: str, return_url: str
    ) -> str:
        """Crée une session du Customer Portal Stripe et renvoie son URL.

        Le portail gère côté Stripe la résiliation et le moyen de paiement —
        inutile de coder un tunnel de gestion d'abonnement.
        """
        session: Any = await stripe.billing_portal.Session.create_async(
            customer=customer_id,
            return_url=return_url,
        )
        log.info("stripe.billing_portal.created", customer_id=customer_id)
        return str(session.url)

    async def record_meter_event(
        self,
        *,
        event_name: str,
        customer_id: str,
        value: int,
        identifier: str,
    ) -> None:
        """Enregistre un évènement d'usage sur un Billing Meter (pay-as-you-go).

        API courante `billing.MeterEvent` (et non l'ancienne `usage_records`,
        dépréciée). `identifier` est la clé d'idempotence : Stripe déduplique
        deux events de même identifiant sur une fenêtre glissante (≥ 24 h) — on
        y passe l'id d'interaction RAG, ce qui rend un rejeu (retry réseau,
        re-livraison) sans effet sur la facture. `value` est le volume agrégé
        par le meter (ici des tokens, agrégation `sum`).
        """
        await stripe.billing.MeterEvent.create_async(
            event_name=event_name,
            payload={"value": str(value), "stripe_customer_id": customer_id},
            identifier=identifier,
        )
        log.info(
            "stripe.meter_event.recorded",
            event_name=event_name,
            customer_id=customer_id,
            value=value,
            identifier=identifier,
        )

    def construct_event(self, payload: bytes, sig_header: str) -> stripe.Event:
        """Vérifie la signature du webhook et reconstruit l'événement typé.

        Lève `stripe.error.SignatureVerificationError` si la signature est
        invalide. Le router doit attraper et renvoyer 400 sans toucher la DB.
        """
        if not self.webhook_secret:
            raise RuntimeError(
                "STRIPE_WEBHOOK_SECRET manquant : impossible de vérifier les webhooks"
            )
        return stripe.Webhook.construct_event(
            payload=payload,
            sig_header=sig_header,
            secret=self.webhook_secret,
        )


@lru_cache(maxsize=1)
def get_stripe_client() -> StripeClient:
    """Singleton Stripe construit depuis les settings."""
    return StripeClient(
        api_key=settings.stripe_secret_key,
        webhook_secret=settings.stripe_webhook_secret,
        api_base=settings.stripe_api_base,
    )

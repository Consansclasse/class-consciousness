# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du pay-as-you-go — enregistrement d'usage Stripe.

Pas de mock Python : Stripe est joué par `stripe-mock` (testcontainer, fixture
`stripe_mock_url` du conftest). On exerce le contrat réel de l'API
`billing.MeterEvent` du SDK et la logique métier `record_token_usage` :
facturer un abonné actif, ne rien facturer sinon.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
import stripe
from cc_api.clients.stripe import StripeClient
from cc_api.models import Abonnement, AbonnementStatus, User
from cc_api.services.abonnement import record_token_usage


@pytest_asyncio.fixture
async def payg_client(
    stripe_mock_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[StripeClient]:
    """StripeClient pointé sur stripe-mock — l'état global du SDK est restauré."""
    monkeypatch.setattr(stripe, "api_key", "sk_test_unit", raising=False)
    monkeypatch.setattr(stripe, "api_base", stripe_mock_url, raising=False)
    yield StripeClient("sk_test_unit", webhook_secret=None, api_base=stripe_mock_url)


def _active_abonnement(user_id: int) -> Abonnement:
    return Abonnement(
        user_id=user_id,
        stripe_customer_id="cus_payg_test",
        stripe_subscription_id="sub_payg_test",
        stripe_price_id="price_payg_test",
        status=AbonnementStatus.ACTIVE,
        current_period_end=datetime.now(UTC) + timedelta(days=20),
    )


async def test_record_meter_event_hits_stripe(payg_client: StripeClient) -> None:
    """L'appel `billing.MeterEvent` réel passe contre stripe-mock sans erreur."""
    await payg_client.record_meter_event(
        event_name="rag_tokens",
        customer_id="cus_payg_test",
        value=4200,
        identifier="qa-42",
    )


async def test_record_token_usage_bills_active_subscriber(
    clean_db: None, db_session: Any, payg_client: StripeClient
) -> None:
    """Un abonné actif est facturé : meter_event émis, renvoie True."""
    user = User(email="payg-bill@example.org", consent_data_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    db_session.add(_active_abonnement(user.id))
    await db_session.commit()

    billed = await record_token_usage(
        db_session,
        user_id=user.id,
        tokens=8400,
        identifier="qa-100",
        stripe_client=payg_client,
    )
    assert billed is True


async def test_record_token_usage_skips_without_subscription(
    clean_db: None, db_session: Any, payg_client: StripeClient
) -> None:
    """Sans abonnement actif (requête du quota gratuit), aucune facturation."""
    user = User(email="payg-free@example.org", consent_data_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.commit()

    billed = await record_token_usage(
        db_session,
        user_id=user.id,
        tokens=8400,
        identifier="qa-101",
        stripe_client=payg_client,
    )
    assert billed is False


async def test_record_token_usage_skips_zero_tokens(
    clean_db: None, db_session: Any, payg_client: StripeClient
) -> None:
    """Zéro token facturable → no-op, même avec un abonnement actif."""
    user = User(email="payg-zero@example.org", consent_data_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    db_session.add(_active_abonnement(user.id))
    await db_session.commit()

    billed = await record_token_usage(
        db_session,
        user_id=user.id,
        tokens=0,
        identifier="qa-102",
        stripe_client=payg_client,
    )
    assert billed is False

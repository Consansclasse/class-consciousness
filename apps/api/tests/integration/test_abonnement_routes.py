# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration /abonnements — webhooks Stripe Billing signés.

Pas de mock : la DB est un testcontainer Postgres réel. Les events Stripe sont
signés à la main (webhooks = Stripe → serveur, sens non couvert par stripe-mock).
Aucun appel sortant à l'API Stripe ici → pas besoin du conteneur stripe-mock :
`construct_event` est une vérification de signature purement locale et
`handle_stripe_event` ne fait que de la DB.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from cc_api.models import Abonnement, AbonnementStatus, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_WEBHOOK_SECRET = "whsec_test_for_signing_only"


@pytest_asyncio.fixture
async def webhook_env(
    monkeypatch: pytest.MonkeyPatch,
    migrated_db: str,
) -> AsyncIterator[None]:
    """Patche settings (Stripe + DB) vers le testcontainer et purge les caches."""
    from cc_api.clients import db as db_module
    from cc_api.clients import stripe as stripe_client_module
    from cc_api.core.settings import settings

    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_unit", raising=False)
    monkeypatch.setattr(
        settings, "stripe_webhook_secret", _WEBHOOK_SECRET, raising=False
    )

    parsed = urlparse(migrated_db)
    monkeypatch.setattr(settings, "postgres_host", parsed.hostname or "localhost")
    monkeypatch.setattr(settings, "postgres_port", parsed.port or 5432)
    monkeypatch.setattr(settings, "postgres_user", parsed.username or "cc")
    monkeypatch.setattr(settings, "postgres_password", parsed.password or "cc")
    monkeypatch.setattr(settings, "postgres_db", (parsed.path or "/cc_test").lstrip("/"))

    stripe_client_module.get_stripe_client.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()
    yield
    stripe_client_module.get_stripe_client.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()


def _sign(body: bytes) -> str:
    """Génère un header Stripe-Signature valide pour `body`."""
    ts = int(time.time())
    signed = f"{ts}.{body.decode()}".encode()
    sig = hmac.new(_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _subscription_event(
    event_type: str,
    sub_id: str,
    *,
    status: str,
    user_id: int,
    period_end: int,
    price_id: str = "price_test_mensuel",
    cancel_at_period_end: bool = False,
    canceled_at: int | None = None,
) -> dict[str, Any]:
    """Construit un event `customer.subscription.*` minimaliste."""
    return {
        "id": f"evt_{sub_id}_{event_type.replace('.', '_')}",
        "object": "event",
        "type": event_type,
        "data": {
            "object": {
                "id": sub_id,
                "object": "subscription",
                "status": status,
                "customer": "cus_testabonne",
                "current_period_end": period_end,
                "cancel_at_period_end": cancel_at_period_end,
                "canceled_at": canceled_at,
                "metadata": {"user_id": str(user_id)},
                "items": {
                    "object": "list",
                    "data": [
                        {
                            "object": "subscription_item",
                            "price": {"id": price_id, "object": "price"},
                        }
                    ],
                },
            }
        },
    }


async def _make_user(db_session: AsyncSession, email: str) -> int:
    """Insère un User (un abonnement a une FK vers users) et renvoie son id."""
    user = User(email=email)
    db_session.add(user)
    await db_session.commit()
    return user.id


def _post_event(client: Any, event: dict[str, Any]) -> Any:
    body = json.dumps(event, separators=(",", ":")).encode()
    return client.post(
        "/abonnements/webhook/stripe",
        content=body,
        headers={"Stripe-Signature": _sign(body), "Content-Type": "application/json"},
    )


async def _abonnements(db_url: Any) -> list[Abonnement]:
    """Relit tous les abonnements via une session fraîche (le webhook commit ailleurs)."""
    engine = create_async_engine(db_url, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as fresh:
            return list((await fresh.execute(select(Abonnement))).scalars().all())
    finally:
        await engine.dispose()


# ── Tests ────────────────────────────────────────────────────────────────────


async def test_webhook_invalid_signature_returns_400(
    webhook_env: None,
    clean_db: None,
    client: Any,
) -> None:
    """Sans signature valide, le webhook répond 400 sans toucher la DB."""
    res = client.post(
        "/abonnements/webhook/stripe",
        content=b'{"id":"evt_x","type":"customer.subscription.created"}',
        headers={"Stripe-Signature": "t=1,v1=bad"},
    )
    assert res.status_code == 400


async def test_webhook_created_inserts_abonnement(
    webhook_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """customer.subscription.created → ligne Abonnement ACTIVE rattachée au user."""
    user_id = await _make_user(db_session, "abonne@example.org")
    period_end = int(time.time()) + 30 * 24 * 3600
    event = _subscription_event(
        "customer.subscription.created",
        "sub_test_1",
        status="active",
        user_id=user_id,
        period_end=period_end,
    )

    res = _post_event(client, event)
    assert res.status_code == 200, res.text

    rows = await _abonnements(db_session.bind.url)  # type: ignore[union-attr]
    assert len(rows) == 1
    abo = rows[0]
    assert abo.user_id == user_id
    assert abo.stripe_subscription_id == "sub_test_1"
    assert abo.status == AbonnementStatus.ACTIVE
    assert abo.stripe_price_id == "price_test_mensuel"
    assert abo.cancel_at_period_end is False


async def test_webhook_updated_changes_status(
    webhook_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """Un échec de paiement (past_due) met l'abonnement à jour, sans doublon."""
    user_id = await _make_user(db_session, "pastdue@example.org")
    period_end = int(time.time()) + 30 * 24 * 3600

    assert (
        _post_event(
            client,
            _subscription_event(
                "customer.subscription.created",
                "sub_test_2",
                status="active",
                user_id=user_id,
                period_end=period_end,
            ),
        ).status_code
        == 200
    )
    assert (
        _post_event(
            client,
            _subscription_event(
                "customer.subscription.updated",
                "sub_test_2",
                status="past_due",
                user_id=user_id,
                period_end=period_end,
            ),
        ).status_code
        == 200
    )

    rows = await _abonnements(db_session.bind.url)  # type: ignore[union-attr]
    assert len(rows) == 1
    assert rows[0].status == AbonnementStatus.PAST_DUE


async def test_webhook_idempotent_on_replay(
    webhook_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """Rejouer le même event de création ne crée pas de doublon."""
    user_id = await _make_user(db_session, "replay@example.org")
    period_end = int(time.time()) + 30 * 24 * 3600
    event = _subscription_event(
        "customer.subscription.created",
        "sub_test_3",
        status="active",
        user_id=user_id,
        period_end=period_end,
    )

    for _ in range(3):
        assert _post_event(client, event).status_code == 200

    engine = create_async_engine(db_session.bind.url, echo=False)  # type: ignore[union-attr]
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as fresh:
            count = (
                await fresh.execute(select(func.count()).select_from(Abonnement))
            ).scalar_one()
    finally:
        await engine.dispose()
    assert count == 1


async def test_webhook_deleted_marks_canceled(
    webhook_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """customer.subscription.deleted → statut CANCELED + canceled_at horodaté."""
    user_id = await _make_user(db_session, "canceled@example.org")
    period_end = int(time.time()) + 30 * 24 * 3600

    _post_event(
        client,
        _subscription_event(
            "customer.subscription.created",
            "sub_test_4",
            status="active",
            user_id=user_id,
            period_end=period_end,
        ),
    )
    res = _post_event(
        client,
        _subscription_event(
            "customer.subscription.deleted",
            "sub_test_4",
            status="canceled",
            user_id=user_id,
            period_end=period_end,
            canceled_at=int(time.time()),
        ),
    )
    assert res.status_code == 200, res.text

    rows = await _abonnements(db_session.bind.url)  # type: ignore[union-attr]
    assert len(rows) == 1
    assert rows[0].status == AbonnementStatus.CANCELED
    assert rows[0].canceled_at is not None

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration /adhesions — Stripe Checkout + webhook signé.

Pas de mocks Python : Stripe est joué par `stripe-mock` (image officielle
`stripe/stripe-mock`) lancée via testcontainers. Le webhook est signé à la
main car stripe-mock ne génère pas d'events (c'est par design : webhooks =
Stripe → notre serveur, on simule ce sens).

Couverture :

- create_checkout standard → 201 + intent PENDING + User créé + consent_data_at
- create_checkout avec consent_data manquant → 422
- create_checkout solidaire INDIVIDUAL → pas d'appel Stripe + Membership 0 €
- webhook signature invalide → 400, aucun side-effect
- webhook checkout.session.completed → Membership active, intent COMPLETED
- webhook rejoué (idempotence) → 1 seule Membership, statut inchangé
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio
import stripe
from cc_api.models import AdhesionIntent, AdhesionIntentStatus, Membership, User
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

_WEBHOOK_SECRET = "whsec_test_for_signing_only"


@pytest.fixture(scope="session")
def stripe_mock_url() -> Iterator[str]:
    """Lance stripe-mock en testcontainer et renvoie son URL HTTP.

    stripe-mock écoute par défaut sur 12111 (HTTP). Il accepte n'importe quelle
    clé API `sk_test_…` et renvoie des fixtures Stripe conformes à l'OpenAPI
    spec officielle.
    """
    try:
        from testcontainers.core.container import DockerContainer
        from testcontainers.core.waiting_utils import wait_for_logs
    except ImportError:
        pytest.skip("testcontainers not installed")

    # Le démon Docker peut dépasser le timeout API de 60 s de docker-py quand
    # la machine est chargée (suite complète + serveur GPU cc-embed) : le
    # `containers/create` du conteneur stripe-mock lève alors un ReadTimeout.
    # On réessaie le démarrage plutôt que d'errer toute la suite adhésion.
    container = None
    last_exc: Exception | None = None
    for _attempt in range(3):
        candidate = DockerContainer("stripe/stripe-mock:latest").with_exposed_ports(12111)
        try:
            candidate.start()
            container = candidate
            break
        except Exception as exc:  # docker-py : ReadTimeout, transport, etc.
            last_exc = exc
            with contextlib.suppress(Exception):
                candidate.stop()
            time.sleep(3)
    if container is None:
        pytest.skip(f"stripe-mock indisponible après 3 tentatives : {last_exc}")
    try:
        # stripe-mock >= 0.199 loggue « Listening for HTTP at address: [::]:12111 »
        # (et non plus « ... on port 12111 ») — on matche le prefixe stable.
        wait_for_logs(container, "Listening for HTTP", timeout=60)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(12111)
        yield f"http://{host}:{port}"
    finally:
        container.stop()


@pytest_asyncio.fixture
async def stripe_env(
    monkeypatch: pytest.MonkeyPatch,
    stripe_mock_url: str,
    migrated_db: str,
) -> AsyncIterator[None]:
    """Patche settings + module stripe pour pointer sur stripe-mock + DB de test.

    On invalide aussi les caches lru_cache pour que le client se reconstruise.
    """
    from cc_api.clients import db as db_module
    from cc_api.clients import stripe as stripe_client_module
    from cc_api.core.settings import settings

    # Configuration Stripe pour les tests.
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_unit", raising=False)
    monkeypatch.setattr(
        settings, "stripe_publishable_key", "pk_test_unit", raising=False
    )
    monkeypatch.setattr(
        settings, "stripe_webhook_secret", _WEBHOOK_SECRET, raising=False
    )
    monkeypatch.setattr(settings, "stripe_api_base", stripe_mock_url, raising=False)
    monkeypatch.setattr(settings, "public_web_base", "http://test.local", raising=False)

    # Configuration DB pour pointer sur le testcontainer Postgres.
    from urllib.parse import urlparse

    parsed = urlparse(migrated_db)
    monkeypatch.setattr(settings, "postgres_host", parsed.hostname or "localhost")
    monkeypatch.setattr(settings, "postgres_port", parsed.port or 5432)
    monkeypatch.setattr(settings, "postgres_user", parsed.username or "cc")
    monkeypatch.setattr(settings, "postgres_password", parsed.password or "cc")
    monkeypatch.setattr(
        settings, "postgres_db", (parsed.path or "/cc_test").lstrip("/")
    )

    # Vider les caches lru_cache pour que les singletons se reconstruisent.
    stripe_client_module.get_stripe_client.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()

    # Forcer aussi le module stripe global (api_key + api_base).
    monkeypatch.setattr(stripe, "api_key", "sk_test_unit", raising=False)
    monkeypatch.setattr(stripe, "api_base", stripe_mock_url, raising=False)

    yield

    stripe_client_module.get_stripe_client.cache_clear()
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()


def _sign_webhook(body_bytes: bytes, secret: str) -> str:
    """Génère un header Stripe-Signature valide pour `body_bytes`."""
    ts = int(time.time())
    signed = f"{ts}.{body_bytes.decode()}".encode()
    sig = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def _make_completed_event(
    session_id: str,
    *,
    payment_status: str = "paid",
) -> dict[str, Any]:
    """Construit un event `checkout.session.completed` minimaliste."""
    return {
        "id": f"evt_test_{session_id}",
        "object": "event",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": session_id,
                "object": "checkout.session",
                "payment_status": payment_status,
            },
        },
    }


# ── Tests checkout ──────────────────────────────────────────────────────────


async def test_checkout_standard_creates_intent_and_user(
    stripe_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """POST /adhesions/checkout standard → 201 + intent PENDING + User créé."""
    payload = {
        "email": "alice@example.org",
        "display_name": "Alice",
        "tier": "INDIVIDUAL",
        "solidaire": False,
        "consent_data": True,
        "consent_newsletter": False,
    }
    res = client.post("/adhesions/checkout", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert "public_token" in body
    # L'id séquentiel ne doit JAMAIS être exposé (vecteur d'énumération IDOR).
    assert "intent_id" not in body
    assert body["redirect_url"].startswith("http"), body
    assert "expires_at" in body

    # User créé avec consent_data_at horodaté.
    user = (
        await db_session.execute(select(User).where(User.email == "alice@example.org"))
    ).scalar_one()
    assert user.display_name == "Alice"
    assert user.consent_data_at is not None
    assert user.consent_newsletter_at is None  # opt-in pas coché

    # AdhesionIntent en PENDING.
    intent = (
        await db_session.execute(
            select(AdhesionIntent).where(
                AdhesionIntent.public_token == body["public_token"]
            )
        )
    ).scalar_one()
    assert intent.status == AdhesionIntentStatus.PENDING
    assert intent.amount_eur_cents == 900
    assert intent.user_id == user.id
    assert intent.stripe_session_id.startswith("cs_")


async def test_checkout_refuses_without_consent(
    stripe_env: None,
    clean_db: None,
    client: Any,
) -> None:
    """Sans consent_data=True, Pydantic rejette → 422."""
    payload = {
        "email": "noconsent@example.org",
        "tier": "INDIVIDUAL",
        "solidaire": False,
        "consent_data": False,  # interdit
        "consent_newsletter": False,
    }
    res = client.post("/adhesions/checkout", json=payload)
    assert res.status_code == 422, res.text


async def test_checkout_solidaire_creates_membership_immediately(
    stripe_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """Tarif solidaire INDIVIDUAL → pas d'appel Stripe, Membership 0 € créée."""
    payload = {
        "email": "militant@example.org",
        "tier": "INDIVIDUAL",
        "solidaire": True,
        "consent_data": True,
        "consent_newsletter": False,
    }
    res = client.post("/adhesions/checkout", json=payload)
    assert res.status_code == 201, res.text
    body = res.json()
    assert "solidaire=1" in body["redirect_url"]

    intent = (
        await db_session.execute(
            select(AdhesionIntent).where(
                AdhesionIntent.public_token == body["public_token"]
            )
        )
    ).scalar_one()
    assert intent.status == AdhesionIntentStatus.COMPLETED
    assert intent.amount_eur_cents == 0
    assert intent.paid_at is not None

    # Membership directement active.
    mem_count = (
        await db_session.execute(select(func.count()).select_from(Membership))
    ).scalar_one()
    assert mem_count == 1


# ── Tests webhook ───────────────────────────────────────────────────────────


async def test_webhook_invalid_signature_returns_400(
    stripe_env: None,
    clean_db: None,
    client: Any,
) -> None:
    """Sans signature valide, le webhook répond 400 sans toucher la DB."""
    res = client.post(
        "/adhesions/webhook/stripe",
        content=b'{"id":"evt_fake","type":"checkout.session.completed"}',
        headers={"Stripe-Signature": "t=1,v1=bad"},
    )
    assert res.status_code == 400


async def test_webhook_completed_creates_membership(
    stripe_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """checkout.session.completed → intent COMPLETED + Membership créée."""
    # Étape 1 : créer un intent via /checkout pour obtenir un stripe_session_id réel.
    payload = {
        "email": "bob@example.org",
        "tier": "STRUCTURE",
        "solidaire": False,
        "consent_data": True,
        "consent_newsletter": True,
    }
    res = client.post("/adhesions/checkout", json=payload)
    assert res.status_code == 201
    token = res.json()["public_token"]

    intent = (
        await db_session.execute(
            select(AdhesionIntent).where(AdhesionIntent.public_token == token)
        )
    ).scalar_one()
    session_id = intent.stripe_session_id

    # Étape 2 : envoyer un webhook signé avec ce session_id.
    event = _make_completed_event(session_id)
    body = json.dumps(event, separators=(",", ":")).encode()
    sig = _sign_webhook(body, _WEBHOOK_SECRET)

    res = client.post(
        "/adhesions/webhook/stripe",
        content=body,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
    )
    assert res.status_code == 200, res.text

    # Étape 3 : nouvelle session DB (le webhook a commité dans une session séparée).
    fresh_engine = create_async_engine(
        db_session.bind.url, echo=False  # type: ignore[union-attr]
    )
    maker = async_sessionmaker(fresh_engine, expire_on_commit=False)
    async with maker() as fresh:
        intent_after = (
            await fresh.execute(
                select(AdhesionIntent).where(AdhesionIntent.public_token == token)
            )
        ).scalar_one()
        assert intent_after.status == AdhesionIntentStatus.COMPLETED
        assert intent_after.paid_at is not None

        memberships = (
            await fresh.execute(
                select(Membership).where(Membership.user_id == intent_after.user_id)
            )
        ).scalars().all()
        assert len(memberships) == 1
        assert memberships[0].amount_eur_cents == 9900
        assert memberships[0].external_reference == session_id
    await fresh_engine.dispose()


async def test_webhook_idempotent_on_replay(
    stripe_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """Rejouer le même event ne crée pas de Membership en double."""
    payload = {
        "email": "carol@example.org",
        "tier": "INDIVIDUAL",
        "solidaire": False,
        "consent_data": True,
        "consent_newsletter": False,
    }
    res = client.post("/adhesions/checkout", json=payload)
    token = res.json()["public_token"]
    intent = (
        await db_session.execute(
            select(AdhesionIntent).where(AdhesionIntent.public_token == token)
        )
    ).scalar_one()
    session_id = intent.stripe_session_id

    event = _make_completed_event(session_id)
    body = json.dumps(event, separators=(",", ":")).encode()
    sig = _sign_webhook(body, _WEBHOOK_SECRET)

    for _ in range(3):
        # Re-signer à chaque envoi (timestamp change) — mais même event.id.
        sig = _sign_webhook(body, _WEBHOOK_SECRET)
        res = client.post(
            "/adhesions/webhook/stripe",
            content=body,
            headers={"Stripe-Signature": sig, "Content-Type": "application/json"},
        )
        assert res.status_code == 200, res.text

    fresh_engine = create_async_engine(
        db_session.bind.url, echo=False  # type: ignore[union-attr]
    )
    maker = async_sessionmaker(fresh_engine, expire_on_commit=False)
    async with maker() as fresh:
        mem_count = (
            await fresh.execute(select(func.count()).select_from(Membership))
        ).scalar_one()
        assert mem_count == 1
    await fresh_engine.dispose()


# ── Tests GET /intent — anti-IDOR ────────────────────────────────────────────


async def test_get_intent_by_token_returns_status(
    stripe_env: None,
    clean_db: None,
    client: Any,
) -> None:
    """GET /adhesions/intent/{token} renvoie l'état via le jeton opaque."""
    payload = {
        "email": "dora@example.org",
        "tier": "INDIVIDUAL",
        "solidaire": False,
        "consent_data": True,
        "consent_newsletter": False,
    }
    res = client.post("/adhesions/checkout", json=payload)
    assert res.status_code == 201, res.text
    token = res.json()["public_token"]

    res = client.get(f"/adhesions/intent/{token}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["public_token"] == token
    assert body["status"] == "PENDING"
    assert body["tier"] == "INDIVIDUAL"
    assert body["amount_eur_cents"] == 900
    # L'id séquentiel ne fuit jamais dans la réponse.
    assert "intent_id" not in body


async def test_get_intent_rejects_sequential_id_enumeration(
    stripe_env: None,
    clean_db: None,
    client: Any,
    db_session: AsyncSession,
) -> None:
    """L'IDOR est fermé : énumérer l'id entier ou deviner un jeton → 404.

    Régression du correctif sécurité : avant le jeton opaque, GET /intent/{id}
    indexé par l'entier auto-incrément exposait tout le registre d'adhésions.
    """
    payload = {
        "email": "eve@example.org",
        "tier": "MECENE",
        "solidaire": False,
        "consent_data": True,
        "consent_newsletter": False,
    }
    res = client.post("/adhesions/checkout", json=payload)
    assert res.status_code == 201, res.text
    token = res.json()["public_token"]

    # L'intent existe bien — on récupère son id séquentiel réel en base.
    intent = (
        await db_session.execute(
            select(AdhesionIntent).where(AdhesionIntent.public_token == token)
        )
    ).scalar_one()

    # Énumérer l'entier séquentiel ne résout plus rien.
    res = client.get(f"/adhesions/intent/{intent.id}")
    assert res.status_code == 404, res.text
    # Pas davantage en balayant les premiers entiers.
    for guess in (1, 2, 3):
        assert client.get(f"/adhesions/intent/{guess}").status_code == 404
    # Un jeton inventé est rejeté.
    assert client.get("/adhesions/intent/jeton-bidon-inexistant").status_code == 404

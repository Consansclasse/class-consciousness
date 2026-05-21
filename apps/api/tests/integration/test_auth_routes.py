# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration de l'authentification par magic-link.

Base = testcontainer Postgres réel. Le flux complet (request → verify →
session → me → logout) est exercé via TestClient, qui gère le cookie de
session. SMTP non configuré en test → le lien est renvoyé dans `devMagicLink`.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from cc_api.models import AuthToken, User


@pytest_asyncio.fixture
async def auth_env(
    monkeypatch: pytest.MonkeyPatch, migrated_db: str
) -> AsyncIterator[None]:
    """Pointe la DB applicative vers le testcontainer et purge les caches."""
    from cc_api.clients import db as db_module
    from cc_api.core.settings import settings

    parsed = urlparse(migrated_db)
    monkeypatch.setattr(settings, "postgres_host", parsed.hostname or "localhost")
    monkeypatch.setattr(settings, "postgres_port", parsed.port or 5432)
    monkeypatch.setattr(settings, "postgres_user", parsed.username or "cc")
    monkeypatch.setattr(settings, "postgres_password", parsed.password or "cc")
    monkeypatch.setattr(settings, "postgres_db", (parsed.path or "/cc_test").lstrip("/"))
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()
    yield
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()


def _token_from_link(link: str) -> str:
    """Extrait le paramètre `token` du magic-link."""
    return parse_qs(urlparse(link).query)["token"][0]


async def test_magic_link_full_flow(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """request-link → verify → session active → me → logout → me refusé."""
    req = client.post("/auth/request-link", json={"email": "militante@example.org"})
    assert req.status_code == 200, req.text
    token = _token_from_link(req.json()["devMagicLink"])

    verified = client.post("/auth/verify", json={"token": token})
    assert verified.status_code == 200, verified.text
    assert verified.json()["email"] == "militante@example.org"

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "militante@example.org"

    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401


async def test_me_requires_authentication(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """GET /auth/me sans session ouverte → 401."""
    assert client.get("/auth/me").status_code == 401


async def test_verify_rejects_unknown_token(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Un token inconnu est refusé (401)."""
    res = client.post("/auth/verify", json={"token": "x" * 40})
    assert res.status_code == 401


async def test_verify_rejects_reused_token(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Un magic-link est à usage unique : la 2ᵉ vérification échoue."""
    req = client.post("/auth/request-link", json={"email": "unique@example.org"})
    token = _token_from_link(req.json()["devMagicLink"])

    assert client.post("/auth/verify", json={"token": token}).status_code == 200
    assert client.post("/auth/verify", json={"token": token}).status_code == 401


async def test_verify_rejects_expired_token(
    auth_env: None, clean_db: None, client: Any, db_session: Any
) -> None:
    """Un magic-link expiré est refusé."""
    user = User(email="expire@example.org", consent_data_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    raw = "expired-token-aaaaaaaaaaaaaaaaaaaa"
    db_session.add(
        AuthToken(
            user_id=user.id,
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
        )
    )
    await db_session.commit()

    res = client.post("/auth/verify", json={"token": raw})
    assert res.status_code == 401

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration de l'authentification par email + mot de passe.

Base = testcontainer Postgres réel. Les flux complets (register → vérification →
login → reset) sont exercés via TestClient (qui gère le cookie de session). SMTP
non configuré en test → le lien est renvoyé dans `devLink`.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio

_PWD = "motdepasse-de-test"


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


def _token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def _register(client: Any, email: str, password: str = _PWD) -> str:
    """Inscrit `email` et renvoie le token de vérification (via devLink)."""
    res = client.post(
        "/auth/register",
        json={"email": email, "password": password, "consent_data": True},
    )
    assert res.status_code == 200, res.text
    return _token(res.json()["devLink"])


async def test_register_verify_login_full_flow(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """register → verify-email (ouvre session) → me → logout → login → me."""
    token = _register(client, "militante@example.org")

    verified = client.post("/auth/verify-email", json={"token": token})
    assert verified.status_code == 200, verified.text
    assert verified.json()["email"] == "militante@example.org"

    me = client.get("/auth/me")
    assert me.status_code == 200
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/auth/me").status_code == 401

    # Connexion par mot de passe après vérification.
    logged = client.post(
        "/auth/login", json={"email": "militante@example.org", "password": _PWD}
    )
    assert logged.status_code == 200, logged.text
    assert client.get("/auth/me").status_code == 200


async def test_login_refused_before_verification(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Tant que l'email n'est pas vérifié, la connexion est refusée."""
    _register(client, "pasverif@example.org")
    res = client.post(
        "/auth/login", json={"email": "pasverif@example.org", "password": _PWD}
    )
    assert res.status_code == 401


async def test_login_wrong_password(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Mot de passe erroné → 401."""
    token = _register(client, "user@example.org")
    client.post("/auth/verify-email", json={"token": token})
    client.post("/auth/logout")
    res = client.post(
        "/auth/login", json={"email": "user@example.org", "password": "faux-mot-de-passe"}
    )
    assert res.status_code == 401


async def test_login_unknown_email(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Email inconnu → 401 (message générique, pas d'oracle)."""
    res = client.post(
        "/auth/login", json={"email": "inconnu@example.org", "password": _PWD}
    )
    assert res.status_code == 401


async def test_me_requires_authentication(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """GET /auth/me sans session → 401."""
    assert client.get("/auth/me").status_code == 401


async def test_register_rejects_missing_consent(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Sans consent_data=True, Pydantic rejette → 422."""
    res = client.post(
        "/auth/register", json={"email": "noconsent@example.org", "password": _PWD}
    )
    assert res.status_code == 422


async def test_register_rejects_short_password(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Mot de passe trop court (< 10) → 422."""
    res = client.post(
        "/auth/register",
        json={"email": "court@example.org", "password": "court", "consent_data": True},
    )
    assert res.status_code == 422


async def test_register_existing_verified_is_generic(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Réinscrire une adresse déjà vérifiée → 200 générique SANS devLink (pas d'oracle)."""
    token = _register(client, "deja@example.org")
    client.post("/auth/verify-email", json={"token": token})
    client.post("/auth/logout")

    res = client.post(
        "/auth/register",
        json={"email": "deja@example.org", "password": "autre-mot-de-passe", "consent_data": True},
    )
    assert res.status_code == 200
    assert "devLink" not in res.json()


async def test_verify_email_rejects_unknown_token(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Token de vérification inconnu → 401."""
    assert (
        client.post("/auth/verify-email", json={"token": "x" * 40}).status_code == 401
    )


async def test_verify_email_rejects_reuse(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Un token de vérification est à usage unique."""
    token = _register(client, "unique@example.org")
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 401


async def test_forgot_and_reset_password(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """forgot-password → reset-password → connexion avec le nouveau mot de passe."""
    token = _register(client, "reset@example.org")
    client.post("/auth/verify-email", json={"token": token})
    client.post("/auth/logout")

    forgot = client.post("/auth/forgot-password", json={"email": "reset@example.org"})
    assert forgot.status_code == 200
    reset_token = _token(forgot.json()["devLink"])

    new_pwd = "nouveau-mot-de-passe"
    reset = client.post(
        "/auth/reset-password", json={"token": reset_token, "password": new_pwd}
    )
    assert reset.status_code == 200

    # L'ancien mot de passe ne marche plus, le nouveau oui.
    assert client.post(
        "/auth/login", json={"email": "reset@example.org", "password": _PWD}
    ).status_code == 401
    assert client.post(
        "/auth/login", json={"email": "reset@example.org", "password": new_pwd}
    ).status_code == 200


async def test_forgot_password_unknown_email_is_generic(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """forgot-password sur un email inconnu → 200 sans devLink (pas d'oracle)."""
    res = client.post("/auth/forgot-password", json={"email": "personne@example.org"})
    assert res.status_code == 200
    assert "devLink" not in res.json()


async def test_reset_password_rejects_unknown_token(
    auth_env: None, clean_db: None, client: Any
) -> None:
    """Token de reset inconnu → 401."""
    res = client.post(
        "/auth/reset-password", json={"token": "y" * 40, "password": "un-mot-de-passe"}
    )
    assert res.status_code == 401

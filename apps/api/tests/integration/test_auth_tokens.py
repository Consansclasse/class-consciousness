# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du modèle AuthToken (magic-link à usage unique).

Cycle de vie : created (used_at=NULL) → consumed (used_at=now()).
Le hash sha256 est unique → empêche les collisions et les doubles emails.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cc_api.models import AuthToken, User
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def _new_token_hash() -> str:
    """Génère un token brut puis renvoie son hash sha256 hex (64 chars)."""
    raw = secrets.token_hex(32)
    return hashlib.sha256(raw.encode("ascii")).hexdigest()


async def test_token_hash_unique(
    clean_db: None,
    db_session: Any,
) -> None:
    """Deux AuthToken avec même hash → IntegrityError."""
    user = User(email="auth1@example.org")
    db_session.add(user)
    await db_session.flush()

    token_hash = _new_token_hash()
    expires = datetime.now(tz=UTC) + timedelta(minutes=15)
    db_session.add(AuthToken(user_id=user.id, token_hash=token_hash, expires_at=expires))
    await db_session.commit()

    db_session.add(AuthToken(user_id=user.id, token_hash=token_hash, expires_at=expires))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


async def test_consume_marks_used_at(
    clean_db: None,
    db_session: Any,
) -> None:
    """Un token initial a used_at=NULL ; après consommation, used_at = datetime."""
    user = User(email="auth2@example.org")
    db_session.add(user)
    await db_session.flush()

    expires = datetime.now(tz=UTC) + timedelta(minutes=15)
    token = AuthToken(user_id=user.id, token_hash=_new_token_hash(), expires_at=expires)
    db_session.add(token)
    await db_session.commit()
    await db_session.refresh(token)

    assert token.used_at is None

    consumed_at = datetime.now(tz=UTC)
    token.used_at = consumed_at
    await db_session.commit()
    await db_session.refresh(token)

    assert token.used_at is not None
    # Tolérance : la précision DB peut tronquer les microsecondes.
    assert abs((token.used_at - consumed_at).total_seconds()) < 1.0


async def test_expired_token_detectable(
    clean_db: None,
    db_session: Any,
) -> None:
    """Un token avec expires_at < now() doit être détectable en query."""
    user = User(email="auth3@example.org")
    db_session.add(user)
    await db_session.flush()

    now = datetime.now(tz=UTC)
    fresh = AuthToken(
        user_id=user.id,
        token_hash=_new_token_hash(),
        expires_at=now + timedelta(minutes=15),
    )
    expired = AuthToken(
        user_id=user.id,
        token_hash=_new_token_hash(),
        expires_at=now - timedelta(minutes=1),
    )
    db_session.add_all([fresh, expired])
    await db_session.commit()

    expired_tokens = (
        (await db_session.execute(select(AuthToken).where(AuthToken.expires_at < now)))
        .scalars()
        .all()
    )
    assert len(expired_tokens) == 1
    assert expired_tokens[0].token_hash == expired.token_hash


async def test_token_cascade_delete_with_user(
    clean_db: None,
    db_session: Any,
) -> None:
    """Supprimer un User cascade sur ses auth_tokens (FK ondelete=CASCADE)."""
    user = User(email="auth-cascade@example.org")
    db_session.add(user)
    await db_session.flush()

    expires = datetime.now(tz=UTC) + timedelta(minutes=15)
    db_session.add(AuthToken(user_id=user.id, token_hash=_new_token_hash(), expires_at=expires))
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()

    remaining = (await db_session.execute(select(AuthToken))).scalars().all()
    assert remaining == []

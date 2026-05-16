# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration des modèles User + Membership.

Pas de mocks DB : testcontainers Postgres réels via fixtures `db_session` + `clean_db`.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import pytest
from cc_api.models import Membership, MembershipSource, MembershipTier, User
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


async def test_create_user_with_email_unique(
    clean_db: None,
    db_session: Any,
) -> None:
    """L'unicité de l'email est garantie au niveau DB (UniqueConstraint)."""
    db_session.add(User(email="alice@example.org", display_name="Alice"))
    await db_session.commit()

    db_session.add(User(email="alice@example.org", display_name="Alice doublon"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    count = (await db_session.execute(select(func.count()).select_from(User))).scalar_one()
    assert count == 1


async def test_membership_active_at_date(
    clean_db: None,
    db_session: Any,
) -> None:
    """Une membership avec valid_until ≥ date Y est considérée active à date Y."""
    user = User(email="bob@example.org")
    db_session.add(user)
    await db_session.flush()

    today = date.today()
    yesterday = today - timedelta(days=1)
    last_year = today - timedelta(days=400)
    next_month = today + timedelta(days=30)

    db_session.add(
        Membership(
            user_id=user.id,
            tier=MembershipTier.INDIVIDUAL,
            valid_from=yesterday,
            valid_until=next_month,
            amount_eur_cents=900,
            source=MembershipSource.MANUEL,
        )
    )
    db_session.add(
        Membership(
            user_id=user.id,
            tier=MembershipTier.INDIVIDUAL,
            valid_from=last_year,
            valid_until=last_year + timedelta(days=365),  # expirée
            amount_eur_cents=900,
            source=MembershipSource.MANUEL,
        )
    )
    await db_session.commit()

    # « Tier actif à date Y » = membership avec valid_until ≥ Y AND valid_from ≤ Y.
    actives = (
        (
            await db_session.execute(
                select(Membership).where(
                    Membership.user_id == user.id,
                    Membership.valid_from <= today,
                    Membership.valid_until >= today,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(actives) == 1
    assert actives[0].tier == MembershipTier.INDIVIDUAL


async def test_solidaire_orthogonal_to_tier(
    clean_db: None,
    db_session: Any,
) -> None:
    """Le flag solidaire est déclaratif, indépendant du tier (modulation tarifaire)."""
    user = User(email="militant@example.org")
    db_session.add(user)
    await db_session.flush()

    today = date.today()
    membership = Membership(
        user_id=user.id,
        tier=MembershipTier.INDIVIDUAL,
        solidaire=True,
        valid_from=today,
        valid_until=today + timedelta(days=365),
        amount_eur_cents=0,  # solidaire = potentiellement 0 €
        source=MembershipSource.ADMIN,
    )
    db_session.add(membership)
    await db_session.commit()

    fetched = (
        await db_session.execute(select(Membership).where(Membership.user_id == user.id))
    ).scalar_one()
    assert fetched.tier == MembershipTier.INDIVIDUAL  # le tier reste INDIVIDUAL
    assert fetched.solidaire is True
    assert fetched.amount_eur_cents == 0


async def test_membership_cascade_delete_with_user(
    clean_db: None,
    db_session: Any,
) -> None:
    """Supprimer un User cascade sur ses memberships (FK ondelete=CASCADE)."""
    user = User(email="cascade@example.org")
    db_session.add(user)
    await db_session.flush()

    today = date.today()
    db_session.add(
        Membership(
            user_id=user.id,
            tier=MembershipTier.STRUCTURE,
            valid_from=today,
            valid_until=today + timedelta(days=365),
            amount_eur_cents=9900,
            source=MembershipSource.STRIPE,
        )
    )
    await db_session.commit()

    await db_session.delete(user)
    await db_session.commit()

    remaining = (
        await db_session.execute(select(func.count()).select_from(Membership))
    ).scalar_one()
    assert remaining == 0

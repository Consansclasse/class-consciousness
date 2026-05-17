# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle Abonnement — abonnement mensuel récurrent à l'application.

Vocabulaire juridique : **abonnement** = prestation de service vendue, à ne PAS
confondre avec la cotisation associative (`Membership`). Un abonné est un
client, pas un membre votant — la table n'a aucun lien avec le droit de vote.

Cycle de vie miroir de Stripe Billing : la ligne est créée puis mise à jour par
les webhooks `customer.subscription.*`. `status` reflète le statut Stripe.

Usage métier : le quota RAG quotidien est débloqué tant qu'un abonnement ACTIVE
ou TRIALING couvre la date courante (`current_period_end >= now`).
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.user import User


class AbonnementStatus(str, enum.Enum):  # noqa: UP042 — préserve compat Alembic/Postgres ENUM
    """Statut d'un abonnement — miroir des statuts Stripe Subscription.

    `incomplete_expired` et `paused` côté Stripe sont repliés à l'ingestion sur
    CANCELED / PAST_DUE : seuls ACTIVE et TRIALING ouvrent l'accès au quota.
    """

    ACTIVE = "ACTIVE"
    TRIALING = "TRIALING"
    PAST_DUE = "PAST_DUE"
    CANCELED = "CANCELED"
    INCOMPLETE = "INCOMPLETE"
    UNPAID = "UNPAID"


class Abonnement(Base):
    __tablename__ = "abonnements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stripe_customer_id: Mapped[str] = mapped_column(String(255), nullable=False)
    # Unique → idempotence des webhooks rejoués (un même event Stripe peut
    # arriver n fois ; l'upsert se fait par cet identifiant).
    stripe_subscription_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    stripe_price_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AbonnementStatus] = mapped_column(
        Enum(AbonnementStatus, name="abonnement_status"), nullable=False, index=True
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship()

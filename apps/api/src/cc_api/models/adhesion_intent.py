# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle AdhesionIntent — intention de paiement avant qu'elle ne devienne Membership.

Pourquoi cette table : Stripe Checkout est asynchrone. L'utilisateur peut
fermer l'onglet, le webhook peut arriver en retard, la session peut expirer
sans confirmation. Sans cette table, on ne saurait pas distinguer un user
« en train de payer » d'un user « qui a abandonné ».

Cycle de vie :
  PENDING ─► COMPLETED  (webhook `checkout.session.completed` reçu → Membership créée)
          ├► EXPIRED    (session.expires_at dépassée sans paiement)
          └► FAILED     (webhook `checkout.session.async_payment_failed`)

Idempotence : `stripe_session_id` UNIQUE. Un webhook Stripe peut être rejoué
n fois — l'unicité + le verrouillage du statut garantissent qu'une seule
Membership est créée.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base
from cc_api.models.membership import MembershipTier

if TYPE_CHECKING:
    from cc_api.models.user import User


class AdhesionIntentStatus(str, enum.Enum):  # noqa: UP042
    """Statut d'une intention de paiement Stripe."""

    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


class AdhesionIntent(Base):
    __tablename__ = "adhesion_intents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    tier: Mapped[MembershipTier] = mapped_column(
        Enum(MembershipTier, name="membership_tier", create_type=False), nullable=False
    )
    amount_eur_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    solidaire: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    stripe_session_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    stripe_redirect_url: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[AdhesionIntentStatus] = mapped_column(
        Enum(AdhesionIntentStatus, name="adhesion_intent_status", create_type=False),
        nullable=False,
        server_default="PENDING",
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User | None] = relationship()

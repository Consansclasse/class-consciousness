# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle Membership — adhésion associative d'un User.

Vocabulaire juridique : **cotisation annuelle**, pas « abonnement ».
Une cotisation = adhésion à l'association loi 1901, pas un service vendu.
Voir mémoire `project_tier_strategy` pour la stratégie de paliers.

Un User peut avoir plusieurs Memberships dans le temps (renouvellements).
Le « tier actif » = membership avec `valid_until >= now()`.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.user import User


class MembershipTier(str, enum.Enum):  # noqa: UP042 — préserve compat Alembic/Postgres ENUM existant
    """Paliers d'adhésion. ANONYMOUS n'est PAS ici (absence de membership = anonyme)."""

    INDIVIDUAL = "INDIVIDUAL"
    STRUCTURE = "STRUCTURE"
    MECENE = "MECENE"


class MembershipSource(str, enum.Enum):  # noqa: UP042 — préserve compat Alembic/Postgres ENUM existant
    """Origine technique de l'adhésion (audit trail).

    OPENCOLLECTIVE est conservé dans l'enum PG pour compatibilité de la migration
    initiale — il n'est plus utilisé. La voie active depuis 2026-05 est STRIPE.
    """

    STRIPE = "STRIPE"
    OPENCOLLECTIVE = "OPENCOLLECTIVE"
    MANUEL = "MANUEL"
    ADMIN = "ADMIN"
    AUTRE = "AUTRE"


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tier: Mapped[MembershipTier] = mapped_column(
        Enum(MembershipTier, name="membership_tier"), nullable=False, index=True
    )
    # Flag orthogonal au tier : déclaratif (étudiant, sans-emploi, militant sans budget).
    # Préserve le « P Public » des 4P (BOFIP) en attestant la modulation tarifaire.
    solidaire: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_until: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount_eur_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[MembershipSource] = mapped_column(
        Enum(MembershipSource, name="membership_source"), nullable=False
    )
    external_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship(back_populates="memberships")

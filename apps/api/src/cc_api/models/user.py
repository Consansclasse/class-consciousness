# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle User — identité d'un adhérent ou contact.

Email unique. Soft-delete (`deleted_at`) pour RGPD.
Une absence d'utilisateur (visiteur anonyme) n'apparaît PAS dans cette table —
le rate-limiting niveau 0 se fait par IP côté Redis.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.membership import Membership


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Horodatage du consentement RGPD obligatoire pour l'adhésion — preuve
    # exigée par la CNIL en cas de contrôle (cf. guide RGPD associations).
    consent_data_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Consentement newsletter séparé — opt-in non pré-coché obligatoire.
    consent_newsletter_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    memberships: Mapped[list[Membership]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )

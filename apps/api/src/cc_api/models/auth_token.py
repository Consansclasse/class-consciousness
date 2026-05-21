# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle AuthToken — token email à usage unique (vérification / réinitialisation).

Le token brut (32 octets) est envoyé par email ; seul son hash sha256 est stocké
en base. Une fuite de la table ne révèle pas les tokens actifs.

`purpose` distingue les usages : confirmer l'adresse à l'inscription
(`VERIFY_EMAIL`) ou réinitialiser le mot de passe (`RESET_PASSWORD`). La
consommation vérifie toujours le purpose attendu — un token de reset ne peut pas
servir à vérifier un email et inversement.

Cycle de vie : created (used_at=NULL) → consumed (used_at=now()). Un token
consommé ne peut pas être réutilisé. Le hash est unique → empêche les collisions.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.user import User


class TokenPurpose(str, enum.Enum):  # noqa: UP042 — préserve compat Alembic/Postgres ENUM
    """Usage d'un AuthToken — borne ce qu'il peut consommer."""

    VERIFY_EMAIL = "VERIFY_EMAIL"
    RESET_PASSWORD = "RESET_PASSWORD"  # noqa: S105 — nom d'usage, pas un secret


class AuthToken(Base):
    __tablename__ = "auth_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    purpose: Mapped[TokenPurpose] = mapped_column(
        Enum(TokenPurpose, name="token_purpose"), nullable=False, index=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped[User] = relationship()

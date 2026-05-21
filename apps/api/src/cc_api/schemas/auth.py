# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas de l'authentification par magic-link."""

from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field

from cc_api.schemas.corpus import _CamelModel


class MagicLinkRequest(BaseModel):
    """Demande d'un lien de connexion."""

    email: EmailStr


class VerifyRequest(BaseModel):
    """Vérification d'un magic-link — le token brut reçu par email."""

    token: str = Field(min_length=10, max_length=200)


class UserOut(_CamelModel):
    """Utilisateur de la session — exposé par /auth/verify et /auth/me."""

    id: int
    email: str
    display_name: str | None

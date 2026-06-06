# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas de l'authentification par mot de passe.

Inscription (email + mot de passe + consentement RGPD) → email de vérification →
connexion par mot de passe. Réinitialisation par email. Pas de magic-link.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from cc_api.schemas.corpus import _CamelModel

# Politique de mot de passe : 10 caractères minimum (longueur > complexité, cf.
# NIST SP 800-63B), borne haute pour éviter les payloads abusifs avant hachage.
_Password = Field(min_length=10, max_length=200)
_Token = Field(min_length=10, max_length=200)


class RegisterRequest(BaseModel):
    """Inscription — crée un compte non vérifié et déclenche l'email de confirmation."""

    email: EmailStr
    password: str = _Password
    display_name: str | None = Field(default=None, max_length=255)
    # Consentement RGPD obligatoire et non pré-coché : Literal[True] rejette
    # `false`/absent en 422 (preuve de consentement exigée par la CNIL).
    consent_data: Literal[True]
    consent_newsletter: bool = False


class LoginRequest(BaseModel):
    """Connexion par email + mot de passe."""

    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class EmailVerifyRequest(BaseModel):
    """Confirmation d'adresse — le token reçu par email à l'inscription."""

    token: str = _Token


class ForgotPasswordRequest(BaseModel):
    """Demande de réinitialisation — déclenche l'email de reset si le compte existe."""

    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Réinitialisation — nouveau mot de passe + token reçu par email."""

    token: str = _Token
    password: str = _Password


class UpdateProfileRequest(BaseModel):
    """Édition du profil de l'utilisateur connecté (POST /auth/profile)."""

    display_name: str | None = Field(default=None, max_length=255)


class ChangePasswordRequest(BaseModel):
    """Changement de mot de passe d'un utilisateur connecté (POST /auth/change-password).

    Exige le mot de passe actuel (ré-authentification) ; le nouveau respecte la
    même politique que l'inscription.
    """

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = _Password


class UserOut(_CamelModel):
    """Utilisateur de la session — exposé par /auth/login, /auth/verify-email, /auth/me."""

    id: int
    email: str
    display_name: str | None
    email_verified_at: datetime | None = None
    created_at: datetime

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /auth — authentification par email + mot de passe.

Flux : POST /auth/register (email, mot de passe, consentement) → email de
confirmation → POST /auth/verify-email (token) active le compte ET ouvre la
session → POST /auth/login (email, mot de passe) ouvre la session →
GET /auth/me lit la session, POST /auth/logout la ferme.
Réinitialisation : POST /auth/forgot-password → email → POST /auth/reset-password.

Les réponses de /register et /forgot-password sont volontairement génériques :
on ne révèle jamais si une adresse a déjà un compte. En dev (SMTP non
configuré), le lien est renvoyé dans `devLink` pour faciliter les essais.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from cc_api.clients.db import get_session_maker
from cc_api.core.deps import current_user
from cc_api.core.logging import get_logger
from cc_api.core.ratelimit import limiter
from cc_api.models.user import User
from cc_api.schemas.auth import (
    EmailVerifyRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResetPasswordRequest,
    UserOut,
)
from cc_api.services.auth import (
    AuthError,
    authenticate,
    register,
    request_password_reset,
    reset_password,
    verify_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)


def _generic_sent(link: str | None) -> dict[str, str]:
    """Réponse générique (pas d'oracle d'énumération) ; lien exposé en dev seul."""
    out = {"status": "sent"}
    if link is not None:
        out["devLink"] = link
    return out


@router.post("/register")
@limiter.limit("5/minute")
async def post_register(request: Request, payload: RegisterRequest) -> dict[str, str]:
    """Inscrit un compte et envoie l'email de confirmation (réponse générique)."""
    try:
        async with get_session_maker()() as session:
            link = await register(
                session,
                email=payload.email,
                password=payload.password,
                display_name=payload.display_name,
                consent_newsletter=payload.consent_newsletter,
            )
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _generic_sent(link)


@router.post("/verify-email", response_model=UserOut)
@limiter.limit("10/minute")
async def post_verify_email(request: Request, payload: EmailVerifyRequest) -> UserOut:
    """Confirme l'adresse, active le compte et ouvre la session."""
    async with get_session_maker()() as session:
        try:
            user = await verify_email(session, payload.token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        request.session["user_id"] = user.id
        log.info("auth.session_opened", user_id=user.id, via="verify_email")
        return _user_out(user)


@router.post("/login", response_model=UserOut)
@limiter.limit("10/minute")
async def post_login(request: Request, payload: LoginRequest) -> UserOut:
    """Connexion par email + mot de passe — ouvre la session."""
    async with get_session_maker()() as session:
        try:
            user = await authenticate(session, payload.email, payload.password)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        request.session["user_id"] = user.id
        log.info("auth.session_opened", user_id=user.id, via="password")
        return _user_out(user)


@router.post("/forgot-password")
@limiter.limit("5/minute")
async def post_forgot_password(
    request: Request, payload: ForgotPasswordRequest
) -> dict[str, str]:
    """Envoie un email de réinitialisation si le compte existe (réponse générique)."""
    try:
        async with get_session_maker()() as session:
            link = await request_password_reset(session, payload.email)
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return _generic_sent(link)


@router.post("/reset-password")
@limiter.limit("10/minute")
async def post_reset_password(
    request: Request, payload: ResetPasswordRequest
) -> dict[str, str]:
    """Choisit un nouveau mot de passe à partir d'un token de réinitialisation."""
    async with get_session_maker()() as session:
        try:
            await reset_password(session, payload.token, payload.password)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
    return {"status": "reset"}


@router.post("/logout")
async def logout(request: Request) -> dict[str, str]:
    """Ferme la session courante."""
    request.session.clear()
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(current_user)]) -> UserOut:
    """Renvoie l'utilisateur de la session — 401 si la requête n'est pas authentifiée."""
    return _user_out(user)

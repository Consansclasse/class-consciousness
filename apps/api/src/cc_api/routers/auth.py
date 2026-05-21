# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /auth — authentification par magic-link, sans mot de passe.

Flux : POST /auth/request-link (email) → lien envoyé par email →
POST /auth/verify (token) consomme le lien et ouvre la session →
GET /auth/me lit la session, POST /auth/logout la ferme.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from cc_api.clients.db import get_session_maker
from cc_api.core.deps import current_user
from cc_api.core.logging import get_logger
from cc_api.core.ratelimit import limiter
from cc_api.models.user import User
from cc_api.schemas.auth import MagicLinkRequest, UserOut, VerifyRequest
from cc_api.services.auth import AuthError, request_magic_link, verify_magic_link

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)


@router.post("/request-link")
@limiter.limit("5/minute")
async def request_link(request: Request, payload: MagicLinkRequest) -> dict[str, str]:
    """Envoie un magic-link à l'adresse fournie.

    La réponse est identique que l'adresse ait déjà un compte ou non — on ne
    révèle pas qui est inscrit. En dev (SMTP non configuré), le lien est renvoyé
    dans `devMagicLink` pour faciliter les essais locaux.
    """
    try:
        async with get_session_maker()() as session:
            link = await request_magic_link(session, payload.email)
    except AuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    out = {"status": "sent"}
    if link is not None:
        out["devMagicLink"] = link
    return out


@router.post("/verify", response_model=UserOut)
@limiter.limit("10/minute")
async def verify(request: Request, payload: VerifyRequest) -> UserOut:
    """Consomme un magic-link et ouvre la session de l'utilisateur."""
    async with get_session_maker()() as session:
        try:
            user = await verify_magic_link(session, payload.token)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        request.session["user_id"] = user.id
        log.info("auth.session_opened", user_id=user.id)
        return _user_out(user)


@router.post("/logout")
async def logout(request: Request) -> dict[str, str]:
    """Ferme la session courante."""
    request.session.clear()
    return {"status": "logged_out"}


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(current_user)]) -> UserOut:
    """Renvoie l'utilisateur de la session — 401 si la requête n'est pas authentifiée."""
    return _user_out(user)

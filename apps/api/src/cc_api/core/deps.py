# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dépendances FastAPI partagées — injection de l'utilisateur courant.

`current_user` exige une session valide (401 sinon) ; `current_user_optional`
renvoie None pour un visiteur anonyme. La session est portée par un cookie
signé (SessionMiddleware) où `/auth/verify` pose `user_id`.
"""

from __future__ import annotations

from fastapi import HTTPException, Request

from cc_api.clients.db import get_session_maker
from cc_api.models.user import User


async def current_user_optional(request: Request) -> User | None:
    """Utilisateur de la session, ou None si anonyme ou compte supprimé."""
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    async with get_session_maker()() as session:
        user = await session.get(User, user_id)
    if user is None or user.deleted_at is not None:
        return None
    return user


async def current_user(request: Request) -> User:
    """Utilisateur de la session — lève 401 si la requête n'est pas authentifiée."""
    user = await current_user_optional(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentification requise")
    return user

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Garde-fous sécurité partagés.

`require_dev` : utilisé comme `Depends(require_dev)` sur les routes dev-only
(`/__debug/*`, `/admin/ingest`). Refuse l'accès si `CC_API_ENV != "dev"`.

Hachage de mot de passe : Argon2id (recommandation OWASP, lauréat du Password
Hashing Competition), paramètres par défaut d'`argon2-cffi`. Seul le hash (sel
+ paramètres inclus) est stocké, jamais le mot de passe.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, status

from cc_api.core.settings import settings

_hasher = PasswordHasher()


def require_dev() -> None:
    """Refuse l'accès si on n'est pas en environnement dev."""
    if not settings.is_dev:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"endpoint disabled (CC_API_ENV={settings.env})",
        )


def hash_password(password: str) -> str:
    """Renvoie le hash Argon2id (sel aléatoire intégré) à stocker."""
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Vérifie un mot de passe contre son hash — temps quasi constant.

    Renvoie False (jamais d'exception) sur non-correspondance ou hash illisible :
    l'appelant traite l'échec d'authentification de façon uniforme, sans révéler
    si c'est l'email ou le mot de passe qui est faux.
    """
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False

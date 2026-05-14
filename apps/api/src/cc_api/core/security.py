# SPDX-License-Identifier: AGPL-3.0-or-later
"""Garde-fous sécurité partagés.

`require_dev` : utilisé comme `Depends(require_dev)` sur les routes dev-only
(`/__debug/*`, `/admin/ingest`). Refuse l'accès si `CC_API_ENV != "dev"`.
"""

from __future__ import annotations

from fastapi import HTTPException, status

from cc_api.core.settings import settings


def require_dev() -> None:
    """Refuse l'accès si on n'est pas en environnement dev."""
    if not settings.is_dev:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"endpoint disabled (CC_API_ENV={settings.env})",
        )

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Atelier — export « 1-clic » d'un document vers Notion.

Le front construit les blocs Notion (titres, paragraphes, citations en liens) et
les POST ici. Ce routeur détient le token d'intégration Notion (jamais exposé au
navigateur) et crée la page via l'API Notion. Aucun appel LLM → ni quota ni
facturation, seulement l'authentification.

Notion limite chaque tableau (dont `children`) à 100 éléments par requête : on
crée la page avec les 100 premiers blocs puis on AJOUTE le reste par lots de 100
(`PATCH /blocks/{id}/children`) — pas de troncature silencieuse.
"""

from __future__ import annotations

from typing import Annotated, Any

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from cc_api.core.deps import current_user
from cc_api.core.ratelimit import limiter
from cc_api.core.settings import settings
from cc_api.models import User

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/atelier", tags=["atelier"])

_NOTION_BASE = "https://api.notion.com/v1"
# Notion : 100 éléments max par tableau (children / rich_text…).
_MAX_CHILDREN = 100


class NotionExportRequest(BaseModel):
    """Document à pousser : titre + blocs Notion déjà formés par le front."""

    title: str = Field(min_length=1, max_length=200)
    # Borne de robustesse (le front n'envoie jamais autant) — évite un POST géant.
    children: list[dict[str, Any]] = Field(default_factory=list, max_length=2000)


class NotionExportResponse(BaseModel):
    url: str
    id: str


def _notion_detail(resp: httpx.Response) -> str:
    """Message lisible à partir d'une réponse Notion en erreur (jamais le token
    ni les en-têtes — seulement le champ `message` renvoyé par Notion)."""
    msg: object = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            msg = body.get("message")
    except ValueError:
        msg = None
    prefix = (
        "Notion a refusé la requête" if resp.status_code < 500 else "Notion en erreur"
    )
    return f"{prefix} ({resp.status_code})" + (f" : {str(msg)[:300]}" if msg else "")


@router.post("/notion", response_model=NotionExportResponse)
@limiter.limit("20/minute")
async def export_to_notion(
    request: Request,
    payload: NotionExportRequest,
    user: Annotated[User, Depends(current_user)],
) -> NotionExportResponse:
    """Crée une page Notion (enfant de la page configurée) depuis le document."""
    if not settings.notion_token or not settings.notion_parent_page_id:
        raise HTTPException(
            status_code=503,
            detail=(
                "Export Notion non configuré : définir NOTION_TOKEN et "
                "NOTION_PARENT_PAGE_ID côté serveur."
            ),
        )

    children = payload.children
    headers = {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": settings.notion_version,
        "Content-Type": "application/json",
    }
    create_body: dict[str, Any] = {
        "parent": {"type": "page_id", "page_id": settings.notion_parent_page_id},
        "properties": {"title": {"title": [{"text": {"content": payload.title}}]}},
        "children": children[:_MAX_CHILDREN],
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{_NOTION_BASE}/pages", json=create_body, headers=headers
            )
            if resp.status_code >= 400:
                log.warning(
                    "atelier.notion_error",
                    status=resp.status_code,
                    body=resp.text[:500],
                )
                raise HTTPException(status_code=502, detail=_notion_detail(resp))
            data = resp.json()
            page_id = str(data.get("id", ""))

            # Blocs au-delà de 100 : ajout par lots (PATCH append).
            rest = children[_MAX_CHILDREN:]
            for i in range(0, len(rest), _MAX_CHILDREN):
                chunk = rest[i : i + _MAX_CHILDREN]
                appended = await client.patch(
                    f"{_NOTION_BASE}/blocks/{page_id}/children",
                    json={"children": chunk},
                    headers=headers,
                )
                if appended.status_code >= 400:
                    log.warning(
                        "atelier.notion_append_error",
                        status=appended.status_code,
                        body=appended.text[:500],
                    )
                    raise HTTPException(
                        status_code=502,
                        detail=(
                            "Page Notion créée mais une partie du contenu n'a pas "
                            "pu être ajoutée — réessaie. " + _notion_detail(appended)
                        ),
                    )
    except httpx.HTTPError as exc:
        log.warning("atelier.notion_unreachable", error=str(exc))
        raise HTTPException(status_code=502, detail="Notion injoignable.") from exc

    log.info(
        "atelier.notion_exported",
        user_id=user.id,
        page_id=page_id,
        n_blocks=len(children),
    )
    return NotionExportResponse(url=str(data.get("url", "")), id=page_id)

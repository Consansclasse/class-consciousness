# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /conversations — historique des fils de l'assistant RAG.

Toutes les routes exigent une session (401 sinon) et n'exposent que les fils du
demandeur (404 sur un fil d'autrui — on ne révèle pas son existence) :

- GET    /conversations            liste latérale (récents d'abord)
- POST   /conversations            crée un fil vide
- GET    /conversations/{id}       fil complet (messages réaffichables)
- PATCH  /conversations/{id}       renomme
- DELETE /conversations/{id}       supprime (soft-delete)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from cc_api.clients.db import get_session_maker
from cc_api.core.deps import current_user
from cc_api.core.logging import get_logger
from cc_api.models.rag_interaction import RagInteraction
from cc_api.models.user import User
from cc_api.schemas.conversation import (
    ConversationDetail,
    ConversationMessage,
    ConversationSummary,
    RenameRequest,
)
from cc_api.schemas.qa import Citation, Sentence
from cc_api.services import conversation as conv_service

router = APIRouter(prefix="/conversations", tags=["conversations"])
log = get_logger(__name__)


def _message(row: RagInteraction) -> ConversationMessage:
    """Sérialise une interaction persistée en message réaffichable."""
    return ConversationMessage(
        interaction_id=row.id,
        question=row.question,
        answer=row.answer,
        sentences=[Sentence.model_validate(s) for s in row.sentences],
        cited_chunks=[Citation.model_validate(c) for c in row.cited_chunks],
        incomplete=row.incomplete,
        refused_reason=row.refused_reason,
        created_at=row.created_at,
    )


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    user: Annotated[User, Depends(current_user)],
) -> list[ConversationSummary]:
    """Liste des fils de l'utilisateur, du plus récemment actif au plus ancien."""
    async with get_session_maker()() as session:
        convs = await conv_service.list_for_user(session, user.id)
    return [
        ConversationSummary(id=c.id, title=c.title, updated_at=c.updated_at)
        for c in convs
    ]


@router.post("", response_model=ConversationSummary, status_code=201)
async def create_conversation(
    user: Annotated[User, Depends(current_user)],
) -> ConversationSummary:
    """Crée un fil vide et renvoie son résumé."""
    async with get_session_maker()() as session:
        conv = await conv_service.create_empty(session, user.id)
        return ConversationSummary(
            id=conv.id, title=conv.title, updated_at=conv.updated_at
        )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: int,
    user: Annotated[User, Depends(current_user)],
) -> ConversationDetail:
    """Fil complet : titre + messages ordonnés, prêts à réafficher."""
    async with get_session_maker()() as session:
        conv = await conv_service.get_owned(session, conversation_id, user.id)
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation introuvable")
        rows = await conv_service.messages_for(session, conv.id)
        title = conv.title
    return ConversationDetail(
        id=conversation_id,
        title=title,
        messages=[_message(r) for r in rows],
    )


@router.patch("/{conversation_id}", response_model=ConversationSummary)
async def rename_conversation(
    conversation_id: int,
    payload: RenameRequest,
    user: Annotated[User, Depends(current_user)],
) -> ConversationSummary:
    """Renomme un fil possédé. 404 si le fil n'appartient pas à l'utilisateur."""
    async with get_session_maker()() as session:
        conv = await conv_service.rename(
            session, conversation_id, user.id, payload.title
        )
        if conv is None:
            raise HTTPException(status_code=404, detail="conversation introuvable")
        return ConversationSummary(
            id=conv.id, title=conv.title, updated_at=conv.updated_at
        )


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: int,
    user: Annotated[User, Depends(current_user)],
) -> None:
    """Supprime (soft-delete) un fil possédé. 404 sinon."""
    async with get_session_maker()() as session:
        ok = await conv_service.soft_delete(session, conversation_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="conversation introuvable")
    log.info("conversation.deleted", conversation_id=conversation_id)

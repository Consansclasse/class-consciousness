# SPDX-License-Identifier: AGPL-3.0-or-later
"""Service des conversations — logique métier des fils de l'assistant RAG.

Un fil regroupe les `RagInteraction` d'un utilisateur (historique latéral). Ce
module concentre la résolution/création d'un fil au moment d'une question, et le
CRUD exposé par `routers/conversations.py`. Toutes les fonctions vérifient la
propriété : un utilisateur ne touche jamais le fil d'un autre.

Le RAG reste mono-tour : aucun contexte inter-questions n'est injecté ici. Le
fil est un regroupement de persistance et d'affichage.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.models.conversation import Conversation
from cc_api.models.rag_interaction import RagInteraction

# Longueur du titre auto-dérivé de la première question (avant troncature avec
# ellipse). La colonne accepte 200 caractères ; on titre plus court pour rester
# lisible dans la liste latérale.
_TITLE_MAX = 80


def derive_title(question: str) -> str:
    """Titre lisible dérivé d'une question — première ligne, tronquée à `_TITLE_MAX`."""
    cleaned = " ".join(question.strip().split())
    if len(cleaned) <= _TITLE_MAX:
        return cleaned or "Nouvelle conversation"
    return cleaned[: _TITLE_MAX - 1].rstrip() + "…"


async def get_owned(
    session: AsyncSession, conversation_id: int, user_id: int
) -> Conversation | None:
    """Renvoie le fil s'il appartient à l'utilisateur et n'est pas supprimé."""
    conv = await session.get(Conversation, conversation_id)
    if conv is None or conv.user_id != user_id or conv.deleted_at is not None:
        return None
    return conv


async def resolve_for_message(
    session: AsyncSession,
    user_id: int,
    conversation_id: int | None,
    question: str,
) -> Conversation:
    """Résout le fil d'une nouvelle question : le fil fourni (s'il appartient à
    l'utilisateur), sinon un fil neuf titré d'après la question.

    Tolérant par conception : un `conversation_id` inconnu ou appartenant à
    autrui n'est pas une erreur (la réponse est déjà calculée au moment de la
    persistance) — on ouvre un nouveau fil. La propriété reste garantie : on ne
    rattache jamais à un fil d'autrui.
    """
    if conversation_id is not None:
        conv = await get_owned(session, conversation_id, user_id)
        if conv is not None:
            return conv
    conv = Conversation(user_id=user_id, title=derive_title(question))
    session.add(conv)
    await session.flush()
    return conv


async def touch(session: AsyncSession, conversation_id: int) -> None:
    """Met à jour `updated_at` du fil (remonte en tête de liste)."""
    await session.execute(
        update(Conversation)
        .where(Conversation.id == conversation_id)
        .values(updated_at=datetime.now(UTC))
    )


async def list_for_user(
    session: AsyncSession, user_id: int
) -> list[Conversation]:
    """Fils non supprimés de l'utilisateur, du plus récemment actif au plus ancien."""
    result = await session.execute(
        select(Conversation)
        .where(Conversation.user_id == user_id, Conversation.deleted_at.is_(None))
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
    )
    return list(result.scalars().all())


async def messages_for(
    session: AsyncSession, conversation_id: int
) -> list[RagInteraction]:
    """Interactions d'un fil, ordonnées chronologiquement (réaffichage)."""
    result = await session.execute(
        select(RagInteraction)
        .where(RagInteraction.conversation_id == conversation_id)
        .order_by(RagInteraction.created_at, RagInteraction.id)
    )
    return list(result.scalars().all())


async def rename(
    session: AsyncSession, conversation_id: int, user_id: int, title: str
) -> Conversation | None:
    """Renomme un fil possédé. None si le fil n'appartient pas à l'utilisateur."""
    conv = await get_owned(session, conversation_id, user_id)
    if conv is None:
        return None
    conv.title = title
    await session.commit()
    return conv


async def soft_delete(
    session: AsyncSession, conversation_id: int, user_id: int
) -> bool:
    """Marque un fil possédé comme supprimé. False si introuvable/non possédé."""
    conv = await get_owned(session, conversation_id, user_id)
    if conv is None:
        return False
    conv.deleted_at = func.now()
    await session.commit()
    return True


async def create_empty(session: AsyncSession, user_id: int) -> Conversation:
    """Crée un fil vide (bouton « Nouvelle conversation »)."""
    conv = Conversation(user_id=user_id, title="Nouvelle conversation")
    session.add(conv)
    await session.commit()
    return conv

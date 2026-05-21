# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle Conversation — fil d'échanges d'un utilisateur avec l'assistant RAG.

Une conversation regroupe les `RagInteraction` d'un même fil (au sens de
l'historique latéral, façon Claude/Gemini). Chaque interaction porte son
`conversation_id` ; la conversation porte le titre lisible (dérivé de la
première question) et `updated_at` (date du dernier message — tri de la liste).

Le RAG reste mono-tour : chaque réponse est ancrée indépendamment dans le
corpus, sans mémoire inter-questions. La conversation est un regroupement
d'affichage et de persistance, pas un contexte injecté au modèle.

Confidentialité : un fil appartient à un compte (`user_id`, CASCADE). Le
soft-delete (`deleted_at`) masque le fil sans casser les `RagInteraction`
rattachées (qui restent pour l'observabilité).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from cc_api.models.base import Base


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Titre lisible — dérivé de la première question (tronqué). Jamais NULL :
    # une conversation fraîche reçoit un titre provisoire dès sa création.
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Horodatage du dernier message — clé de tri de la liste latérale. Mis à
    # jour à chaque interaction rattachée.
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Soft-delete : un fil supprimé disparaît de la liste sans perdre ses
    # interactions (analytics, closed-loop).
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

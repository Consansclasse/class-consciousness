# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle RagFeedback — retour d'un lecteur sur une réponse de l'assistant.

Un feedback se rattache à une `RagInteraction`. Il ferme la boucle humaine du
closed-loop : pouce haut/bas pour l'appréciation globale, signalement (`FLAG`)
pour une citation ou une affirmation contestée — le cas le plus précieux pour
corriger ensuite le pipeline ou le corpus.

Plusieurs feedbacks par interaction sont permis (aucune contrainte d'unicité).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from cc_api.models.base import Base


class RagFeedbackKind(str, enum.Enum):  # noqa: UP042 — préserve compat Alembic/Postgres ENUM
    """Nature du retour d'un lecteur sur une réponse RAG."""

    UP = "UP"  # réponse jugée utile
    DOWN = "DOWN"  # réponse jugée inutile
    FLAG = "FLAG"  # citation ou affirmation contestée — à examiner


class RagFeedback(Base):
    __tablename__ = "rag_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Interaction notée. CASCADE : purger une interaction emporte ses feedbacks.
    rag_interaction_id: Mapped[int] = mapped_column(
        ForeignKey("rag_interactions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[RagFeedbackKind] = mapped_column(
        Enum(RagFeedbackKind, name="rag_feedback_kind"), nullable=False
    )
    # Renseigné surtout pour un signalement (FLAG) ; optionnel pour un vote.
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SHA-256 de l'IP — anti-abus léger, jamais l'IP en clair.
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

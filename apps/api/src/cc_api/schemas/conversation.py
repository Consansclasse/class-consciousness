# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic des conversations (historique de l'assistant RAG).

`ConversationSummary` : ligne de la liste latérale (id, titre, date).
`ConversationMessage` : un échange du fil, réplique exactement la forme d'une
`QaResponse` côté client — le front réaffiche l'historique avec le même rendu.
`ConversationDetail` : un fil complet (titre + messages ordonnés).
`RenameRequest` : renommage d'un fil.

Tous sérialisés en camelCase via `_CamelModel`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from cc_api.schemas.corpus import _CamelModel
from cc_api.schemas.qa import Citation, Sentence


class ConversationSummary(_CamelModel):
    """Vue compacte pour la liste latérale — triée par `updatedAt` décroissant."""

    id: int
    title: str
    updated_at: datetime


class ConversationMessage(_CamelModel):
    """Un échange persisté d'un fil, réaffichable à l'identique.

    Mêmes champs utiles que `QaResponse` : le client réutilise son moteur de
    rendu (phrases vérifiées + appareil de sources, ou note de refus).
    """

    interaction_id: int
    question: str
    answer: str | None
    sentences: list[Sentence]
    cited_chunks: list[Citation]
    incomplete: bool
    refused_reason: str | None
    created_at: datetime


class ConversationDetail(_CamelModel):
    """Fil complet : métadonnées + messages ordonnés chronologiquement."""

    id: int
    title: str
    messages: list[ConversationMessage]


class RenameRequest(BaseModel):
    """Renommage d'un fil — titre 1..200 caractères."""

    title: str = Field(min_length=1, max_length=200)

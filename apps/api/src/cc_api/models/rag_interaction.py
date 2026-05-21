# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle RagInteraction — trace persistée de chaque requête à l'assistant RAG.

Chaque appel à `/qa` ou `/qa/stream` produit une ligne : question, réponse (ou
refus), verdicts d'ancrage par phrase, latences par étape, tokens consommés.

Pourquoi persister : sans cette table, une interaction RAG ne laisse qu'une
traînée de logs JSON dispersés, inexploitable. La table rend l'historique RAG
*interrogeable* — taux de refus, passages les plus cités, dérive de la qualité,
coût — socle de l'observabilité et de l'amélioration continue du pipeline.

Confidentialité : `user_id` reste NULL tant que l'authentification n'existe pas ;
les requêtes anonymes sont rattachées à `ip_hash` (SHA-256 de l'IP, jamais l'IP
en clair).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from cc_api.models.base import Base


class RagInteraction(Base):
    __tablename__ = "rag_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # Demandeur. `user_id` reste NULL jusqu'à l'authentification ; un compte
    # supprimé détache ses interactions (SET NULL) sans les perdre — la donnée
    # analytique survit. Les anonymes ne sont identifiés que par `ip_hash`.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ip_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Fil de conversation auquel l'interaction appartient. NULL pour les lignes
    # historiques antérieures aux conversations (et, en pratique, jamais NULL
    # depuis le verrouillage du chat par compte). SET NULL : supprimer un fil ne
    # détruit pas la trace analytique. La purge de rétention n'efface QUE les
    # lignes `conversation_id IS NULL` — l'historique d'un compte est permanent.
    conversation_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Question posée et issue de la requête.
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    incomplete: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # None si la réponse a abouti ; sinon la clé canonique du refus
    # (no_chunks_retrieved | no_relevant_chunks | unverified_citations).
    refused_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    model: Mapped[str] = mapped_column(String(128), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    # Trace structurée, sérialisée depuis le RagResult du pipeline.
    latencies: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    # {generation: {input_tokens, …, model}, judge: {…, model}} — détaillé par
    # appel LLM : génération et juge tournent sur des modèles tarifés
    # différemment. Le coût se dérive des tokens ; il n'est pas figé ici (un
    # prix figé deviendrait faux au prochain changement de tarif).
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Une entrée par phrase : texte, verdict, citations, verified, paragraphe…
    sentences: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    cited_source_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # Appareil de sources complet (auteur, titre, ARK, offsets, texte cité) tel
    # que renvoyé au client — sérialisé depuis les chunks rerankés. Permet de
    # réafficher un fil d'historique À L'IDENTIQUE : `cited_source_ids` seul ne
    # suffit pas (il faudrait re-résoudre les chunks dans Qdrant). Liste vide
    # pour un refus.
    cited_chunks: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    retrieval_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rerank_count: Mapped[int] = mapped_column(Integer, nullable=False)

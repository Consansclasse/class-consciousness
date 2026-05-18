# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic du pipeline RAG `/qa`.

`QaRequest` : payload d'entrée — question utilisateur.
`Citation` : chunk source utilisé pour assembler la réponse (avec offsets
caractères, ARK article, source_id canonique).
`Sentence` : une phrase de la réponse + son verdict de vérification de citation.
`QaResponse` : réponse complète, sérialisée en camelCase pour l'API.

Tous les champs sont sérialisés en camelCase via `_CamelModel` (cf. schemas.corpus).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cc_api.schemas.corpus import _CamelModel


class QaRequest(BaseModel):
    """Question utilisateur — bornes : 3..500 caractères."""

    question: str = Field(min_length=3, max_length=500)


class Citation(_CamelModel):
    """Chunk source utilisé pour ancrer une phrase de la réponse."""

    source_id: str  # `{issue_slug}/{article_slug}:{chunk_idx}`
    issue_slug: str
    issue_ark: str
    article_slug: str
    article_ark: str
    article_title: str
    author_name: str
    chunk_idx: int
    char_start: int
    char_end: int
    quoted_text: str  # texte intégral du chunk source
    retrieval_score: float
    rerank_score: float


class Sentence(_CamelModel):
    """Une phrase de la réponse RAG + son verdict de vérification d'ancrage.

    `verdict` est le verdict canonique parmi {`SUPPORTED`, `QUOTE_UNVERIFIED`,
    `NOT_SUPPORTED`, `CONTRADICTED`, `UNSOURCED`, `REFUSED_BY_LLM`}.
    `verified` est `True` pour `SUPPORTED` (ancrage vérifié : citations directes
    littérales OK + juge sémantique ENTAILED) et pour `REFUSED_BY_LLM` (refus
    explicite légitime via `[CITE:none]`).
    """

    text: str
    citations: list[str]  # source_ids cités
    verdict: str
    verified: bool
    paragraphe: int  # index du paragraphe d'origine — regroupement à l'affichage
    best_score: float  # 0..100, meilleur match littéral des citations directes
    reason: str  # explication humaine du verdict


class QaResponse(_CamelModel):
    """Réponse `/qa`.

    Cas possibles :
    - `answer` non nul + `incomplete=False` + `refusedReason=None` : succès complet.
    - `answer` non nul + `incomplete=True` + `refusedReason=None` : succès PARTIEL.
      Seules les phrases vérifiées (et les refus explicites du LLM) sont exposées
      dans `answer`. `droppedSentences` liste les phrases retirées et `sentences`
      contient les verdicts de toutes (verified + dropped) pour debug.
    - `answer=null` + `refusedReason != None` : refus complet (HTTP 422).
    """

    question: str
    answer: str | None
    sentences: list[Sentence]
    cited_chunks: list[Citation]
    refused_reason: str | None  # None si succès ; sinon raison du refus (clé canonique)
    refused_sentences: list[str] = Field(default_factory=list)
    incomplete: bool = False
    dropped_sentences: list[str] = Field(default_factory=list)
    latency_ms: int
    model: str
    retrieval_count: int  # nb chunks Qdrant top-k retournés (avant rerank)
    rerank_count: int  # nb chunks gardés après rerank (= taille de cited_chunks)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic v2 du corpus.

Sérialisation : alias camelCase pour s'aligner sur `apps/web/src/pages/corpus.astro`
(qui attend `title`, `author`, `insertedAt`). Construire avec noms Python snake_case ;
exporter via `model_dump(by_alias=True)` ou response_model FastAPI.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _CamelModel(BaseModel):
    """Base pour les schemas sérialisés en camelCase côté JSON."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class AuthorOut(_CamelModel):
    id: int
    display_name: str
    viaf_id: str | None = None
    idref_id: str | None = None
    wikidata_id: str | None = None
    birth_year: int | None = None
    death_year: int | None = None
    created_at: datetime


class WorkSummary(_CamelModel):
    """Vue compacte pour la liste `/corpus`."""

    title: str
    author: str
    inserted_at: datetime


class WorkOut(_CamelModel):
    """Vue détaillée pour `/corpus/{work_id}`."""

    id: int
    ark: str
    title: str
    author: AuthorOut
    published_date: date | None = None
    source_url: str | None = None
    license: str
    sha256: str
    inserted_at: datetime
    n_chunks: int


class ChunkOut(_CamelModel):
    id: int
    work_id: int
    idx: int
    text: str
    char_start: int
    char_end: int
    token_count: int
    embedding_model: str
    qdrant_point_id: uuid.UUID


class IngestRequest(BaseModel):
    """Payload POST /admin/ingest — path absolu lisible côté API."""

    path: str = Field(min_length=1, description="Chemin absolu vers le fichier TEI à ingérer")


class IngestResult(_CamelModel):
    """Réponse POST /admin/ingest — résumé d'une ingestion."""

    work_id: int
    ark: str
    n_chunks: int
    duration_ms: int
    was_duplicate: bool = False


class CorpusPage(_CamelModel):
    """Page paginée de works."""

    items: list[WorkSummary]
    page: int
    size: int
    total: int

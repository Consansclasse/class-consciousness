# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic v2 du corpus.

Hiérarchie : IssueSummary (liste /corpus) → IssueDetail (/corpus/{slug})
contenant ArticleSummary → ArticleDetail (/corpus/{issue}/{article}) avec body.

Sérialisation : alias camelCase pour s'aligner sur `apps/web/src/pages/corpus.astro`.
"""

from __future__ import annotations

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


class ArticleSummary(_CamelModel):
    """Vue compacte pour la liste des articles d'un numéro."""

    slug: str
    title: str
    author: str
    idx_in_issue: int


class ArticleDetail(_CamelModel):
    """Article complet avec body reconstitué depuis les chunks."""

    id: int
    slug: str
    ark: str
    title: str
    author: AuthorOut
    idx_in_issue: int
    page_start: int | None = None
    page_end: int | None = None
    n_paragraphs: int
    paragraphs: list[str]


class IssueSummary(_CamelModel):
    """Vue compacte pour la liste `/corpus`."""

    slug: str
    journal_title: str
    issue_number: int | None
    title: str
    published_date: date | None
    inserted_at: datetime
    n_articles: int


class IssueDetail(_CamelModel):
    """Issue complète avec ses articles (sans le body)."""

    id: int
    slug: str
    ark: str
    journal_title: str
    issue_number: int | None
    title: str
    published_date: date | None
    license: str
    source_desc: str
    sha256: str
    inserted_at: datetime
    articles: list[ArticleSummary]


class CorpusPage(_CamelModel):
    """Page paginée de numéros."""

    items: list[IssueSummary]
    page: int
    size: int
    total: int


class IngestRequest(BaseModel):
    """Payload POST /admin/ingest — path absolu lisible côté API."""

    path: str = Field(min_length=1, description="Chemin absolu vers le fichier TEI à ingérer")


class IngestResult(_CamelModel):
    """Réponse POST /admin/ingest — résumé d'une ingestion d'issue."""

    issue_id: int
    slug: str
    ark: str
    n_articles: int
    n_chunks: int
    duration_ms: int
    was_duplicate: bool = False

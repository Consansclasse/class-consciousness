# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /corpus — hiérarchie Issue → Article.

Routes :
- GET /corpus → liste paginée d'IssueSummary
- GET /corpus/{issue_slug} → IssueDetail avec liste d'ArticleSummary
- GET /corpus/{issue_slug}/{article_slug} → ArticleDetail avec paragraphes
- POST /admin/ingest (dev only) → ingère 1 TEI hiérarchique
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from cc_api.clients.db import get_session_maker
from cc_api.core.logging import get_logger
from cc_api.core.security import require_dev
from cc_api.models import Article, Chunk, Issue
from cc_api.schemas import (
    ArticleDetail,
    ArticleSummary,
    AuthorOut,
    CorpusPage,
    IngestRequest,
    IngestResult,
    IssueDetail,
    IssueSummary,
)
from cc_api.services.ingest import ingest_issue

router = APIRouter(prefix="/corpus", tags=["corpus"])
admin_router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_dev)])
log = get_logger(__name__)


async def _session() -> AsyncSession:
    return get_session_maker()()


@router.get("", response_model=CorpusPage)
async def list_corpus(
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> CorpusPage:
    """Liste paginée des numéros de revues (par date d'insertion décroissante)."""
    async with await _session() as session:
        total = (await session.execute(select(func.count()).select_from(Issue))).scalar_one()
        rows = (
            (
                await session.execute(
                    select(Issue)
                    .order_by(Issue.inserted_at.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            )
            .scalars()
            .all()
        )
        items: list[IssueSummary] = []
        for issue in rows:
            n_articles = (
                await session.execute(
                    select(func.count()).select_from(Article).where(Article.issue_id == issue.id)
                )
            ).scalar_one()
            items.append(
                IssueSummary(
                    slug=issue.slug,
                    journal_title=issue.journal_title,
                    issue_number=issue.issue_number,
                    title=issue.title,
                    published_date=issue.published_date,
                    inserted_at=issue.inserted_at,
                    n_articles=n_articles,
                )
            )
    return CorpusPage(items=items, page=page, size=size, total=total)


@router.get("/{issue_slug}", response_model=IssueDetail)
async def get_issue(issue_slug: str) -> IssueDetail:
    """Détail d'un numéro + liste des articles dedans."""
    async with await _session() as session:
        issue_q = await session.execute(select(Issue).where(Issue.slug == issue_slug))
        issue = issue_q.scalar_one_or_none()
        if issue is None:
            raise HTTPException(status_code=404, detail=f"issue '{issue_slug}' introuvable")
        articles = (
            (
                await session.execute(
                    select(Article)
                    .options(joinedload(Article.author))
                    .where(Article.issue_id == issue.id)
                    .order_by(Article.idx_in_issue)
                )
            )
            .scalars()
            .all()
        )
        return IssueDetail(
            id=issue.id,
            slug=issue.slug,
            ark=issue.ark,
            journal_title=issue.journal_title,
            issue_number=issue.issue_number,
            title=issue.title,
            published_date=issue.published_date,
            license=issue.license,
            source_desc=issue.source_desc,
            sha256=issue.sha256,
            inserted_at=issue.inserted_at,
            articles=[
                ArticleSummary(
                    slug=a.slug,
                    title=a.title,
                    author=a.author.display_name,
                    idx_in_issue=a.idx_in_issue,
                )
                for a in articles
            ],
        )


@router.get("/{issue_slug}/{article_slug}", response_model=ArticleDetail)
async def get_article(issue_slug: str, article_slug: str) -> ArticleDetail:
    """Article complet : titre, auteur, paragraphes reconstruits depuis les chunks."""
    async with await _session() as session:
        issue_q = await session.execute(select(Issue.id).where(Issue.slug == issue_slug))
        issue_id = issue_q.scalar_one_or_none()
        if issue_id is None:
            raise HTTPException(status_code=404, detail=f"issue '{issue_slug}' introuvable")
        article_q = await session.execute(
            select(Article)
            .options(joinedload(Article.author))
            .where(Article.issue_id == issue_id, Article.slug == article_slug)
        )
        article = article_q.scalar_one_or_none()
        if article is None:
            raise HTTPException(
                status_code=404, detail=f"article '{article_slug}' introuvable dans '{issue_slug}'"
            )
        chunks = (
            (
                await session.execute(
                    select(Chunk.text).where(Chunk.article_id == article.id).order_by(Chunk.idx)
                )
            )
            .scalars()
            .all()
        )
        return ArticleDetail(
            id=article.id,
            slug=article.slug,
            ark=article.ark,
            title=article.title,
            author=AuthorOut.model_validate(article.author),
            idx_in_issue=article.idx_in_issue,
            page_start=article.page_start,
            page_end=article.page_end,
            n_paragraphs=len(chunks),
            paragraphs=list(chunks),
        )


@admin_router.post("/ingest", response_model=IngestResult)
async def admin_ingest(payload: IngestRequest) -> IngestResult:
    """Ingère un fichier TEI (1 issue) (dev only)."""
    path = Path(payload.path)
    if not path.exists():
        raise HTTPException(status_code=422, detail=f"fichier introuvable : {path}")
    if not path.is_file():
        raise HTTPException(status_code=422, detail=f"pas un fichier : {path}")
    try:
        ref = await ingest_issue(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return IngestResult(
        issue_id=ref.issue_id,
        slug=ref.slug,
        ark=ref.ark,
        n_articles=ref.n_articles,
        n_chunks=ref.n_chunks,
        duration_ms=ref.duration_ms,
        was_duplicate=ref.was_duplicate,
    )

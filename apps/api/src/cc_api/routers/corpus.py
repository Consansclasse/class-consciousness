# SPDX-License-Identifier: AGPL-3.0-or-later
"""Router /corpus — liste paginée, détail, et /admin/ingest (dev-only)."""

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
from cc_api.models import Chunk, Work
from cc_api.schemas import (
    AuthorOut,
    CorpusPage,
    IngestRequest,
    IngestResult,
    WorkOut,
    WorkSummary,
)
from cc_api.services.ingest import ingest_tei

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
    """Liste paginée des œuvres ingérées (résumé : titre, auteur, date d'insertion)."""
    async with await _session() as session:
        total = (await session.execute(select(func.count()).select_from(Work))).scalar_one()
        rows = (
            (
                await session.execute(
                    select(Work)
                    .options(joinedload(Work.author))
                    .order_by(Work.inserted_at.desc())
                    .offset((page - 1) * size)
                    .limit(size)
                )
            )
            .scalars()
            .all()
        )

        items = [
            WorkSummary(
                title=w.title,
                author=w.author.display_name,
                inserted_at=w.inserted_at,
            )
            for w in rows
        ]
    return CorpusPage(items=items, page=page, size=size, total=total)


@router.get("/{work_id}", response_model=WorkOut)
async def get_work(work_id: int) -> WorkOut:
    """Détail d'une œuvre + nombre de chunks indexés."""
    async with await _session() as session:
        work_q = await session.execute(
            select(Work).options(joinedload(Work.author)).where(Work.id == work_id)
        )
        work = work_q.scalar_one_or_none()
        if work is None:
            raise HTTPException(status_code=404, detail=f"work {work_id} introuvable")
        n_chunks = (
            await session.execute(
                select(func.count()).select_from(Chunk).where(Chunk.work_id == work.id)
            )
        ).scalar_one()
        return WorkOut(
            id=work.id,
            ark=work.ark,
            title=work.title,
            author=AuthorOut.model_validate(work.author),
            published_date=work.published_date,
            source_url=work.source_url,
            license=work.license,
            sha256=work.sha256,
            inserted_at=work.inserted_at,
            n_chunks=n_chunks,
        )


@admin_router.post("/ingest", response_model=IngestResult)
async def admin_ingest(payload: IngestRequest) -> IngestResult:
    """Ingère un fichier TEI P5 (dev only). Path lisible côté serveur API."""
    path = Path(payload.path)
    if not path.exists():
        raise HTTPException(status_code=422, detail=f"fichier introuvable : {path}")
    if not path.is_file():
        raise HTTPException(status_code=422, detail=f"pas un fichier : {path}")

    try:
        ref = await ingest_tei(path)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return IngestResult(
        work_id=ref.work_id,
        ark=ref.ark,
        n_chunks=ref.n_chunks,
        duration_ms=ref.duration_ms,
        was_duplicate=ref.was_duplicate,
    )

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'idempotence et reproductibilité du pipeline d'ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cc_api.models import Article, Author, Chunk, Issue
from cc_api.services.ingest import COLLECTION, ingest_issue
from sqlalchemy import func, select


async def test_double_ingest_same_file_yields_one_issue(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    first = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )
    assert first.was_duplicate is False

    second = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )
    assert second.was_duplicate is True
    assert second.issue_id == first.issue_id

    issues = (await db_session.execute(select(func.count()).select_from(Issue))).scalar_one()
    articles = (await db_session.execute(select(func.count()).select_from(Article))).scalar_one()
    chunks = (await db_session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    assert issues == 1
    assert articles == first.n_articles
    assert chunks == first.n_chunks  # pas 2x les chunks


async def test_different_files_same_sha256_dedupe(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
    tmp_path: Path,
) -> None:
    """Copier la fixture sous un autre nom → mêmes bytes → même SHA → dédupliqué."""
    copy = tmp_path / "bilan-001-renamed.tei.xml"
    copy.write_bytes(canonical_tei_path.read_bytes())

    first = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )
    second = await ingest_issue(
        copy,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )

    assert second.was_duplicate is True
    assert second.issue_id == first.issue_id


async def test_modified_file_creates_new_issue(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
    tmp_path: Path,
) -> None:
    """Modifier un caractère dans le TEI change le SHA → nouvelle issue distincte."""
    first = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )

    # Réécrit le fichier en changeant l'ARK ET le titre (le slug Issue est dérivé du titre).
    modified = tmp_path / "bilan-002.tei.xml"
    content = (
        canonical_tei_path.read_text(encoding="utf-8")
        .replace("ark:/00000/test-bilan-001", "ark:/00000/test-bilan-002")
        .replace(
            "Fixture de test — pipeline ingestion",
            "Fixture de test — pipeline ingestion 002",
        )
    )
    modified.write_text(content, encoding="utf-8")

    second = await ingest_issue(
        modified,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )

    assert second.was_duplicate is False
    assert second.issue_id != first.issue_id

    issues = (await db_session.execute(select(func.count()).select_from(Issue))).scalar_one()
    assert issues == 2


async def test_reproducibility_uuid_v5_stable_across_reingestion(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Après ingest → reset DB+Qdrant → re-ingest, les qdrant_point_id sont identiques (UUID v5)."""
    first = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )
    # Joindre Chunk → Article pour filtrer par issue.
    first_point_ids = sorted(
        str(row[0])
        for row in (
            await db_session.execute(
                select(Chunk.qdrant_point_id)
                .join(Article, Chunk.article_id == Article.id)
                .where(Article.issue_id == first.issue_id)
            )
        ).all()
    )

    # Reset complet : DELETE issues CASCADE (issues→articles→chunks) puis authors séparément.
    await db_session.execute(Issue.__table__.delete())
    await db_session.execute(Author.__table__.delete())
    await db_session.commit()
    await qdrant_client.delete_collection(COLLECTION)

    second = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )
    second_point_ids = sorted(
        str(row[0])
        for row in (
            await db_session.execute(
                select(Chunk.qdrant_point_id)
                .join(Article, Chunk.article_id == Article.id)
                .where(Article.issue_id == second.issue_id)
            )
        ).all()
    )

    assert first_point_ids == second_point_ids, "UUID v5 non reproductibles après reset"
    assert first.n_chunks == second.n_chunks

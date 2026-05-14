# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'idempotence et reproductibilité du pipeline d'ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cc_api.models import Chunk, Work
from cc_api.services.ingest import COLLECTION, ingest_tei
from sqlalchemy import func, select


async def test_double_ingest_same_file_yields_one_work(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    first = await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )
    assert first.was_duplicate is False

    second = await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )
    assert second.was_duplicate is True
    assert second.work_id == first.work_id

    works = (await db_session.execute(select(func.count()).select_from(Work))).scalar_one()
    chunks = (await db_session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    assert works == 1
    assert chunks == first.n_chunks  # pas 2x les chunks


async def test_different_files_same_sha256_dedupe(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
    tmp_path: Path,
) -> None:
    """Copier la fixture sous un autre nom → mêmes bytes → même SHA → dédupliqué."""
    copy = tmp_path / "bilan-001-renamed.tei.xml"
    copy.write_bytes(canonical_tei_path.read_bytes())

    first = await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )
    second = await ingest_tei(
        copy,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )

    assert second.was_duplicate is True
    assert second.work_id == first.work_id


async def test_modified_file_creates_new_work(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
    tmp_path: Path,
) -> None:
    """Modifier un caractère dans le TEI change le SHA → nouveau work distinct."""
    first = await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )

    # Réécrit le fichier en changeant l'ARK pour éviter la contrainte UNIQUE(ark)
    modified = tmp_path / "bilan-002.tei.xml"
    content = canonical_tei_path.read_text(encoding="utf-8").replace(
        "ark:/00000/test-bilan-001", "ark:/00000/test-bilan-002"
    )
    modified.write_text(content, encoding="utf-8")

    second = await ingest_tei(
        modified,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )

    assert second.was_duplicate is False
    assert second.work_id != first.work_id

    works = (await db_session.execute(select(func.count()).select_from(Work))).scalar_one()
    assert works == 2


async def test_reproducibility_uuid_v5_stable_across_reingestion(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    """Après ingest → reset DB+Qdrant → re-ingest, les qdrant_point_id sont identiques (UUID v5)."""
    first = await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )
    first_point_ids = sorted(
        str(row[0])
        for row in (
            await db_session.execute(
                select(Chunk.qdrant_point_id).where(Chunk.work_id == first.work_id)
            )
        ).all()
    )

    # Reset complet
    await db_session.execute(Chunk.__table__.delete())
    await db_session.execute(Work.__table__.delete())
    await db_session.commit()
    await qdrant_client.delete_collection(COLLECTION)

    second = await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )
    second_point_ids = sorted(
        str(row[0])
        for row in (
            await db_session.execute(
                select(Chunk.qdrant_point_id).where(Chunk.work_id == second.work_id)
            )
        ).all()
    )

    assert first_point_ids == second_point_ids, "UUID v5 non reproductibles après reset"
    assert first.n_chunks == second.n_chunks

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du pipeline d'ingestion TEI → Postgres + Qdrant.

Pas de mocks DB/Qdrant : testcontainers réels. Voyage AI via httpx.MockTransport
(transport, pas mock métier) avec des embeddings déterministes par hash.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cc_api.models import Author, Chunk, Work
from cc_api.services.ingest import COLLECTION, VOYAGE_DIM, ingest_tei
from cc_corpus.tei import parse
from qdrant_client.http.models import Distance, VectorParams
from sqlalchemy import func, select


async def test_ingest_creates_work_author_chunks_atomically(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    ref = await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )

    works = (await db_session.execute(select(func.count()).select_from(Work))).scalar_one()
    authors = (await db_session.execute(select(func.count()).select_from(Author))).scalar_one()
    chunks = (await db_session.execute(select(func.count()).select_from(Chunk))).scalar_one()

    assert works == 1
    assert authors == 1
    assert chunks >= 3
    assert ref.n_chunks == chunks
    assert ref.was_duplicate is False


async def test_chunk_offsets_round_trip_through_db(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    """Invariant règle d'or : full_text[c.char_start:c.char_end] == c.text après round-trip."""
    await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )

    full_text = parse(canonical_tei_path).full_text
    chunks = (await db_session.execute(select(Chunk).order_by(Chunk.idx))).scalars().all()

    for c in chunks:
        slice_ = full_text[c.char_start : c.char_end]
        assert slice_ == c.text, (
            f"chunk idx={c.idx} : offsets corrompus après round-trip DB "
            f"(attendu={c.text[:30]!r}, obtenu={slice_[:30]!r})"
        )


async def test_qdrant_upsert_payload_carries_offsets(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )

    info = await qdrant_client.get_collection(COLLECTION)
    assert info.points_count is not None and info.points_count >= 3

    # Récupère le 1er point pour vérifier payload + dim
    chunks = (await db_session.execute(select(Chunk).order_by(Chunk.idx).limit(1))).scalars().all()
    assert chunks
    point_id = str(chunks[0].qdrant_point_id)
    points = await qdrant_client.retrieve(
        collection_name=COLLECTION, ids=[point_id], with_vectors=True, with_payload=True
    )
    assert len(points) == 1
    pt = points[0]
    assert pt.payload is not None
    assert pt.payload["chunk_idx"] == chunks[0].idx
    assert pt.payload["char_start"] == chunks[0].char_start
    assert pt.payload["char_end"] == chunks[0].char_end
    assert pt.payload["ark"] == "ark:/00000/test-bilan-001"
    assert len(pt.vector) == VOYAGE_DIM  # type: ignore[arg-type]


async def test_self_test_finds_first_chunk_top1(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    """Le self-test interne implicite : si on cherche avec l'embedding du 1er chunk,
    on retrouve ce chunk en top-1 avec score ≥ 0.99."""
    from cc_api.clients.voyage import VoyageClient

    # Récupère les embeddings utilisés (via le mock, déterministes)
    await ingest_tei(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        voyage=mock_voyage_client,
    )

    chunks = (await db_session.execute(select(Chunk).order_by(Chunk.idx).limit(1))).scalars().all()
    assert chunks
    first_chunk = chunks[0]

    # Re-embedder le 1er chunk avec le même mock pour reproduire son vecteur
    assert isinstance(mock_voyage_client, VoyageClient)
    embeddings = await mock_voyage_client.embed_batch([first_chunk.text])

    hits = await qdrant_client.query_points(
        collection_name=COLLECTION, query=embeddings[0], limit=1
    )
    assert hits.points
    top = hits.points[0]
    assert str(top.id) == str(first_chunk.qdrant_point_id)
    assert top.score is not None and top.score >= 0.99


async def test_ingest_rollback_on_qdrant_failure(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    """Force une collection avec dim incompatible → upsert Qdrant échoue → rollback complet."""
    # Pré-créer la collection avec une dim incorrecte pour faire échouer l'upsert
    await qdrant_client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=512, distance=Distance.COSINE),
    )

    # Qdrant lève une exception non-publique stable ; on accepte n'importe quelle erreur.
    with pytest.raises(BaseException, match=r"(?i).*"):
        await ingest_tei(
            canonical_tei_path,
            session=db_session,
            qdrant=qdrant_client,
            voyage=mock_voyage_client,
        )

    # Vérifie qu'aucun work n'a été persisté (rollback Postgres)
    works = (await db_session.execute(select(func.count()).select_from(Work))).scalar_one()
    chunks = (await db_session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    assert works == 0
    assert chunks == 0


async def test_invalid_tei_raises_before_db_write(
    invalid_tei_no_ark: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_voyage_client: Any,
) -> None:
    """Un TEI sans ARK déclenche ValueError du parser → 0 work/chunk insérés."""
    with pytest.raises(ValueError, match=r"(?i)ark"):
        await ingest_tei(
            invalid_tei_no_ark,
            session=db_session,
            qdrant=qdrant_client,
            voyage=mock_voyage_client,
        )
    works = (await db_session.execute(select(func.count()).select_from(Work))).scalar_one()
    assert works == 0


@pytest.fixture
def invalid_tei_no_ark() -> Path:
    """Réutilise la fixture invalide du package corpus-tools."""
    path = (
        Path(__file__).resolve().parents[4]
        / "packages"
        / "corpus-tools"
        / "tests"
        / "fixtures"
        / "bilan-invalid-no-ark.tei.xml"
    )
    assert path.exists(), f"fixture absente : {path}"
    return path

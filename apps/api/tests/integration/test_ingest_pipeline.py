# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du pipeline d'ingestion TEI hiérarchique → Postgres + Qdrant.

Pas de mocks DB/Qdrant : testcontainers réels. Le serveur cc-embed est simulé
via httpx.MockTransport (transport, pas mock métier) avec des embeddings
déterministes par hash.

La fixture canonique `corpus/_seed/bilan-001.tei.xml` n'a pas de
`<div type="article">` — `parse_issue` applique son fallback : 1 article unique
avec slug = `slugify(title)` = `fixture-de-test-pipeline-ingestion`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from cc_api.core.settings import settings
from cc_api.models import Article, Author, Chunk, Issue
from cc_api.services.ingest import COLLECTION, ingest_issue
from cc_corpus.tei import parse_issue
from qdrant_client.http.models import Distance, VectorParams
from sqlalchemy import func, select

FIXTURE_ISSUE_ARK = "ark:/00000/test-bilan-001"
FIXTURE_ARTICLE_SLUG = "fixture-de-test-pipeline-ingestion"
FIXTURE_ARTICLE_ARK = f"{FIXTURE_ISSUE_ARK}/{FIXTURE_ARTICLE_SLUG}"


async def test_ingest_creates_issue_article_author_chunks_atomically(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    ref = await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )

    issues = (await db_session.execute(select(func.count()).select_from(Issue))).scalar_one()
    articles = (await db_session.execute(select(func.count()).select_from(Article))).scalar_one()
    authors = (await db_session.execute(select(func.count()).select_from(Author))).scalar_one()
    chunks = (await db_session.execute(select(func.count()).select_from(Chunk))).scalar_one()

    assert issues == 1
    assert articles == 1  # fixture _seed = fallback 1 article unique
    assert authors == 1
    assert chunks >= 3
    assert ref.n_articles == articles
    assert ref.n_chunks == chunks
    assert ref.was_duplicate is False
    assert ref.ark == FIXTURE_ISSUE_ARK


async def test_chunk_offsets_round_trip_through_db(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Invariant règle d'or : full_text[c.char_start:c.char_end] == c.text après round-trip.

    Les offsets sont relatifs au full_text de l'article (et non au TEI complet),
    car `parse_issue` produit un IssueDocument dont chaque ArticleData a son propre
    full_text et ses propres offsets.
    """
    await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )

    doc = parse_issue(canonical_tei_path)
    assert len(doc.articles) == 1, "fixture canonique = fallback 1 article unique"
    article_full_text = doc.articles[0].full_text

    chunks = (await db_session.execute(select(Chunk).order_by(Chunk.idx))).scalars().all()
    assert chunks

    for c in chunks:
        slice_ = article_full_text[c.char_start : c.char_end]
        assert slice_ == c.text, (
            f"chunk idx={c.idx} : offsets corrompus après round-trip DB "
            f"(attendu={c.text[:30]!r}, obtenu={slice_[:30]!r})"
        )


async def test_qdrant_upsert_payload_carries_offsets_and_ark(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Le payload Qdrant porte issue/article identifiers + offsets caractères."""
    await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )

    info = await qdrant_client.get_collection(COLLECTION)
    assert info.points_count is not None and info.points_count >= 3

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
    assert pt.payload["article_ark"] == FIXTURE_ARTICLE_ARK
    assert pt.payload["article_slug"] == FIXTURE_ARTICLE_SLUG
    assert pt.payload["issue_slug"] == FIXTURE_ARTICLE_SLUG  # même slugify pour cette fixture
    assert len(pt.vector) == settings.embed_dim  # type: ignore[arg-type]


async def test_self_test_finds_first_chunk_top1(
    canonical_tei_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Le self-test interne implicite : si on cherche avec l'embedding du 1er chunk,
    on retrouve ce chunk en top-1 avec score ≥ 0.99."""
    from cc_api.clients.embed import LocalEmbedClient

    await ingest_issue(
        canonical_tei_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=mock_embed_client,
    )

    chunks = (await db_session.execute(select(Chunk).order_by(Chunk.idx).limit(1))).scalars().all()
    assert chunks
    first_chunk = chunks[0]

    assert isinstance(mock_embed_client, LocalEmbedClient)
    embeddings = await mock_embed_client.embed_batch([first_chunk.text])

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
    mock_embed_client: Any,
) -> None:
    """Force une collection avec dim incompatible → upsert Qdrant échoue → rollback complet."""
    await qdrant_client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=512, distance=Distance.COSINE),
    )

    with pytest.raises(BaseException, match=r"(?i).*"):
        await ingest_issue(
            canonical_tei_path,
            session=db_session,
            qdrant=qdrant_client,
            embed=mock_embed_client,
        )

    issues = (await db_session.execute(select(func.count()).select_from(Issue))).scalar_one()
    articles = (await db_session.execute(select(func.count()).select_from(Article))).scalar_one()
    chunks = (await db_session.execute(select(func.count()).select_from(Chunk))).scalar_one()
    assert issues == 0
    assert articles == 0
    assert chunks == 0


async def test_invalid_tei_raises_before_db_write(
    invalid_tei_no_ark: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """Un TEI sans ARK déclenche ValueError du parser → 0 issue/article/chunk insérés."""
    with pytest.raises(ValueError, match=r"(?i)ark"):
        await ingest_issue(
            invalid_tei_no_ark,
            session=db_session,
            qdrant=qdrant_client,
            embed=mock_embed_client,
        )
    issues = (await db_session.execute(select(func.count()).select_from(Issue))).scalar_one()
    assert issues == 0


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

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Service d'ingestion TEI → Postgres + Qdrant.

Transaction unique Postgres avec rollback compensating Qdrant en cas d'échec.
Idempotence par SHA256 des bytes bruts. Self-test post-ingest : seuil ≥ 0.99.
"""

from __future__ import annotations

import contextlib
import hashlib
import time
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cc_corpus.chunk import split
from cc_corpus.tei import parse
from qdrant_client import AsyncQdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.clients.db import get_session_maker
from cc_api.clients.qdrant import get_qdrant
from cc_api.clients.voyage import VoyageClient, get_voyage_client
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.models import Author, Chunk, Work

COLLECTION = "bilan"
VOYAGE_DIM = 1024
SELF_TEST_THRESHOLD = 0.99
NAMESPACE_QDRANT = uuid.uuid5(uuid.NAMESPACE_URL, "https://consciencedeclasse.com/qdrant/bilan")

log = get_logger(__name__)


class IngestSelfTestError(RuntimeError):
    """Self-test post-ingest : top-1 ne matche pas ou score < seuil."""


@dataclass(frozen=True)
class WorkRef:
    work_id: int
    ark: str
    n_chunks: int
    duration_ms: int
    was_duplicate: bool = False


def chunk_point_id(work_ark: str, idx: int) -> uuid.UUID:
    """UUID v5 déterministe pour un (work_ark, idx). Permet la reproductibilité."""
    return uuid.uuid5(NAMESPACE_QDRANT, f"{work_ark}#{idx:08d}")


def _parse_published_date(date_iso: str) -> date | None:
    if len(date_iso) == 10:
        try:
            return date.fromisoformat(date_iso)
        except ValueError:
            return None
    return None


async def _ensure_collection(qdrant: AsyncQdrantClient) -> None:
    cols = await qdrant.get_collections()
    if COLLECTION not in {c.name for c in cols.collections}:
        await qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=VOYAGE_DIM, distance=Distance.COSINE),
        )


async def _self_test(
    qdrant: AsyncQdrantClient,
    first_embedding: list[float],
    expected_point_id: str,
    expected_work_id: int,
) -> None:
    hits = await qdrant.query_points(
        collection_name=COLLECTION,
        query=first_embedding,
        limit=1,
        with_payload=True,
        query_filter=Filter(
            must=[FieldCondition(key="work_id", match=MatchValue(value=expected_work_id))]
        ),
    )
    if not hits.points:
        raise IngestSelfTestError(
            f"aucun point retrouvé pour work_id={expected_work_id} après upsert"
        )
    top = hits.points[0]
    if top.score is None or top.score < SELF_TEST_THRESHOLD:
        raise IngestSelfTestError(
            f"self-test score={top.score} (< {SELF_TEST_THRESHOLD}) pour work_id={expected_work_id}"
        )


async def ingest_tei(
    path: Path,
    *,
    session: AsyncSession | None = None,
    qdrant: AsyncQdrantClient | None = None,
    voyage: VoyageClient | None = None,
) -> WorkRef:
    """Ingère un fichier TEI P5 → Postgres + Qdrant. Idempotent par SHA256.

    Ordre transactionnel : INSERT Postgres (sans commit) → UPSERT Qdrant →
    self-test → COMMIT Postgres. En cas d'échec : rollback Postgres + DELETE
    des points Qdrant déjà créés (best-effort).
    """
    started_at = time.monotonic()
    embedding_model = settings.voyage_embed_model

    raw_bytes = path.read_bytes()
    sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
    sha_short = sha256_hex[:8]

    log.info(
        "ingest.start",
        path=str(path),
        sha256_short=sha_short,
        file_size_bytes=len(raw_bytes),
    )

    owns_session = session is None
    owns_voyage = voyage is None
    if session is None:
        session = get_session_maker()()
    if qdrant is None:
        qdrant = get_qdrant()
    if voyage is None:
        voyage = get_voyage_client()

    try:
        # Idempotence — short-circuit si SHA256 déjà connu.
        existing = (
            await session.execute(select(Work.id, Work.ark).where(Work.sha256 == sha256_hex))
        ).first()
        if existing is not None:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            log.info(
                "ingest.short_circuit_idempotent",
                sha256_short=sha_short,
                existing_work_id=existing.id,
                reason="sha256_match",
            )
            return WorkRef(
                work_id=existing.id,
                ark=existing.ark,
                n_chunks=0,
                duration_ms=duration_ms,
                was_duplicate=True,
            )

        # Parse TEI
        parse_start = time.monotonic()
        doc = parse(path)
        log.info(
            "ingest.parsed",
            sha256_short=sha_short,
            title=doc.title,
            author_name=doc.author_name,
            n_paragraphs=len(doc.paragraphs),
            duration_ms=int((time.monotonic() - parse_start) * 1000),
        )

        # Chunk
        chunk_start = time.monotonic()
        chunks = split(doc.paragraphs)
        if not chunks:
            raise ValueError(f"aucun chunk produit pour {path}")
        avg = sum(c.token_count for c in chunks) // len(chunks)
        max_tokens = max(c.token_count for c in chunks)
        log.info(
            "ingest.chunked",
            sha256_short=sha_short,
            n_chunks=len(chunks),
            avg_tokens=avg,
            max_tokens=max_tokens,
            duration_ms=int((time.monotonic() - chunk_start) * 1000),
        )

        # Embed
        embed_start = time.monotonic()
        embeddings = await voyage.embed_batch([c.text for c in chunks])
        if len(embeddings) != len(chunks):
            raise RuntimeError(
                f"Voyage a renvoyé {len(embeddings)} vecteurs pour {len(chunks)} chunks"
            )
        log.info(
            "ingest.embedded",
            sha256_short=sha_short,
            n_chunks=len(chunks),
            model=embedding_model,
            duration_ms=int((time.monotonic() - embed_start) * 1000),
        )

        # Upsert auteur (recherche par display_name simple en phase 0)
        author_row = await session.execute(
            select(Author).where(Author.display_name == doc.author_name)
        )
        author = author_row.scalar_one_or_none()
        if author is None:
            author = Author(display_name=doc.author_name)
            session.add(author)
            await session.flush()

        # INSERT work + chunks (sans commit)
        store_start = time.monotonic()
        work = Work(
            ark=doc.ark,
            title=doc.title,
            author_id=author.id,
            published_date=_parse_published_date(doc.date_iso),
            license=doc.license,
            sha256=sha256_hex,
        )
        session.add(work)
        await session.flush()

        chunk_rows: list[Chunk] = []
        point_ids: list[int | str | uuid.UUID] = []
        for c in chunks:
            point_uuid = chunk_point_id(doc.ark, c.idx)
            point_ids.append(point_uuid)
            chunk_rows.append(
                Chunk(
                    work_id=work.id,
                    idx=c.idx,
                    text=c.text,
                    char_start=c.char_start,
                    char_end=c.char_end,
                    token_count=c.token_count,
                    embedding_model=embedding_model,
                    qdrant_point_id=point_uuid,
                )
            )
        session.add_all(chunk_rows)
        await session.flush()
        log.info(
            "ingest.stored",
            sha256_short=sha_short,
            work_id=work.id,
            author_id=author.id,
            n_chunks_inserted=len(chunks),
            duration_ms=int((time.monotonic() - store_start) * 1000),
        )

        # UPSERT Qdrant + self-test
        await _ensure_collection(qdrant)
        points = [
            PointStruct(
                id=point_ids[i],
                vector=embeddings[i],
                payload={
                    "work_id": work.id,
                    "chunk_idx": c.idx,
                    "char_start": c.char_start,
                    "char_end": c.char_end,
                    "ark": doc.ark,
                },
            )
            for i, c in enumerate(chunks)
        ]
        qdrant_start = time.monotonic()
        try:
            await qdrant.upsert(collection_name=COLLECTION, points=points)
            log.info(
                "ingest.qdrant_upserted",
                sha256_short=sha_short,
                work_id=work.id,
                collection=COLLECTION,
                n_points=len(points),
                duration_ms=int((time.monotonic() - qdrant_start) * 1000),
            )

            selftest_start = time.monotonic()
            await _self_test(qdrant, embeddings[0], str(point_ids[0]), work.id)
            log.info(
                "ingest.selftest_ok",
                sha256_short=sha_short,
                work_id=work.id,
                duration_ms=int((time.monotonic() - selftest_start) * 1000),
            )
        except Exception as exc:
            with contextlib.suppress(Exception):
                await qdrant.delete(collection_name=COLLECTION, points_selector=point_ids)
            await session.rollback()
            log.error(
                "ingest.error",
                sha256_short=sha_short,
                stage="qdrant_or_selftest",
                error_type=type(exc).__name__,
                error_message=str(exc),
                rolled_back=True,
            )
            raise

        # COMMIT Postgres
        await session.commit()
        duration_ms = int((time.monotonic() - started_at) * 1000)
        log.info(
            "ingest.done",
            sha256_short=sha_short,
            work_id=work.id,
            n_chunks=len(chunks),
            total_duration_ms=duration_ms,
        )
        return WorkRef(
            work_id=work.id,
            ark=doc.ark,
            n_chunks=len(chunks),
            duration_ms=duration_ms,
            was_duplicate=False,
        )

    finally:
        if owns_session:
            await session.close()
        if owns_voyage:
            await voyage.aclose()

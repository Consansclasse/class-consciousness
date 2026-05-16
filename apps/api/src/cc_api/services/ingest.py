# SPDX-License-Identifier: AGPL-3.0-or-later
"""Service d'ingestion TEI (issue hiérarchique) → Postgres + Qdrant.

1 TEI = 1 issue (numéro de revue) contenant N articles. Chaque article est
chunké et indexé indépendamment. Transaction unique Postgres avec rollback
compensating Qdrant en cas d'échec. Idempotence par SHA256 du fichier TEI.
Self-test post-ingest : seuil ≥ 0.99 sur le 1er chunk du 1er article.
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
from cc_corpus.tei import parse_issue
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
from cc_api.clients.embed import EmbedClient, get_embed_client
from cc_api.clients.qdrant import get_qdrant
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.models import Article, Author, Chunk, Issue

COLLECTION = "bilan"
SELF_TEST_THRESHOLD = 0.99
NAMESPACE_QDRANT = uuid.uuid5(uuid.NAMESPACE_URL, "https://consciencedeclasse.com/qdrant/bilan")

log = get_logger(__name__)


class IngestSelfTestError(RuntimeError):
    """Self-test post-ingest : top-1 ne matche pas ou score < seuil."""


@dataclass(frozen=True)
class IssueRef:
    issue_id: int
    slug: str
    ark: str
    n_articles: int
    n_chunks: int
    duration_ms: int
    was_duplicate: bool = False


def chunk_point_id(article_ark: str, idx: int) -> uuid.UUID:
    """UUID v5 déterministe pour un (article_ark, idx)."""
    return uuid.uuid5(NAMESPACE_QDRANT, f"{article_ark}#{idx:08d}")


def _parse_published_date(date_iso: str) -> date | None:
    if len(date_iso) == 10:
        try:
            return date.fromisoformat(date_iso)
        except ValueError:
            return None
    return None


async def _ensure_collection(qdrant: AsyncQdrantClient) -> None:
    """Crée la collection Qdrant si absente, en dimension `settings.embed_dim`.

    Si elle existe déjà avec une dimension différente (ex. après un changement
    de modèle d'embedding), on échoue explicitement : mélanger deux espaces
    vectoriels corromprait la recherche. La recréation est une opération
    destructrice délibérée, jamais implicite ici.
    """
    cols = await qdrant.get_collections()
    if COLLECTION not in {c.name for c in cols.collections}:
        await qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=VectorParams(size=settings.embed_dim, distance=Distance.COSINE),
        )
        return
    info = await qdrant.get_collection(COLLECTION)
    existing_dim = info.config.params.vectors.size  # type: ignore[union-attr]
    if existing_dim != settings.embed_dim:
        raise RuntimeError(
            f"collection '{COLLECTION}' en dimension {existing_dim}, "
            f"attendu {settings.embed_dim}. "
            f"Recréer la collection puis ré-ingérer le corpus."
        )


async def _self_test(
    qdrant: AsyncQdrantClient,
    first_embedding: list[float],
    expected_article_id: int,
) -> None:
    hits = await qdrant.query_points(
        collection_name=COLLECTION,
        query=first_embedding,
        limit=1,
        with_payload=True,
        query_filter=Filter(
            must=[FieldCondition(key="article_id", match=MatchValue(value=expected_article_id))]
        ),
    )
    if not hits.points:
        raise IngestSelfTestError(
            f"aucun point retrouvé pour article_id={expected_article_id} après upsert"
        )
    top = hits.points[0]
    if top.score is None or top.score < SELF_TEST_THRESHOLD:
        raise IngestSelfTestError(
            f"self-test score={top.score} (< {SELF_TEST_THRESHOLD}) "
            f"pour article_id={expected_article_id}"
        )


async def _upsert_author(session: AsyncSession, display_name: str) -> Author:
    row = await session.execute(select(Author).where(Author.display_name == display_name))
    author = row.scalar_one_or_none()
    if author is None:
        author = Author(display_name=display_name)
        session.add(author)
        await session.flush()
    return author


async def ingest_issue(
    path: Path,
    *,
    session: AsyncSession | None = None,
    qdrant: AsyncQdrantClient | None = None,
    embed: EmbedClient | None = None,
) -> IssueRef:
    """Ingère un fichier TEI (1 numéro de revue avec N articles) → Postgres + Qdrant.

    Idempotent par SHA256. Ordre transactionnel : INSERT Postgres (sans commit)
    → UPSERT Qdrant → self-test → COMMIT Postgres. Rollback compensating Qdrant
    si échec après UPSERT.
    """
    started_at = time.monotonic()
    embedding_model = settings.embed_model

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
    owns_embed = embed is None
    if session is None:
        session = get_session_maker()()
    if qdrant is None:
        qdrant = get_qdrant()
    if embed is None:
        embed = get_embed_client()

    all_point_ids: list[int | str | uuid.UUID] = []
    try:
        # Idempotence — short-circuit si SHA256 déjà connu.
        existing = (
            await session.execute(
                select(Issue.id, Issue.slug, Issue.ark).where(Issue.sha256 == sha256_hex)
            )
        ).first()
        if existing is not None:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            log.info(
                "ingest.short_circuit_idempotent",
                sha256_short=sha_short,
                existing_issue_id=existing.id,
            )
            return IssueRef(
                issue_id=existing.id,
                slug=existing.slug,
                ark=existing.ark,
                n_articles=0,
                n_chunks=0,
                duration_ms=duration_ms,
                was_duplicate=True,
            )

        # Parse TEI hiérarchique.
        doc = parse_issue(path)
        log.info(
            "ingest.parsed",
            sha256_short=sha_short,
            journal=doc.journal_title,
            issue_number=doc.issue_number,
            n_articles=len(doc.articles),
        )

        # INSERT issue.
        issue = Issue(
            slug=doc.slug,
            ark=doc.ark,
            journal_title=doc.journal_title,
            issue_number=doc.issue_number,
            title=doc.title,
            published_date=_parse_published_date(doc.date_iso),
            license=doc.license,
            source_desc=doc.source_desc,
            sha256=sha256_hex,
        )
        session.add(issue)
        await session.flush()

        # Pour le self-test après UPSERT Qdrant.
        first_article_id: int | None = None
        first_embedding: list[float] | None = None
        total_chunks = 0
        all_points: list[PointStruct] = []

        for idx_in_issue, article_data in enumerate(doc.articles):
            author = await _upsert_author(session, article_data.author_name)
            article_ark = f"{doc.ark}/{article_data.slug}"
            article = Article(
                issue_id=issue.id,
                slug=article_data.slug,
                ark=article_ark,
                title=article_data.title,
                author_id=author.id,
                idx_in_issue=idx_in_issue,
            )
            session.add(article)
            await session.flush()

            # Chunk + embed.
            chunks = split(article_data.paragraphs)
            if not chunks:
                raise ValueError(f"article '{article_data.slug}' produit 0 chunks")
            embeddings = await embed.embed_batch(
                [c.text for c in chunks], input_type="document"
            )
            if len(embeddings) != len(chunks):
                raise RuntimeError(
                    f"le backend d'embedding a renvoyé {len(embeddings)} vecteurs "
                    f"pour {len(chunks)} chunks"
                )

            chunk_rows: list[Chunk] = []
            for c, emb in zip(chunks, embeddings, strict=True):
                point_uuid = chunk_point_id(article_ark, c.idx)
                all_point_ids.append(point_uuid)
                chunk_rows.append(
                    Chunk(
                        article_id=article.id,
                        idx=c.idx,
                        text=c.text,
                        char_start=c.char_start,
                        char_end=c.char_end,
                        token_count=c.token_count,
                        embedding_model=embedding_model,
                        qdrant_point_id=point_uuid,
                    )
                )
                all_points.append(
                    PointStruct(
                        id=point_uuid,
                        vector=emb,
                        payload={
                            "issue_id": issue.id,
                            "issue_slug": doc.slug,
                            "issue_ark": doc.ark,
                            "issue_title": doc.title,
                            "article_id": article.id,
                            "article_slug": article_data.slug,
                            "article_ark": article_ark,
                            "article_title": article_data.title,
                            "author_name": article_data.author_name,
                            "chunk_idx": c.idx,
                            "char_start": c.char_start,
                            "char_end": c.char_end,
                            "text": c.text,
                        },
                    )
                )
            session.add_all(chunk_rows)
            await session.flush()
            total_chunks += len(chunks)

            if first_article_id is None:
                first_article_id = article.id
                first_embedding = embeddings[0]

        log.info(
            "ingest.stored",
            sha256_short=sha_short,
            issue_id=issue.id,
            n_articles=len(doc.articles),
            n_chunks_inserted=total_chunks,
        )

        # UPSERT Qdrant + self-test. `_ensure_collection` est dans le bloc
        # protégé : une incompatibilité de dimension détectée ici doit aussi
        # déclencher le rollback compensating Postgres.
        qdrant_start = time.monotonic()
        try:
            await _ensure_collection(qdrant)
            await qdrant.upsert(collection_name=COLLECTION, points=all_points)
            log.info(
                "ingest.qdrant_upserted",
                sha256_short=sha_short,
                issue_id=issue.id,
                collection=COLLECTION,
                n_points=len(all_points),
                duration_ms=int((time.monotonic() - qdrant_start) * 1000),
            )
            assert first_embedding is not None and first_article_id is not None
            await _self_test(qdrant, first_embedding, first_article_id)
            log.info("ingest.selftest_ok", sha256_short=sha_short, issue_id=issue.id)
        except Exception as exc:
            with contextlib.suppress(Exception):
                await qdrant.delete(collection_name=COLLECTION, points_selector=all_point_ids)
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

        # COMMIT Postgres.
        await session.commit()
        duration_ms = int((time.monotonic() - started_at) * 1000)
        log.info(
            "ingest.done",
            sha256_short=sha_short,
            issue_id=issue.id,
            n_articles=len(doc.articles),
            n_chunks=total_chunks,
            total_duration_ms=duration_ms,
        )
        return IssueRef(
            issue_id=issue.id,
            slug=doc.slug,
            ark=doc.ark,
            n_articles=len(doc.articles),
            n_chunks=total_chunks,
            duration_ms=duration_ms,
            was_duplicate=False,
        )

    finally:
        if owns_session:
            await session.close()
        if owns_embed:
            await embed.aclose()

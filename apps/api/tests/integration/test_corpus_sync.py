# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de l'auto-synchro du corpus (services/corpus_sync.py).

Deux niveaux, sans réseau ni mock de notre code :
- `_select_from_tarball` : sélection + extraction, sur une archive construite EN
  MÉMOIRE → prouve que le glob canonique ne retient que les numéros consolidés
  (et exclut les variantes découpées + les fichiers hors corpus).
- `sync_once` : ingestion réelle via testcontainers (Postgres + Qdrant) →
  ingestion, idempotence (2ᵉ passe = doublon), et isolation d'un fichier cassé
  (le lot continue).
"""

from __future__ import annotations

import io
import tarfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from cc_api.models import Issue
from cc_api.services.corpus_sync import _select_from_tarball, sync_once
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

CANONICAL_GLOB = "**/bilan/bilan-[0-9][0-9][0-9].tei.xml"


def _make_tarball(names_to_content: dict[str, bytes]) -> bytes:
    """Construit un `.tar.gz` en mémoire (pas de disque, pas de réseau)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in names_to_content.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def test_select_from_tarball_keeps_only_consolidated_issues(tmp_path: Path) -> None:
    """Le glob canonique retient les `bilan-NNN.tei.xml` et rien d'autre."""
    root = "class-consciousness-corpus-main"
    tar_bytes = _make_tarball(
        {
            f"{root}/bilan/bilan-001.tei.xml": b"<TEI/>",
            f"{root}/bilan/bilan-042.tei.xml": b"<TEI/>",
            # Variante découpée du n°1 — NE DOIT PAS matcher.
            f"{root}/bilan/bilan-001-introduction.tei.xml": b"<TEI/>",
            # Hors corpus — NE DOIT PAS matcher.
            f"{root}/README.md": b"# corpus",
            f"{root}/_meta/.gitkeep": b"",
        }
    )

    selected = _select_from_tarball(tar_bytes, CANONICAL_GLOB, tmp_path)

    assert [p.name for p in selected] == ["bilan-001.tei.xml", "bilan-042.tei.xml"]


def test_select_from_tarball_empty_when_nothing_matches(tmp_path: Path) -> None:
    tar_bytes = _make_tarball({"root/README.md": b"# nothing to ingest"})
    assert _select_from_tarball(tar_bytes, CANONICAL_GLOB, tmp_path) == []


@pytest_asyncio.fixture
async def patched_db(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Pointe le `get_session_maker` interne de `ingest_issue` vers le testcontainer.

    `sync_once` appelle `ingest_issue(session=None)` → chaque fichier possède SA
    session (commit/rollback isolés) ; il faut donc patcher la fabrique de session
    du module ingest, pas injecter une session partagée."""
    from cc_api.clients import db as db_module
    from cc_api.services import ingest as ingest_module

    engine = create_async_engine(migrated_db, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    for mod in (db_module, ingest_module):
        monkeypatch.setattr(mod, "get_session_maker", lambda m=maker: m)
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    try:
        yield
    finally:
        await engine.dispose()


async def test_sync_once_ingests_then_dedupes(
    canonical_tei_path: Path,
    patched_db: None,
    clean_db: None,
    clean_qdrant: None,
    qdrant_client: Any,
    mock_embed_client: Any,
) -> None:
    """1ʳᵉ passe ingère ; 2ᵉ passe sur le même fichier = doublon (idempotence)."""
    first = await sync_once([canonical_tei_path], embed=mock_embed_client, qdrant=qdrant_client)
    assert (first.ingested, first.duplicates, first.errors) == (1, 0, 0)
    assert first.ok

    second = await sync_once([canonical_tei_path], embed=mock_embed_client, qdrant=qdrant_client)
    assert (second.ingested, second.duplicates, second.errors) == (0, 1, 0)


async def test_sync_once_isolates_broken_file(
    canonical_tei_path: Path,
    patched_db: None,
    clean_db: None,
    clean_qdrant: None,
    qdrant_client: Any,
    mock_embed_client: Any,
    db_session: Any,
    tmp_path: Path,
) -> None:
    """Un TEI cassé n'interrompt pas le lot : l'autre fichier est bien ingéré.

    Le fichier cassé est listé EN PREMIER pour prouver que son échec (chaque
    `ingest_issue` possède sa propre session) ne contamine pas l'ingestion du
    fichier valide qui suit."""
    broken = tmp_path / "bilan-666.tei.xml"
    broken.write_text("ceci n'est pas du TEI valide <<<", encoding="utf-8")

    report = await sync_once(
        [broken, canonical_tei_path], embed=mock_embed_client, qdrant=qdrant_client
    )

    assert report.errors == 1
    assert report.ingested == 1
    assert not report.ok

    # Le fichier valide a bien atterri en base, malgré l'échec du précédent.
    issues = (await db_session.execute(select(func.count()).select_from(Issue))).scalar_one()
    assert issues == 1

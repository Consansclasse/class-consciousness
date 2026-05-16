# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration des routes /corpus et /admin/ingest (hiérarchie Issue → Article)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# Fixture _seed : pas de <div type="article"> → fallback parse_issue 1 article unique
# avec slug = slugify("Fixture de test — pipeline ingestion").
FIXTURE_ISSUE_ARK = "ark:/00000/test-bilan-001"
FIXTURE_SLUG = "fixture-de-test-pipeline-ingestion"


@pytest_asyncio.fixture
async def patched_db(migrated_db: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    """Patch get_session_maker dans tous les modules consommateurs."""
    from cc_api.clients import db as db_module
    from cc_api.routers import corpus as corpus_module
    from cc_api.services import ingest as ingest_module

    engine = create_async_engine(migrated_db, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    for mod in (db_module, ingest_module, corpus_module):
        monkeypatch.setattr(mod, "get_session_maker", lambda m=maker: m)
    monkeypatch.setattr(db_module, "get_engine", lambda: engine)
    try:
        yield
    finally:
        await engine.dispose()


@pytest.fixture
def patched_qdrant(qdrant_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch get_qdrant dans le service ingest + module clients."""
    from cc_api.clients import qdrant as qdrant_module
    from cc_api.services import ingest as ingest_module

    for mod in (qdrant_module, ingest_module):
        monkeypatch.setattr(mod, "get_qdrant", lambda c=qdrant_client: c)


@pytest.fixture
def patched_embed(mock_embed_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch get_embed_client dans le service ingest + module clients."""
    from cc_api.clients import embed as embed_module
    from cc_api.services import ingest as ingest_module

    for mod in (embed_module, ingest_module):
        monkeypatch.setattr(mod, "get_embed_client", lambda c=mock_embed_client: c)


@pytest_asyncio.fixture
async def http_client(app: Any) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_get_corpus_empty_returns_empty_list(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
) -> None:
    resp = await http_client.get("/corpus")
    assert resp.status_code == 200
    body = resp.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1


async def test_admin_ingest_dev_then_get_corpus_shows_entry(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
    clean_qdrant: None,
    canonical_tei_path: Path,
) -> None:
    ingest_resp = await http_client.post("/admin/ingest", json={"path": str(canonical_tei_path)})
    assert ingest_resp.status_code == 200, ingest_resp.text
    ingest_body = ingest_resp.json()
    assert ingest_body["wasDuplicate"] is False
    assert ingest_body["nChunks"] >= 3
    assert ingest_body["nArticles"] == 1  # fallback fixture _seed
    assert ingest_body["ark"] == FIXTURE_ISSUE_ARK
    assert ingest_body["slug"] == FIXTURE_SLUG

    list_resp = await http_client.get("/corpus")
    assert list_resp.status_code == 200
    items = list_resp.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["title"].startswith("Fixture")
    assert item["slug"] == FIXTURE_SLUG
    assert item["nArticles"] == 1
    assert "insertedAt" in item


async def test_get_corpus_pagination(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
    clean_qdrant: None,
    canonical_tei_path: Path,
    tmp_path: Path,
) -> None:
    """Ingère 3 issues distinctes (ARK + titre/slug différents) et teste la pagination."""
    for i in range(1, 4):
        copy = tmp_path / f"bilan-page-{i:03d}.tei.xml"
        content = (
            canonical_tei_path.read_text(encoding="utf-8")
            .replace("ark:/00000/test-bilan-001", f"ark:/00000/test-bilan-page-{i:03d}")
            .replace(
                "Fixture de test — pipeline ingestion",
                f"Fixture de test — page {i:03d}",
            )
        )
        copy.write_text(content, encoding="utf-8")
        resp = await http_client.post("/admin/ingest", json={"path": str(copy)})
        assert resp.status_code == 200, resp.text

    page1 = await http_client.get("/corpus?page=1&size=2")
    assert page1.status_code == 200
    body1 = page1.json()
    assert body1["total"] == 3
    assert len(body1["items"]) == 2

    page2 = await http_client.get("/corpus?page=2&size=2")
    body2 = page2.json()
    assert len(body2["items"]) == 1


async def test_get_issue_detail_returns_404_unknown_slug(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
) -> None:
    resp = await http_client.get("/corpus/inexistant-slug")
    assert resp.status_code == 404


async def test_get_issue_detail_after_ingest(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
    clean_qdrant: None,
    canonical_tei_path: Path,
) -> None:
    ingest = await http_client.post("/admin/ingest", json={"path": str(canonical_tei_path)})
    assert ingest.status_code == 200, ingest.text
    issue_slug = ingest.json()["slug"]

    resp = await http_client.get(f"/corpus/{issue_slug}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["slug"] == issue_slug
    assert body["ark"] == FIXTURE_ISSUE_ARK
    assert "CC0" in body["license"]
    assert isinstance(body["articles"], list)
    assert len(body["articles"]) == 1
    article = body["articles"][0]
    assert article["slug"] == FIXTURE_SLUG  # fallback : article slug = slugify(title)
    assert article["author"]  # ArticleSummary porte 'author' (pas IssueSummary)


async def test_get_article_detail_after_ingest(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
    clean_qdrant: None,
    canonical_tei_path: Path,
) -> None:
    """ArticleDetail expose nParagraphs + paragraphes reconstruits depuis chunks."""
    ingest = await http_client.post("/admin/ingest", json={"path": str(canonical_tei_path)})
    issue_slug = ingest.json()["slug"]
    article_slug = FIXTURE_SLUG  # fallback : même slug

    resp = await http_client.get(f"/corpus/{issue_slug}/{article_slug}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["slug"] == article_slug
    assert body["ark"] == f"{FIXTURE_ISSUE_ARK}/{FIXTURE_SLUG}"
    assert body["nParagraphs"] >= 3
    assert isinstance(body["paragraphs"], list)
    assert len(body["paragraphs"]) >= 3
    # author = AuthorOut sérialisé
    assert body["author"]["displayName"]


async def test_get_article_detail_404_unknown_article(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
    clean_qdrant: None,
    canonical_tei_path: Path,
) -> None:
    ingest = await http_client.post("/admin/ingest", json={"path": str(canonical_tei_path)})
    issue_slug = ingest.json()["slug"]
    resp = await http_client.get(f"/corpus/{issue_slug}/inexistant-article")
    assert resp.status_code == 404


async def test_admin_ingest_invalid_path_returns_422(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
) -> None:
    resp = await http_client.post("/admin/ingest", json={"path": "/nonexistent.tei.xml"})
    assert resp.status_code == 422


async def test_admin_ingest_invalid_tei_returns_422(
    http_client: httpx.AsyncClient,
    patched_db: None,
    patched_qdrant: None,
    patched_embed: None,
    clean_db: None,
    clean_qdrant: None,
) -> None:
    invalid = (
        Path(__file__).resolve().parents[4]
        / "packages"
        / "corpus-tools"
        / "tests"
        / "fixtures"
        / "bilan-invalid-no-ark.tei.xml"
    )
    resp = await http_client.post("/admin/ingest", json={"path": str(invalid)})
    assert resp.status_code == 422
    assert "ark" in resp.text.lower()


def test_admin_ingest_refused_outside_dev(client: Any, monkeypatch: Any) -> None:
    """En env non-dev, /admin/ingest renvoie 403 (Depends(require_dev)).

    Note : `app` est créée avec CC_API_ENV=dev (cf. fixture conftest), donc
    le router admin est monté. On simule prod en patchant settings.env juste
    pour la dépendance — le router reste monté mais require_dev refuse.
    """
    from cc_api.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "env", "prod")
    resp = client.post("/admin/ingest", json={"path": "/x"})
    # Selon le moment où require_dev lit settings.env :
    # - 403 si la dépendance bloque avant le handler.
    # - 404 si le router n'est pas monté (env prod au boot).
    assert resp.status_code in (403, 404)

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures partagées des suites eval RAG (DeepEval + RAGAS).

Toutes les fixtures de ce conftest sont coûteuses (génération Claude via API +
serveur cc-embed local + Qdrant testcontainer + corpus Bilan réel ingéré).
Elles sont implicitement marquées `pytest.mark.expensive` sur tous les tests
`eval/`.

Si `ANTHROPIC_API_KEY` est absente, ou si le serveur cc-embed est injoignable,
les fixtures `skip` au lieu d'échouer brutalement (utile en CI nightly où la
présence des secrets et du GPU est conditionnelle).
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[4]
BILAN_REAL_CORPUS = REPO_ROOT / "corpus" / "bilan" / "bilan-001.tei.xml"
GOLDEN_QUESTIONS_PATH = Path(__file__).parent / "golden_questions.json"


def _require_eval_env() -> None:
    """Skip si ANTHROPIC_API_KEY est absente ou si le serveur cc-embed est injoignable."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY manquante — source `.env` avant `pytest -m expensive`.")
    import httpx
    from cc_api.core.settings import settings

    try:
        httpx.get(f"{settings.embed_server_url}/health", timeout=5.0).raise_for_status()
    except httpx.HTTPError as exc:
        pytest.skip(
            f"serveur cc-embed injoignable ({settings.embed_server_url}) : {exc}. "
            "Démarre-le avec `python -m cc_embed`."
        )


@pytest.fixture(scope="session")
def golden_questions() -> dict[str, Any]:
    """Charge `golden_questions.json` une fois par session."""
    return json.loads(GOLDEN_QUESTIONS_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def bilan_corpus_path() -> Path:
    """Chemin vers le corpus réel Bilan n°1 (5 articles)."""
    assert BILAN_REAL_CORPUS.exists(), f"corpus Bilan absent : {BILAN_REAL_CORPUS}"
    return BILAN_REAL_CORPUS


@pytest_asyncio.fixture
async def real_embed_client() -> AsyncIterator[Any]:
    """Vrai client d'embedding — serveur cc-embed local (Qwen3-Embedding sur GPU)."""
    _require_eval_env()
    from cc_api.clients.embed import LocalEmbedClient
    from cc_api.core.settings import settings

    client = LocalEmbedClient(settings.embed_server_url)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def real_rerank_client() -> AsyncIterator[Any]:
    """Vrai client de reranking — serveur cc-embed local (Qwen3-Reranker sur GPU)."""
    _require_eval_env()
    from cc_api.clients.embed import LocalRerankClient
    from cc_api.core.settings import settings

    client = LocalRerankClient(settings.embed_server_url)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def real_anthropic_client() -> AsyncIterator[Any]:
    """Vrai AnthropicClient — appelle Claude Opus 4.7 et coûte des tokens."""
    _require_eval_env()
    from cc_api.clients.anthropic import AnthropicClient

    model = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-7")
    client = AnthropicClient(api_key=os.environ["ANTHROPIC_API_KEY"], model=model)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def seeded_real_corpus(
    bilan_corpus_path: Path,
    clean_db: None,
    clean_qdrant: None,
    db_session: Any,
    qdrant_client: Any,
    real_embed_client: Any,
) -> AsyncIterator[dict[str, Any]]:
    """Ingère le vrai corpus Bilan n°1 (5 articles) dans Postgres + Qdrant.

    Embedding via le serveur cc-embed local (Qwen3, 5 articles x ~20-150 chunks
    selon longueur). Marqué expensive automatiquement.
    """
    _require_eval_env()
    from cc_api.services.ingest import ingest_issue

    ref = await ingest_issue(
        bilan_corpus_path,
        session=db_session,
        qdrant=qdrant_client,
        embed=real_embed_client,
    )
    yield {
        "ref": ref,
        "issue_slug": ref.slug,
        "n_articles": ref.n_articles,
        "n_chunks": ref.n_chunks,
        "article_slugs": [
            "note-liminaire",
            "introduction",
            "anniversaire-revolution-russe",
            "internationale-deux-trois-quarts",
            "bureau-international-information",
        ],
    }

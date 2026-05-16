# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clients HTTP du serveur cc-embed local (Qwen3 sur GPU).

`LocalEmbedClient` et `LocalRerankClient` parlent au serveur `cc-embed`
(`apps/embed-server`). Les protocoles `EmbedClient` / `RerankClient` typent
l'interface attendue par les pipelines d'ingestion et RAG.

Pas de fallback : si le serveur local est indisponible, le pipeline échoue
bruyamment — c'est volontaire, un embedding silencieusement dégradé corromprait
l'espace vectoriel du corpus. Aucun service d'embedding tiers (jamais Voyage).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol, runtime_checkable

import httpx

from cc_api.core.logging import get_logger
from cc_api.core.settings import settings

log = get_logger(__name__)

# Embedding d'un article ou d'une query : le serveur sérialise les lots GPU,
# une requête peut donc attendre derrière une autre — timeout généreux.
EMBED_TIMEOUT_S = 300.0


class EmbedServerError(RuntimeError):
    """Erreur non récupérable du serveur cc-embed (HTTP non-200 ou transport)."""


@dataclass(frozen=True)
class RerankHit:
    """Résultat d'un rerank pour un document : index d'origine + score."""

    index: int
    score: float


@runtime_checkable
class EmbedClient(Protocol):
    """Interface d'un client d'embedding (implémentée par `LocalEmbedClient`)."""

    async def embed_batch(
        self, texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]]: ...

    async def aclose(self) -> None: ...


@runtime_checkable
class RerankClient(Protocol):
    """Interface d'un client de reranking (implémentée par `LocalRerankClient`)."""

    async def rerank(
        self, *, query: str, documents: list[str], top_k: int = 5
    ) -> list[RerankHit]: ...

    async def aclose(self) -> None: ...


class LocalEmbedClient:
    """Client HTTP du endpoint `/embed` du serveur cc-embed (Qwen3-Embedding)."""

    def __init__(
        self, base_url: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url: str = base_url.rstrip("/")
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=EMBED_TIMEOUT_S)
        self._owns_client: bool = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> LocalEmbedClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def embed_batch(
        self, texts: list[str], *, input_type: str = "document"
    ) -> list[list[float]]:
        """Embedde une liste de textes. `input_type` ∈ {document, query}."""
        if not texts:
            return []
        try:
            resp = await self._client.post(
                f"{self.base_url}/embed",
                json={"texts": texts, "input_type": input_type},
            )
        except httpx.RequestError as exc:
            raise EmbedServerError(f"erreur transport cc-embed /embed : {exc}") from exc
        if resp.status_code != 200:
            raise EmbedServerError(
                f"cc-embed /embed a renvoyé {resp.status_code} : {resp.text[:200]}"
            )
        return list(resp.json()["embeddings"])


class LocalRerankClient:
    """Client HTTP du endpoint `/rerank` du serveur cc-embed (Qwen3-Reranker)."""

    def __init__(
        self, base_url: str, *, client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url: str = base_url.rstrip("/")
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=EMBED_TIMEOUT_S)
        self._owns_client: bool = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> LocalRerankClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def rerank(
        self, *, query: str, documents: list[str], top_k: int = 5
    ) -> list[RerankHit]:
        """Retourne les `top_k` documents triés par pertinence descendante.

        L'`index` retourné réfère à la position dans `documents` original.
        """
        if not documents:
            return []
        try:
            resp = await self._client.post(
                f"{self.base_url}/rerank",
                json={
                    "query": query,
                    "documents": documents,
                    "top_k": min(top_k, len(documents)),
                },
            )
        except httpx.RequestError as exc:
            raise EmbedServerError(f"erreur transport cc-embed /rerank : {exc}") from exc
        if resp.status_code != 200:
            raise EmbedServerError(
                f"cc-embed /rerank a renvoyé {resp.status_code} : {resp.text[:200]}"
            )
        return [
            RerankHit(index=item["index"], score=item["score"])
            for item in resp.json()["results"]
        ]


@lru_cache(maxsize=1)
def get_embed_client() -> EmbedClient:
    """Singleton client d'embedding — serveur cc-embed local."""
    return LocalEmbedClient(settings.embed_server_url)


@lru_cache(maxsize=1)
def get_rerank_client() -> RerankClient:
    """Singleton client de reranking — serveur cc-embed local."""
    return LocalRerankClient(settings.embed_server_url)

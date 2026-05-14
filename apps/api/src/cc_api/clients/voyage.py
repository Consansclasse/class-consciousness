# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client Voyage AI — embeddings `voyage-4` (1024 dims).

Pas de fallback : si Voyage est indisponible, le pipeline échoue bruyamment.
Retry exponentiel sur 5xx (3 tentatives max). Pas de retry sur 4xx.
"""

from __future__ import annotations

import asyncio
from functools import lru_cache

import httpx

from cc_api.core.logging import get_logger
from cc_api.core.settings import settings

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MAX_BATCH = 128
MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE = 0.5

log = get_logger(__name__)


class VoyageError(RuntimeError):
    """Toute erreur Voyage non récupérable (4xx, 5xx épuisé, transport)."""


class VoyageClient:
    """Client minimaliste pour `POST /v1/embeddings`."""

    def __init__(
        self,
        api_key: str | None,
        model: str = "voyage-4",
        *,
        client: httpx.AsyncClient | None = None,
        max_retries: int = MAX_RETRIES,
        backoff_base: float = DEFAULT_BACKOFF_BASE,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "VOYAGE_API_KEY manquant : exporter la variable d'env ou la passer à VoyageClient"
            )
        self.api_key: str = api_key
        self.model: str = model
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=30.0)
        self._owns_client: bool = client is None
        self._max_retries: int = max_retries
        self._backoff_base: float = backoff_base

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> VoyageClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embedde un lot quelconque de textes en respectant la limite Voyage (128)."""
        if not texts:
            return []
        result: list[list[float]] = []
        for i in range(0, len(texts), MAX_BATCH):
            batch = texts[i : i + MAX_BATCH]
            result.extend(await self._embed_one_request(batch))
        return result

    async def _embed_one_request(self, batch: list[str]) -> list[list[float]]:
        payload = {"input": batch, "model": self.model}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_status: int | None = None
        last_text: str = ""
        for attempt in range(self._max_retries):
            try:
                resp = await self._client.post(VOYAGE_URL, json=payload, headers=headers)
            except httpx.RequestError as exc:
                if attempt == self._max_retries - 1:
                    raise VoyageError(f"erreur transport Voyage : {exc}") from exc
                await asyncio.sleep(self._backoff_base * (2**attempt))
                continue

            if 500 <= resp.status_code < 600:
                last_status = resp.status_code
                last_text = resp.text
                if attempt == self._max_retries - 1:
                    raise VoyageError(
                        f"Voyage 5xx épuisé après {self._max_retries} tentatives "
                        f"(dernier statut={last_status}) : {last_text[:200]}"
                    )
                await asyncio.sleep(self._backoff_base * (2**attempt))
                continue

            if 400 <= resp.status_code < 500:
                raise VoyageError(
                    f"Voyage {resp.status_code} (pas de retry sur 4xx) : {resp.text[:200]}"
                )

            data = resp.json()
            return [item["embedding"] for item in data["data"]]

        raise VoyageError(
            f"Voyage : flux inattendu (dernier statut={last_status}) — vérifier les logs"
        )


@lru_cache(maxsize=1)
def get_voyage_client() -> VoyageClient:
    """Singleton Voyage construit depuis les settings."""
    return VoyageClient(api_key=settings.voyage_api_key, model=settings.voyage_embed_model)

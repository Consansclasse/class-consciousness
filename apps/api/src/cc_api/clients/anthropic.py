# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client Anthropic — wrapper minimal avec prompt caching ephemeral.

Le prompt système et le contexte RAG (les 5 chunks reranked) sont marqués
`cache_control={"type":"ephemeral"}`, ce qui économise jusqu'à 90% des tokens
input sur les sessions où plusieurs questions partagent le même contexte.

Pas de fallback. Pas de retry sur 4xx. Retry exponentiel sur 5xx (Anthropic SDK
gère déjà ça en interne via `max_retries`, on configure simplement le seuil).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import cast

from anthropic import AsyncAnthropic

from cc_api.core.logging import get_logger
from cc_api.core.settings import settings

log = get_logger(__name__)


@dataclass(frozen=True)
class GenerationUsage:
    """Compteurs de tokens retournés par l'API."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass(frozen=True)
class GenerationResult:
    """Réponse brute du LLM + usage."""

    text: str
    model: str
    usage: GenerationUsage
    stop_reason: str | None


class AnthropicClient:
    """Client async pour `claude-opus-4-7` (défaut) avec prompt caching."""

    def __init__(
        self,
        api_key: str | None,
        model: str,
        *,
        client: AsyncAnthropic | None = None,
        max_retries: int = 5,
    ) -> None:
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY manquant : exporter la variable d'env "
                "ou la passer à AnthropicClient"
            )
        self.api_key: str = api_key
        self.model: str = model
        self._client: AsyncAnthropic = client or AsyncAnthropic(
            api_key=api_key, max_retries=max_retries
        )
        self._owns_client: bool = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()

    async def __aenter__(self) -> AnthropicClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def generate(
        self,
        *,
        system: str,
        context: str,
        question: str,
        max_tokens: int = 1024,
        temperature: float = 0.0,
    ) -> GenerationResult:
        """Génère une réponse à `question` avec `system` + `context` mis en cache."""
        response = await self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                },
            ],
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": context,
                            "cache_control": {"type": "ephemeral"},
                        },
                        {"type": "text", "text": question},
                    ],
                },
            ],
        )
        # `content` est une liste de blocs ; on prend le 1er bloc texte.
        text_parts: list[str] = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
        text = "\n".join(text_parts)
        usage = GenerationUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cache_creation_input_tokens=cast(
                int, getattr(response.usage, "cache_creation_input_tokens", 0) or 0
            ),
            cache_read_input_tokens=cast(
                int, getattr(response.usage, "cache_read_input_tokens", 0) or 0
            ),
        )
        log.info(
            "anthropic.generate",
            model=self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read=usage.cache_read_input_tokens,
            cache_creation=usage.cache_creation_input_tokens,
            stop_reason=response.stop_reason,
        )
        return GenerationResult(
            text=text,
            model=self.model,
            usage=usage,
            stop_reason=response.stop_reason,
        )


@lru_cache(maxsize=1)
def get_anthropic_client() -> AnthropicClient:
    """Singleton Anthropic construit depuis les settings."""
    return AnthropicClient(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

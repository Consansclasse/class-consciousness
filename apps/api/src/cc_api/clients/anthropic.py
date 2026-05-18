# SPDX-License-Identifier: AGPL-3.0-or-later
"""Client Anthropic — génération RAG et juge d'ancrage, en sortie structurée.

Deux passages, tous deux en **tool-use forcé** (`tool_choice`) : le modèle ne
répond pas en prose libre mais remplit un schéma JSON validé par l'API. C'est le
choix de robustesse central du pipeline — il supprime tout re-parsing fragile :

- `generate` → schéma `rediger_reponse` : la dissertation arrive déjà découpée
  en paragraphes et en phrases, chaque phrase portant explicitement ses
  `citations` (source_ids) et ses `citations_directes` (fragments cités mot pour
  mot). Aucune segmentation devinée côté serveur.
- `judge` → schéma `rendre_verdicts` : un verdict d'entailment par phrase, dans
  une liste typée. Aucun `json.loads` best-effort. Un ré-essai en cas d'échec.

Le prompt système et le contexte RAG sont marqués `cache_control` ephemeral.
Retry exponentiel sur 5xx délégué au SDK Anthropic (`max_retries`).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

from anthropic import AsyncAnthropic

from cc_api.core.logging import get_logger
from cc_api.core.settings import settings

log = get_logger(__name__)


# --- Schémas d'outils (tool-use forcé) --------------------------------------

_PHRASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "texte": {
            "type": "string",
            "description": (
                "Une phrase de la dissertation, en prose, SANS marqueur de "
                "citation. Les citations littérales y figurent entre « »."
            ),
        },
        "citations": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "source_ids EXACTS des passages du contexte qui soutiennent "
                "cette phrase. ['none'] pour la phrase de refus."
            ),
        },
        "citations_directes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Chaque fragment de `texte` reproduit MOT POUR MOT depuis un "
                "passage cité (le contenu entre « »), sans les guillemets. "
                "Liste vide si la phrase ne contient pas de citation directe."
            ),
        },
    },
    "required": ["texte", "citations", "citations_directes"],
}

_REDIGER_TOOL: dict[str, Any] = {
    "name": "rediger_reponse",
    "description": (
        "Enregistre la dissertation d'explication de texte : une liste de "
        "paragraphes, chaque paragraphe étant une liste de phrases ancrées."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "paragraphes": {
                "type": "array",
                "description": "Les paragraphes de la dissertation, dans l'ordre.",
                "items": {
                    "type": "object",
                    "properties": {
                        "phrases": {
                            "type": "array",
                            "items": _PHRASE_SCHEMA,
                        },
                    },
                    "required": ["phrases"],
                },
            },
        },
        "required": ["paragraphes"],
    },
}

_DECOMPOSER_TOOL: dict[str, Any] = {
    "name": "decomposer_question",
    "description": (
        "Enregistre les sous-questions de recherche qui, ensemble, couvrent "
        "tous les angles de la question posée."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sous_questions": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "2 à 4 sous-questions de recherche distinctes et "
                    "complémentaires. Si la question est déjà atomique, une seule."
                ),
            },
        },
        "required": ["sous_questions"],
    },
}

_VERDICT_TOOL: dict[str, Any] = {
    "name": "rendre_verdicts",
    "description": (
        "Rend un verdict d'ancrage sémantique pour chaque phrase soumise."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "Index de la phrase jugée.",
                        },
                        "verdict": {
                            "type": "string",
                            "enum": ["ENTAILED", "NOT_ENTAILED", "CONTRADICTED"],
                        },
                        "justification": {
                            "type": "string",
                            "description": "Justification brève du verdict.",
                        },
                    },
                    "required": ["index", "verdict", "justification"],
                },
            },
        },
        "required": ["verdicts"],
    },
}


# --- Types de retour --------------------------------------------------------


@dataclass(frozen=True)
class GenerationUsage:
    """Compteurs de tokens retournés par l'API."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass(frozen=True)
class GeneratedPhrase:
    """Une phrase de la réponse, telle qu'émise par le LLM (sortie structurée)."""

    texte: str
    citations: list[str]
    citations_directes: list[str]


@dataclass(frozen=True)
class GeneratedAnswer:
    """Réponse structurée : paragraphes de phrases + usage."""

    paragraphes: list[list[GeneratedPhrase]]
    model: str
    usage: GenerationUsage


@dataclass(frozen=True)
class JudgeVerdict:
    """Verdict brut du juge pour une phrase (index dans la liste soumise)."""

    index: int
    verdict: str  # ENTAILED | NOT_ENTAILED | CONTRADICTED
    justification: str


class AnthropicError(RuntimeError):
    """Le modèle n'a pas produit la sortie structurée attendue."""


def _tool_input(response: Any, tool_name: str) -> dict[str, Any]:
    """Extrait l'`input` du bloc `tool_use` attendu. Lève `AnthropicError` sinon."""
    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == tool_name:
            return cast(dict[str, Any], block.input)
    raise AnthropicError(
        f"réponse sans bloc tool_use `{tool_name}` (stop_reason={response.stop_reason})"
    )


def _usage(response: Any) -> GenerationUsage:
    return GenerationUsage(
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_creation_input_tokens=cast(
            int, getattr(response.usage, "cache_creation_input_tokens", 0) or 0
        ),
        cache_read_input_tokens=cast(
            int, getattr(response.usage, "cache_read_input_tokens", 0) or 0
        ),
    )


class AnthropicClient:
    """Client async pour `claude-sonnet-4-6` (défaut), sortie structurée."""

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
        max_tokens: int = 8000,
    ) -> GeneratedAnswer:
        """Génère la dissertation en sortie structurée (tool-use forcé).

        Le `system` et le `context` sont mis en cache (ephemeral). Le modèle est
        contraint d'appeler `rediger_reponse` : la réponse arrive donc déjà
        découpée en phrases, sans segmentation devinée côté serveur.
        """
        # kwargs typés `Any` : les TypedDict de paramètres du SDK Anthropic ne
        # se laissent pas satisfaire par des littéraux ; le contrat réel est
        # garanti par les schémas `_REDIGER_TOOL` / `_VERDICT_TOOL`.
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "tools": [_REDIGER_TOOL],
            "tool_choice": {"type": "tool", "name": "rediger_reponse"},
            "messages": [
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
        }
        response = await self._client.messages.create(**params)
        data = _tool_input(response, "rediger_reponse")
        paragraphes: list[list[GeneratedPhrase]] = []
        for para in data.get("paragraphes", []):
            phrases = [
                GeneratedPhrase(
                    texte=str(p.get("texte", "")).strip(),
                    citations=[str(c) for c in p.get("citations", [])],
                    citations_directes=[str(q) for q in p.get("citations_directes", [])],
                )
                for p in para.get("phrases", [])
                if str(p.get("texte", "")).strip()
            ]
            if phrases:
                paragraphes.append(phrases)
        usage = _usage(response)
        log.info(
            "anthropic.generate",
            model=self.model,
            n_paragraphes=len(paragraphes),
            n_phrases=sum(len(p) for p in paragraphes),
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read=usage.cache_read_input_tokens,
        )
        if not paragraphes:
            raise AnthropicError("`rediger_reponse` n'a produit aucune phrase exploitable")
        return GeneratedAnswer(paragraphes=paragraphes, model=self.model, usage=usage)

    async def decompose(
        self,
        *,
        system: str,
        question: str,
        model: str | None = None,
        max_tokens: int = 1024,
    ) -> list[str]:
        """Décompose la question en sous-questions de recherche (tool-use forcé).

        Renvoie la liste des sous-questions ; vide si le modèle n'en produit
        aucune (l'appelant retombe alors sur la question d'origine).
        """
        params: dict[str, Any] = {
            "model": model or self.model,
            "max_tokens": max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "tools": [_DECOMPOSER_TOOL],
            "tool_choice": {"type": "tool", "name": "decomposer_question"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": question}]}],
        }
        response = await self._client.messages.create(**params)
        data = _tool_input(response, "decomposer_question")
        subs = [str(s).strip() for s in data.get("sous_questions", []) if str(s).strip()]
        log.info("anthropic.decompose", n_sous_questions=len(subs))
        return subs

    async def judge(
        self,
        *,
        system: str,
        payload: str,
        model: str | None = None,
        max_tokens: int = 4096,
    ) -> list[JudgeVerdict]:
        """2ᵉ passage « juge » — verdicts d'ancrage en tool-use forcé.

        Un ré-essai en cas de sortie inexploitable (très improbable avec un
        schéma forcé, mais le refus de réponse en dépend : on ne laisse pas une
        panne de parsing décider du verdict).
        """
        judge_model = model or self.model
        params: dict[str, Any] = {
            "model": judge_model,
            "max_tokens": max_tokens,
            "system": [
                {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
            ],
            "tools": [_VERDICT_TOOL],
            "tool_choice": {"type": "tool", "name": "rendre_verdicts"},
            "messages": [{"role": "user", "content": [{"type": "text", "text": payload}]}],
        }
        last_exc: Exception | None = None
        for attempt in (1, 2):
            response = await self._client.messages.create(**params)
            try:
                data = _tool_input(response, "rendre_verdicts")
                verdicts = [
                    JudgeVerdict(
                        index=int(v["index"]),
                        verdict=str(v["verdict"]).upper(),
                        justification=str(v.get("justification", "")),
                    )
                    for v in data["verdicts"]
                ]
            except (AnthropicError, KeyError, TypeError, ValueError) as exc:
                last_exc = exc
                log.warning("anthropic.judge_retry", attempt=attempt, error=str(exc))
                continue
            log.info("anthropic.judge", model=judge_model, n_verdicts=len(verdicts))
            return verdicts
        raise AnthropicError(f"juge sémantique : sortie inexploitable après 2 essais ({last_exc})")


@lru_cache(maxsize=1)
def get_anthropic_client() -> AnthropicClient:
    """Singleton Anthropic construit depuis les settings."""
    return AnthropicClient(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

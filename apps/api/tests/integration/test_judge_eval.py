# SPDX-License-Identifier: AGPL-3.0-or-later
"""Éval du juge sémantique — appels RÉELS à Claude (pas de mock).

La règle d'or anti-distorsion repose sur la capacité du juge à statuer
correctement ENTAILED / NOT_ENTAILED / CONTRADICTED. Les tests du pipeline
mockent le juge ; ce module mesure sa qualité réelle sur un petit jeu de cas
étalons — il faut une vraie clé API.

Ces tests sont `skip` si `ANTHROPIC_API_KEY` est absente, pour ne pas casser la
CI hors-ligne. Pour les exécuter :

    ANTHROPIC_API_KEY=sk-ant-... uv run pytest tests/integration/test_judge_eval.py

Étendre `_CASES` au fil des régressions observées sur le corpus réel.
"""

from __future__ import annotations

import os

import pytest
from cc_api.clients.anthropic import AnthropicClient
from cc_api.core.settings import settings
from cc_api.services.citation import _JUDGE_SYSTEM

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY") and not settings.anthropic_api_key,
    reason="ANTHROPIC_API_KEY absente — éval du juge sémantique ignorée",
)

# (affirmation, passage source, verdict attendu). Cas étalons : un cas net par
# verdict, dont l'exemple canonique de distorsion de citation-honest-vs-literal.
_CASES: list[tuple[str, str, str]] = [
    (
        "Le centrisme est un facteur qui conduit le prolétariat à la guerre.",
        "Le centrisme sera un facteur nécessaire pour conduire le prolétariat "
        "à la guerre et ainsi sa fonction s'épanouira totalement.",
        "ENTAILED",
    ),
    (
        "Le centrisme est apparu pour la première fois en Russie en 1917.",
        "Le centrisme sera un facteur nécessaire pour conduire le prolétariat "
        "à la guerre et ainsi sa fonction s'épanouira totalement.",
        "NOT_ENTAILED",
    ),
    (
        "La révolution est terminée.",
        "Les opportunistes prétendent que la révolution est terminée, mais ils "
        "se trompent gravement : la lutte se poursuit.",
        "CONTRADICTED",
    ),
]


def _payload(cases: list[tuple[str, str, str]]) -> str:
    blocks = [
        f"### Phrase {i}\nAffirmation : {claim}\n"
        f"Passage(s) cité(s) :\n--- src-{i} ---\n{source}\n"
        for i, (claim, source, _) in enumerate(cases)
    ]
    return "\n".join(blocks)


async def test_judge_classifies_canonical_cases() -> None:
    """Le juge réel doit classer correctement les 3 cas étalons."""
    client = AnthropicClient(
        api_key=settings.anthropic_api_key, model=settings.anthropic_judge_model
    )
    try:
        verdicts = await client.judge(system=_JUDGE_SYSTEM, payload=_payload(_CASES))
    finally:
        await client.aclose()

    by_index = {v.index: v.verdict for v in verdicts}
    assert len(by_index) == len(_CASES), f"verdicts manquants : {by_index}"
    for i, (claim, _, expected) in enumerate(_CASES):
        assert by_index.get(i) == expected, (
            f"cas {i} « {claim} » : attendu {expected}, obtenu {by_index.get(i)}"
        )

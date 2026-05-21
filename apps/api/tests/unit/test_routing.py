# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests unitaires du routage de complexité (G3) — heuristique pure, sans I/O.

`_classify_complexity` décide si une question justifie la décomposition (un
appel LLM) : « simple » → pipeline une passe ; « complexe » → décomposition.
La règle penche vers « complexe » au moindre indice de pluralité (rappel).
"""

from __future__ import annotations

import pytest

from cc_api.services.rag import _classify_complexity


@pytest.mark.parametrize(
    "question",
    [
        "Qu'est-ce que la plus-value ?",
        "Définis la dictature du prolétariat.",
        "Quel est le rôle du parti ?",
        "Que dit Bilan de l'État ?",
    ],
)
def test_question_simple(question: str) -> None:
    assert _classify_complexity(question) == "simple"


@pytest.mark.parametrize(
    "question",
    [
        # marqueur de comparaison
        "Compare les positions de Lénine et Trotsky sur l'État.",
        # marqueur d'évolution
        "Comment la conception de la révolution évolue-t-elle entre 1905 et 1917 ?",
        # marqueur de différence
        "En quoi Bilan diffère-t-il de l'Internationale communiste sur l'Espagne ?",
        # questions multiples
        "Qu'est-ce que l'impérialisme ? Et quel rapport avec la guerre ?",
        # énoncé long (≥ 16 mots)
        "Quelles sont les causes profondes que les auteurs du corpus avancent "
        "pour expliquer la défaite du prolétariat allemand au début des années trente ?",
    ],
)
def test_question_complexe(question: str) -> None:
    assert _classify_complexity(question) == "complexe"


def test_casse_insensible() -> None:
    """La classification ne dépend pas de la casse."""
    assert _classify_complexity("COMPARE A ET B") == "complexe"

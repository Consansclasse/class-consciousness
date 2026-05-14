# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests du pipeline RAG — squelette, dé-skippé quand le pipeline existe.

Règle d'or : aucune phrase produite par le pipeline ne doit exister sans citation
littéralement vérifiable dans le corpus source. Voir `.claude/rules/no-unsourced-rag.md`.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.mark.skip(reason="phase 0 — pipeline RAG pas encore implémenté")
def test_every_sentence_has_verified_citation(client: Any) -> None:
    """Chaque phrase d'une réponse RAG doit citer un source_id présent littéralement."""
    raise NotImplementedError


@pytest.mark.skip(reason="phase 0 — pipeline RAG pas encore implémenté")
def test_refuses_when_no_source_available(client: Any) -> None:
    """Quand aucun chunk pertinent n'est trouvé, le pipeline refuse plutôt que d'halluciner."""
    raise NotImplementedError


@pytest.mark.skip(reason="phase 0 — pipeline RAG pas encore implémenté")
def test_citations_use_csl_json(client: Any) -> None:
    """Les citations exposées suivent le standard CSL-JSON."""
    raise NotImplementedError

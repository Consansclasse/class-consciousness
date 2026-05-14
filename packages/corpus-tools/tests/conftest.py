# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures partagées pour les tests cc-corpus.

Résolveurs de chemins vers les fixtures TEI canoniques et invalides.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_FIXTURE = REPO_ROOT / "corpus" / "_seed" / "bilan-001.tei.xml"
LOCAL_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def canonical_tei_path() -> Path:
    assert CANONICAL_FIXTURE.exists(), f"fixture canonique absente : {CANONICAL_FIXTURE}"
    return CANONICAL_FIXTURE


@pytest.fixture(scope="session")
def invalid_no_ark_path() -> Path:
    path = LOCAL_FIXTURES / "bilan-invalid-no-ark.tei.xml"
    assert path.exists(), f"fixture invalide absente : {path}"
    return path


@pytest.fixture(scope="session")
def invalid_no_license_path() -> Path:
    path = LOCAL_FIXTURES / "bilan-invalid-no-license.tei.xml"
    assert path.exists(), f"fixture invalide absente : {path}"
    return path

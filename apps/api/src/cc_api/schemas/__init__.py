# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic v2 — contrats API."""

from __future__ import annotations

from cc_api.schemas.adhesion import (
    TIER_DEFAULT_AMOUNTS_CENTS,
    TIER_LABELS,
    AdhesionCheckoutIn,
    AdhesionCheckoutOut,
    AdhesionIntentStatusOut,
)
from cc_api.schemas.corpus import (
    ArticleDetail,
    ArticleSummary,
    AuthorOut,
    CorpusPage,
    IngestRequest,
    IngestResult,
    IssueDetail,
    IssueSummary,
)
from cc_api.schemas.qa import Citation, QaRequest, QaResponse, Sentence

__all__ = [
    "TIER_DEFAULT_AMOUNTS_CENTS",
    "TIER_LABELS",
    "AdhesionCheckoutIn",
    "AdhesionCheckoutOut",
    "AdhesionIntentStatusOut",
    "ArticleDetail",
    "ArticleSummary",
    "AuthorOut",
    "Citation",
    "CorpusPage",
    "IngestRequest",
    "IngestResult",
    "IssueDetail",
    "IssueSummary",
    "QaRequest",
    "QaResponse",
    "Sentence",
]

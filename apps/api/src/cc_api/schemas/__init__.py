# SPDX-License-Identifier: AGPL-3.0-or-later
"""Schemas Pydantic v2 — contrats API."""

from __future__ import annotations

from cc_api.schemas.corpus import (
    AuthorOut,
    ChunkOut,
    CorpusPage,
    IngestRequest,
    IngestResult,
    WorkOut,
    WorkSummary,
)

__all__ = [
    "AuthorOut",
    "ChunkOut",
    "CorpusPage",
    "IngestRequest",
    "IngestResult",
    "WorkOut",
    "WorkSummary",
]

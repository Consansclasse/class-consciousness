# SPDX-License-Identifier: AGPL-3.0-or-later
"""Services métier — orchestration au-dessus des clients et modèles."""

from __future__ import annotations

from cc_api.services.ingest import (
    COLLECTION,
    IngestSelfTestError,
    WorkRef,
    chunk_point_id,
    ingest_tei,
)

__all__ = [
    "COLLECTION",
    "IngestSelfTestError",
    "WorkRef",
    "chunk_point_id",
    "ingest_tei",
]

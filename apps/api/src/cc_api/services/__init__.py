# SPDX-License-Identifier: AGPL-3.0-or-later
"""Services métier — orchestration au-dessus des clients et modèles."""

from __future__ import annotations

from cc_api.services.adhesion import AdhesionError, create_checkout, handle_stripe_event
from cc_api.services.citation import (
    CitationReport,
    CitationVerdict,
    SentenceVerdict,
    assemble_answer,
    verify_response,
)
from cc_api.services.ingest import (
    COLLECTION,
    IngestSelfTestError,
    IssueRef,
    chunk_point_id,
    ingest_issue,
)
from cc_api.services.rag import (
    RagResult,
    RerankedChunk,
    RetrievedChunk,
    answer_question,
)

__all__ = [
    "COLLECTION",
    "AdhesionError",
    "CitationReport",
    "CitationVerdict",
    "IngestSelfTestError",
    "IssueRef",
    "RagResult",
    "RerankedChunk",
    "RetrievedChunk",
    "SentenceVerdict",
    "answer_question",
    "assemble_answer",
    "chunk_point_id",
    "create_checkout",
    "handle_stripe_event",
    "ingest_issue",
    "verify_response",
]

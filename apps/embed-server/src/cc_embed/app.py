# SPDX-License-Identifier: AGPL-3.0-or-later
"""API HTTP du serveur cc-embed — endpoints `/embed`, `/rerank`, `/health`.

Le travail GPU (bloquant) est déporté dans un thread via `anyio.to_thread`
pour ne pas geler la boucle d'événements ; le verrou interne du moteur
sérialise de toute façon les lots GPU.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import structlog
import torch
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from cc_embed.config import settings
from cc_embed.engine import get_embedder, get_reranker

log = structlog.get_logger(__name__)


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1)
    input_type: str = Field(default="document")


class EmbedResponse(BaseModel):
    embeddings: list[list[float]]
    dim: int
    model: str


class RerankRequest(BaseModel):
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1)


class RerankResult(BaseModel):
    index: int
    score: float


class RerankResponse(BaseModel):
    results: list[RerankResult]
    model: str


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    # L'embedder est chargé dès le démarrage : l'ingestion en a besoin
    # immédiatement et on veut échouer bruyamment si le GPU est indisponible.
    await anyio.to_thread.run_sync(get_embedder)
    yield


app = FastAPI(title="cc-embed", version="0.0.1", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    embedder = get_embedder()
    vram_mb = (
        round(torch.cuda.memory_allocated() / 2**20, 1) if torch.cuda.is_available() else None
    )
    return {
        "status": "ok",
        "device": settings.device,
        "embed_model": embedder.model_name,
        "embed_dim": embedder.dim,
        "rerank_model": settings.rerank_model,
        "vram_allocated_mb": vram_mb,
    }


@app.post("/embed", response_model=EmbedResponse)
async def embed(req: EmbedRequest) -> EmbedResponse:
    embedder = get_embedder()
    try:
        vectors = await anyio.to_thread.run_sync(embedder.embed, req.texts, req.input_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    log.info("embed.done", n_texts=len(req.texts), input_type=req.input_type)
    return EmbedResponse(embeddings=vectors, dim=embedder.dim, model=embedder.model_name)


@app.post("/rerank", response_model=RerankResponse)
async def rerank(req: RerankRequest) -> RerankResponse:
    reranker = await anyio.to_thread.run_sync(get_reranker)
    scores = await anyio.to_thread.run_sync(reranker.score, req.query, req.documents)
    ranked = sorted(
        (RerankResult(index=i, score=s) for i, s in enumerate(scores)),
        key=lambda r: r.score,
        reverse=True,
    )
    if req.top_k is not None:
        ranked = ranked[: req.top_k]
    log.info("rerank.done", n_documents=len(req.documents), n_returned=len(ranked))
    return RerankResponse(results=ranked, model=reranker.model_name)

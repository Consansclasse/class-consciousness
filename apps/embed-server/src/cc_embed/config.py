# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration du serveur cc-embed (variables d'environnement `CC_EMBED_*`)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CC_EMBED_", env_file=".env", extra="ignore")

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8001)
    log_level: str = Field(default="INFO")
    # En prod, cc-embed tourne sur le CPU du VPS (pas de GPU). `device=cuda`
    # reste possible pour le développement local sur une machine équipée.
    device: str = Field(default="cpu")

    # Embeddings — Qwen3-Embedding-0.6B, pooling dernier token + normalisation L2.
    # Le 0.6B est le format qui tient et tourne sur un CPU de VPS ; le 8B
    # exigerait un GPU (voir docs/adr/0008-architecture-embedding-vps-cpu.md).
    embed_model: str = Field(default="Qwen/Qwen3-Embedding-0.6B")
    embed_quant: str = Field(default="none")  # 8bit | 4bit | none — 8bit/4bit = GPU only
    embed_max_tokens: int = Field(default=2048)
    # Batching par budget de tokens : les chunks (triés par longueur) sont
    # empaquetés jusqu'à ce que `nb x longueur_paddée` atteigne le budget, dans
    # la limite de `embed_batch_max`.
    embed_token_budget: int = Field(default=4096)
    embed_batch_max: int = Field(default=48)

    # Reranking — Qwen3-Reranker-0.6B, score yes/no d'une paire (requête, document).
    # Chargé paresseusement : l'ingestion n'a besoin que de l'embedder.
    rerank_model: str = Field(default="Qwen/Qwen3-Reranker-0.6B")
    rerank_quant: str = Field(default="none")  # 8bit | 4bit | none — 8bit/4bit = GPU only
    rerank_device: str = Field(default="cpu")  # cuda | cpu
    rerank_max_tokens: int = Field(default=1024)
    rerank_batch_size: int = Field(default=1)


settings = EmbedSettings()

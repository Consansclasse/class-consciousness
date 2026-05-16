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
    device: str = Field(default="cuda")

    # Embeddings — Qwen3-Embedding, pooling dernier token + normalisation L2.
    embed_model: str = Field(default="Qwen/Qwen3-Embedding-8B")
    embed_quant: str = Field(default="8bit")  # 8bit | 4bit | none
    embed_max_tokens: int = Field(default=2048)
    # Batching par budget de tokens : les chunks (triés par longueur) sont
    # empaquetés jusqu'à ce que `nb x longueur_paddée` atteigne le budget, dans
    # la limite de `embed_batch_max`. Le budget réplique le plafond mémoire
    # éprouvé du lot 8x512 ; les chunks courts — majoritaires dans Bilan — sont
    # donc bien plus nombreux par passage GPU qu'avec un lot de taille fixe.
    embed_token_budget: int = Field(default=4096)
    embed_batch_max: int = Field(default=48)

    # Reranking — Qwen3-Reranker, score yes/no d'une paire (requête, document).
    # Chargé paresseusement : l'ingestion n'a besoin que de l'embedder.
    # Modèle 0.6B : seul format assez petit pour cohabiter en VRAM avec
    # l'embedder 8B 8-bit sur un GPU 12 Go (le 4B provoque un CUDA OOM).
    rerank_model: str = Field(default="Qwen/Qwen3-Reranker-0.6B")
    rerank_quant: str = Field(default="8bit")  # 8bit | 4bit | none
    rerank_device: str = Field(default="cuda")  # cuda | cpu (cpu impose quant=none)
    # Sur GPU 12 Go, l'embedder 8B ne laisse que ~0,4 Gio : le reranking se fait
    # paire par paire (batch 1) et la longueur est plafonnée bas pour borner les
    # activations — sinon CUDA OOM sur des chunks longs.
    rerank_max_tokens: int = Field(default=1024)
    rerank_batch_size: int = Field(default=1)


settings = EmbedSettings()

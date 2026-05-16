#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Harnais d'évaluation du pipeline RAG — scénarios utilisateur réalistes.

Exécute, pour une batterie de questions d'utilisateur de l'archive, le pipeline
embed (input_type=query) → Qdrant top-k → reranking Qwen3 local, et dumpe le
contexte reranked dans `/tmp/eval_rag.json`. La génération de la réponse sourcée
et la vérification citationnelle (`cc_api.services.citation`) suivent.

Usage : set -a && source .env && set +a && uv run python scripts/eval_rag.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if _ENV_PATH.exists():
    for _line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _, _v = _line.partition("=")
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

QUESTIONS: list[dict[str, str]] = [
    {"id": "U1", "question": "Pourquoi l'Internationale communiste a-t-elle degenere ?"},
    {"id": "U2", "question": "Qu'est-il arrive au proletariat espagnol pendant la guerre civile ?"},
    {"id": "U3", "question": "Bilan defendait-il l'URSS comme un Etat ouvrier ?"},
    {"id": "U4", "question": "Quelle etait la position de Bilan sur le Front populaire ?"},
    {"id": "U5",
     "question": "Pourquoi Bilan s'opposait-il a la creation d'une IVe Internationale ?"},
    {"id": "U6", "question": "Qu'est-ce qu'une fraction et quel est son role selon Bilan ?"},
    {"id": "U7", "question": "Que reproche-t-on a la these de l'Etat proletarien defendue par "
                              "Bilan ?"},
    {"id": "U8", "question": "Le fascisme et la democratie sont-ils deux formes opposees ?"},
    {"id": "U9", "question": "Quelles lecons Bilan tire-t-il des defaites du proletariat ?"},
]

K_RETRIEVE = 20
K_RERANK = 6


async def main() -> int:
    from cc_api.clients.embed import get_embed_client, get_rerank_client
    from cc_api.clients.qdrant import get_qdrant
    from cc_api.services.rag import COLLECTION, RerankedChunk, _build_context, _source_id

    embed = get_embed_client()
    reranker = get_rerank_client()
    qdrant = get_qdrant()
    results: list[dict[str, object]] = []

    for q in QUESTIONS:
        emb = (await embed.embed_batch([q["question"]], input_type="query"))[0]
        hits = await qdrant.query_points(
            collection_name=COLLECTION, query=emb, limit=K_RETRIEVE, with_payload=True
        )
        retrieved = [dict(p.payload or {}) | {"_score": p.score or 0.0} for p in hits.points]
        documents = [r.get("text", "") for r in retrieved]
        rerank_hits = await reranker.rerank(
            query=q["question"], documents=documents, top_k=K_RERANK
        )
        chunks = [
            RerankedChunk(
                source_id=_source_id(retrieved[h.index]),
                text=retrieved[h.index].get("text", ""),
                retrieval_score=float(retrieved[h.index]["_score"]),
                rerank_score=h.score,
                payload=retrieved[h.index],
            )
            for h in rerank_hits
        ]
        results.append(
            {
                "id": q["id"],
                "question": q["question"],
                "chunks": [
                    {
                        "source_id": c.source_id,
                        "rerank_score": round(c.rerank_score, 5),
                        "cosine_score": round(c.retrieval_score, 4),
                        "article_title": c.payload.get("article_title"),
                        "author_name": c.payload.get("author_name"),
                        "text": c.text,
                    }
                    for c in chunks
                ],
                "context": _build_context(chunks),
            }
        )
        top = [f"{c.rerank_score:.3f}" for c in chunks]
        print(f"[{q['id']}] rerank_scores={top}", file=sys.stderr)

    await embed.aclose()
    await reranker.aclose()
    out = Path("/tmp/eval_rag.json")  # noqa: S108 — artefact d'éval jetable
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n-> {out} ({len(results)} questions)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

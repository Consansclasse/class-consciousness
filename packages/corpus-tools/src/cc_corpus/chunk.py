# SPDX-License-Identifier: AGPL-3.0-or-later
"""Chunker — découpe sémantique d'un TEI parsé en unités vectorisables.

Règle d'or : `full_text[chunk.char_start:chunk.char_end] == chunk.text` toujours.
Stratégie : 1 paragraphe = 1 chunk par défaut. Sous-découpe avec overlap si le
paragraphe dépasse `max_tokens`.

La sous-découpe travaille en caractères (offsets garantis exacts), avec un
mapping caractères ↔ tokens calculé par ratio sur le paragraphe entier.
Le `token_count` final est mesuré exactement sur chaque fenêtre via tiktoken.
"""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken

from cc_corpus.tei import Paragraph

DEFAULT_ENCODER = "cl100k_base"
DEFAULT_MAX_TOKENS = 800
DEFAULT_OVERLAP = 100


@dataclass(frozen=True)
class Chunk:
    idx: int
    text: str
    char_start: int
    char_end: int
    token_count: int


def split(
    paragraphs: list[Paragraph],
    *,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap: int = DEFAULT_OVERLAP,
    encoder_name: str = DEFAULT_ENCODER,
) -> list[Chunk]:
    """Découpe une séquence de paragraphes en chunks vectorisables.

    - paragraphes ≤ max_tokens : 1 chunk = 1 paragraphe (offsets identiques).
    - paragraphes > max_tokens : sous-découpe avec recouvrement `overlap` tokens.
    """
    if not paragraphs:
        return []
    if overlap >= max_tokens:
        raise ValueError(f"overlap ({overlap}) doit être < max_tokens ({max_tokens})")

    enc = tiktoken.get_encoding(encoder_name)
    chunks: list[Chunk] = []
    idx = 0

    for para in paragraphs:
        token_count = len(enc.encode(para.text))
        if token_count <= max_tokens:
            chunks.append(
                Chunk(
                    idx=idx,
                    text=para.text,
                    char_start=para.char_start,
                    char_end=para.char_end,
                    token_count=token_count,
                )
            )
            idx += 1
            continue

        # Sous-découpe — fenêtre en chars, ratio tokens→chars sur ce paragraphe.
        char_count = len(para.text)
        chars_per_token = char_count / token_count
        window_chars = max(1, int(max_tokens * chars_per_token))
        overlap_chars = max(1, int(overlap * chars_per_token))
        step = max(1, window_chars - overlap_chars)

        local = 0
        while local < char_count:
            local_end = min(local + window_chars, char_count)
            window_text = para.text[local:local_end]
            chunks.append(
                Chunk(
                    idx=idx,
                    text=window_text,
                    char_start=para.char_start + local,
                    char_end=para.char_start + local_end,
                    token_count=len(enc.encode(window_text)),
                )
            )
            idx += 1
            if local_end >= char_count:
                break
            local += step

    return chunks

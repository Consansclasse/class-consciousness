# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests unitaires du chunker.

Invariant absolu : full_text[chunk.char_start:chunk.char_end] == chunk.text.
1 paragraphe = 1 chunk par défaut. Sous-découpe avec overlap si > max_tokens.
"""

from __future__ import annotations

from itertools import pairwise

import tiktoken
from cc_corpus.chunk import split
from cc_corpus.tei import SEPARATOR, Paragraph


def _build(parts: list[str]) -> tuple[list[Paragraph], str]:
    paragraphs: list[Paragraph] = []
    cursor = 0
    for text in parts:
        paragraphs.append(Paragraph(text=text, char_start=cursor, char_end=cursor + len(text)))
        cursor += len(text) + len(SEPARATOR)
    full_text = SEPARATOR.join(parts)
    return paragraphs, full_text


def test_short_paragraph_yields_one_chunk() -> None:
    paragraphs, _full_text = _build(["Phrase courte. Encore une phrase. Et une dernière."])
    chunks = split(paragraphs)

    assert len(chunks) == 1
    assert chunks[0].text == paragraphs[0].text
    assert chunks[0].char_start == paragraphs[0].char_start
    assert chunks[0].char_end == paragraphs[0].char_end
    assert chunks[0].idx == 0
    assert chunks[0].token_count > 0


def test_long_paragraph_splits_with_overlap() -> None:
    # ~5000 chars de français → ~1500 tokens (ratio cl100k_base ≈ 0.3)
    big = (
        "Matérialisme historique et lutte des classes : le rapport entre infrastructure "
        "et superstructure conditionne l'ensemble des rapports sociaux de production. "
    ) * 30
    paragraphs, _full_text = _build([big])
    chunks = split(paragraphs, max_tokens=300, overlap=50)

    assert len(chunks) >= 2
    assert all(c.token_count > 0 for c in chunks)
    # chevauchement : chaque chunk (sauf le premier) doit recouvrir le précédent en chars
    for prev, curr in pairwise(chunks):
        assert curr.char_start < prev.char_end, "overlap absent entre chunks consécutifs"
        assert curr.char_start > prev.char_start, "non-progression"


def test_chunk_offsets_map_back_to_source() -> None:
    parts = [
        "Premier paragraphe court.",
        (
            "Deuxième paragraphe plus long, qui va potentiellement être sous-découpé "
            "selon le seuil de tokens choisi par le chunker. "
        )
        * 20,
        "Troisième paragraphe court.",
    ]
    paragraphs, full_text = _build(parts)
    chunks = split(paragraphs, max_tokens=200, overlap=40)

    for c in chunks:
        slice_ = full_text[c.char_start : c.char_end]
        assert slice_ == c.text, (
            f"invariant char_start/char_end cassé pour chunk idx={c.idx} : "
            f"attendu={c.text[:30]!r}, obtenu={slice_[:30]!r}"
        )


def test_token_count_uses_cl100k_base() -> None:
    paragraphs, _ = _build(["Une phrase courte pour mesurer les tokens."])
    chunks = split(paragraphs)

    enc = tiktoken.get_encoding("cl100k_base")
    expected = len(enc.encode(paragraphs[0].text))
    assert chunks[0].token_count == expected


def test_idx_is_zero_based_and_monotonic() -> None:
    parts = ["A.", "B.", "C.", "D."]
    paragraphs, _ = _build(parts)
    chunks = split(paragraphs)

    assert [c.idx for c in chunks] == list(range(len(chunks)))


def test_subdivision_preserves_typography() -> None:
    # cadratin, œ, accents, espaces fines
    big = (
        "Œuvres complètes — édition critique avec préface inédite. "
        "L'idéologie allemande conserve sa pertinence aujourd'hui. "
    ) * 25
    paragraphs, full_text = _build([big])
    chunks = split(paragraphs, max_tokens=200, overlap=30)

    assert len(chunks) >= 2
    # caractères Unicode préservés bit-à-bit dans tous les chunks
    for c in chunks:
        assert full_text[c.char_start : c.char_end] == c.text


def test_empty_paragraphs_list_returns_empty_chunks() -> None:
    assert split([]) == []


def test_chunks_cover_full_text_for_simple_case() -> None:
    parts = ["Premier.", "Deuxième.", "Troisième."]
    paragraphs, _full_text = _build(parts)
    chunks = split(paragraphs)

    # Chaque paragraphe court = 1 chunk : N chunks couvrent les N paragraphes
    assert len(chunks) == 3
    assert chunks[0].text == "Premier."
    assert chunks[1].text == "Deuxième."
    assert chunks[2].text == "Troisième."

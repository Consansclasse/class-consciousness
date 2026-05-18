# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de `services.citation` — vérification d'ancrage par phrase.

Ces tests sont en `integration/` parce qu'ils valident la règle d'or RAG du
projet, même s'ils ne touchent ni DB ni Qdrant.

Ils couvrent le **pré-classement local** (`_classify`) — la part déterministe,
sans LLM : UNSOURCED, REFUSED_BY_LLM, QUOTE_UNVERIFIED, source absente, et le
verdict provisoire « pending » d'une phrase qui passe le contrôle littéral.
Le juge sémantique (SUPPORTED / NOT_SUPPORTED / CONTRADICTED) est exercé de
bout en bout dans `test_pipeline_rag.py`.
"""

from __future__ import annotations

from cc_api.clients.anthropic import GeneratedPhrase
from cc_api.services.citation import (
    CitationVerdict,
    SentenceVerdict,
    _adaptive_threshold,
    _classify,
    _fragment_score,
    _normalize,
    assemble_answer,
)

CHUNKS = {
    "bilan-1/note:0": "La fraction défend l'unité ouvrière dans toutes les circonstances.",
    "bilan-2/intro:1": (
        "Le centrisme dispersait les réactions de classe provenant des antagonismes."
    ),
}


def _classify_phrase(
    texte: str, citations: list[str], directes: list[str] | None = None
) -> SentenceVerdict:
    phrase = GeneratedPhrase(texte=texte, citations=citations, citations_directes=directes or [])
    return _classify(phrase, 0, CHUNKS, 95)


# ---------------------------------------------------------------------------
# _classify — pré-classement déterministe
# ---------------------------------------------------------------------------


def test_classify_no_citation_marks_unsourced() -> None:
    v = _classify_phrase("Une phrase sans aucune citation.", [])
    assert v.verdict == CitationVerdict.UNSOURCED
    assert v.verified is False


def test_classify_refusal_marks_refused_by_llm() -> None:
    v = _classify_phrase("Je ne peux pas répondre à partir des sources disponibles.", ["none"])
    assert v.verdict == CitationVerdict.REFUSED_BY_LLM
    assert v.verified is True


def test_classify_unknown_source_marks_not_supported() -> None:
    v = _classify_phrase("Une analyse.", ["bilan-9/inconnu:99"])
    assert v.verdict == CitationVerdict.NOT_SUPPORTED
    assert "aucun chunk cité" in v.reason


def test_classify_direct_quote_absent_marks_quote_unverified() -> None:
    v = _classify_phrase(
        "Le texte affirme : « une formule jamais écrite ».",
        ["bilan-1/note:0"],
        ["une formule jamais écrite"],
    )
    assert v.verdict == CitationVerdict.QUOTE_UNVERIFIED
    assert "citation directe" in v.reason


def test_classify_direct_quote_literal_passes_to_judge() -> None:
    """Une citation directe littérale passe le contrôle local → verdict pending."""
    v = _classify_phrase(
        "Le texte affirme : « La fraction défend l'unité ouvrière ».",
        ["bilan-1/note:0"],
        ["La fraction défend l'unité ouvrière"],
    )
    assert v.reason == "pending"
    assert v.best_score == 100.0


def test_classify_direct_quote_typographic_variation_passes() -> None:
    """Variation typographique mineure (apostrophe courbe) tolérée."""
    v = _classify_phrase(
        "Le texte affirme : « La fraction défend l’unité ouvrière ».",  # noqa: RUF001
        ["bilan-1/note:0"],
        ["La fraction défend l’unité ouvrière"],  # noqa: RUF001
    )
    assert v.reason == "pending"


def test_classify_analytic_sentence_passes_to_judge() -> None:
    """Une phrase d'analyse (sans citation directe) part au juge sémantique."""
    v = _classify_phrase("La fraction adopte une position de principe.", ["bilan-1/note:0"])
    assert v.reason == "pending"


def test_classify_short_quote_substitution_rejected() -> None:
    """Sur un fragment court, le seuil monte à 100 : une substitution échoue."""
    v = _classify_phrase(
        "Le texte dit : « le centrisme rassemblait les réactions ».",
        ["bilan-2/intro:1"],
        ["le centrisme rassemblait les réactions"],
    )
    assert v.verdict == CitationVerdict.QUOTE_UNVERIFIED


# ---------------------------------------------------------------------------
# Helpers de contrôle littéral
# ---------------------------------------------------------------------------


def test_normalize_folds_typography_and_punctuation() -> None:
    assert _normalize("  « L’Unité ».  ") == "l'unité"  # noqa: RUF001


def test_adaptive_threshold_stricter_for_short_fragments() -> None:
    assert _adaptive_threshold("un deux trois quatre cinq six sept huit neuf dix", 95) == 95
    assert _adaptive_threshold("trois mots courts", 95) == 100


def test_fragment_score_exact_substring_is_100() -> None:
    assert _fragment_score("défend l'unité ouvrière", [CHUNKS["bilan-1/note:0"]]) == 100.0


# ---------------------------------------------------------------------------
# assemble_answer — reconstitution du texte
# ---------------------------------------------------------------------------


def _verdict(texte: str, paragraphe: int, verdict: CitationVerdict) -> SentenceVerdict:
    phrase = GeneratedPhrase(texte=texte, citations=["bilan-1/note:0"], citations_directes=[])
    return SentenceVerdict(phrase, paragraphe, verdict, 100.0, "test")


def test_assemble_answer_full_joins_all_paragraphs() -> None:
    verdicts = [
        _verdict("Phrase un.", 0, CitationVerdict.SUPPORTED),
        _verdict("Phrase deux.", 0, CitationVerdict.SUPPORTED),
        _verdict("Phrase trois.", 1, CitationVerdict.SUPPORTED),
    ]
    assert assemble_answer(verdicts, only_verified=False) == (
        "Phrase un. Phrase deux.\n\nPhrase trois."
    )


def test_assemble_answer_only_verified_drops_rejected() -> None:
    verdicts = [
        _verdict("Phrase vérifiée.", 0, CitationVerdict.SUPPORTED),
        _verdict("Phrase rejetée.", 0, CitationVerdict.NOT_SUPPORTED),
    ]
    out = assemble_answer(verdicts, only_verified=True)
    assert out == "Phrase vérifiée."

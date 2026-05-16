# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests de `services.citation` — vérification substring + fuzzy par phrase.

Ces tests sont en `integration/` parce qu'ils valident la règle d'or RAG du
projet (« aucune phrase sans citation littéralement vérifiable »), même s'ils
ne touchent ni DB ni Qdrant — c'est délibéré pour qu'ils s'exécutent toujours
dans le pipeline d'intégration.
"""

from __future__ import annotations

from cc_api.services.citation import (
    CitationVerdict,
    extract_citations,
    split_sentences,
    strip_citations,
    verify_response,
    verify_sentence,
)

# ---------------------------------------------------------------------------
# split_sentences
# ---------------------------------------------------------------------------


def test_split_sentences_basic() -> None:
    text = "Première phrase. Seconde phrase. Troisième !"
    assert split_sentences(text) == [
        "Première phrase.",
        "Seconde phrase.",
        "Troisième !",
    ]


def test_split_sentences_respects_french_abbreviations() -> None:
    """`M. Marx` ne doit pas casser la phrase au point après `M`."""
    text = "Selon M. Marx, le capital exploite. Cela reste vrai aujourd'hui."
    sentences = split_sentences(text)
    assert sentences == [
        "Selon M. Marx, le capital exploite.",
        "Cela reste vrai aujourd'hui.",
    ]


def test_split_sentences_respects_cf_etc_ibid() -> None:
    text = "Voir cf. l'analyse classique. Et aussi etc. les variantes. Mais ibid. p. 42 confirme."
    sentences = split_sentences(text)
    # `etc.` et `cf.` et `ibid.` et `p.` ne doivent pas casser.
    assert len(sentences) == 3
    assert sentences[0] == "Voir cf. l'analyse classique."
    assert sentences[1] == "Et aussi etc. les variantes."
    assert sentences[2] == "Mais ibid. p. 42 confirme."


def test_split_sentences_empty_input_returns_empty_list() -> None:
    assert split_sentences("") == []
    assert split_sentences("   \n\t  ") == []


# ---------------------------------------------------------------------------
# extract_citations / strip_citations
# ---------------------------------------------------------------------------


def test_extract_citations_finds_multiple() -> None:
    sentence = (
        "La fraction défend l'unité. [CITE:bilan-1/note:0] "
        "Cf. aussi le texte ultérieur. [CITE:bilan-1/intro:2]"
    )
    assert extract_citations(sentence) == [
        "bilan-1/note:0",
        "bilan-1/intro:2",
    ]


def test_extract_citations_returns_empty_for_no_markers() -> None:
    assert extract_citations("Phrase sans citation.") == []


def test_strip_citations_removes_markers_and_collapses_whitespace() -> None:
    sentence = "L'archive est ouverte. [CITE:bilan-1/note:0]   [CITE:bilan-1/intro:1]"
    assert strip_citations(sentence) == "L'archive est ouverte."


# ---------------------------------------------------------------------------
# verify_sentence — règle d'or
# ---------------------------------------------------------------------------


def test_verify_sentence_substring_exact_marks_verified() -> None:
    chunks = {"bilan-1/note:0": "La fraction défend l'unité ouvrière dans toutes circonstances."}
    sentence = "La fraction défend l'unité ouvrière. [CITE:bilan-1/note:0]"
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_VERIFIED
    assert v.best_score == 100.0
    assert "substring exact" in v.reason
    assert v.citations == ["bilan-1/note:0"]


def test_verify_sentence_fuzzy_above_threshold_marks_verified() -> None:
    """Une variation typographique mineure (apostrophe courbe vs droite, accent)
    doit passer le seuil fuzzy 95."""
    chunks = {
        "bilan-1/intro:0": (
            "Le matérialisme historique reste l'outil d'analyse central des marxistes."
        )
    }
    # Apostrophe typographique différente + ponctuation déplacée (volontaire).
    sentence = (
        "Le matérialisme historique reste l’outil d’analyse central des marxistes. "  # noqa: RUF001
        "[CITE:bilan-1/intro:0]"
    )
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_VERIFIED
    assert v.best_score >= 95.0


def test_verify_sentence_below_threshold_marks_unverified() -> None:
    """Paraphrase grossière → ne doit PAS être considérée comme vérifiée."""
    chunks = {
        "bilan-1/note:0": (
            "La fraction défend l'unité ouvrière dans toutes les circonstances historiques."
        )
    }
    sentence = "Les communistes adoptent une position défensive structurelle. [CITE:bilan-1/note:0]"
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_UNVERIFIED
    assert v.best_score < 95.0


def test_verify_sentence_no_citation_marks_unsourced() -> None:
    chunks = {"bilan-1/note:0": "Texte arbitraire dans le chunk source."}
    sentence = "Phrase sans aucune citation explicite."
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.UNSOURCED
    assert v.best_score == 0.0
    assert "aucune citation" in v.reason


def test_verify_sentence_cited_source_missing_marks_unverified() -> None:
    """Si la phrase cite un source_id qui n'est pas fourni dans `chunks`,
    on ne peut pas vérifier — verdict SOURCED_UNVERIFIED."""
    chunks = {"bilan-1/note:0": "Texte du note liminaire."}
    sentence = "La position est claire. [CITE:bilan-1/inconnu:99]"
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_UNVERIFIED


def test_verify_sentence_multiple_citations_first_match_wins() -> None:
    """Si plusieurs sources citées, au moins une qui valide suffit."""
    chunks = {
        "bilan-1/note:0": "Texte qui ne correspond pas à la phrase.",
        "bilan-1/intro:0": "La position fondamentale reste celle de l'unité ouvrière.",
    }
    sentence = (
        "La position fondamentale reste celle de l'unité ouvrière. "
        "[CITE:bilan-1/note:0] [CITE:bilan-1/intro:0]"
    )
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_VERIFIED


# ---------------------------------------------------------------------------
# verify_response — synthèse multi-phrases
# ---------------------------------------------------------------------------


def test_verify_response_all_verified_returns_all_verified_true() -> None:
    chunks = {
        "bilan-1/note:0": "Premier paragraphe avec le texte attendu A.",
        "bilan-1/note:1": "Second paragraphe avec le texte attendu B.",
    }
    response = (
        "Premier paragraphe avec le texte attendu A. [CITE:bilan-1/note:0] "
        "Second paragraphe avec le texte attendu B. [CITE:bilan-1/note:1]"
    )
    report = verify_response(response, chunks=chunks)
    assert report.all_verified is True
    assert report.n_sourced_verified == 2
    assert report.n_sourced_unverified == 0
    assert report.n_unsourced == 0
    assert report.refused_sentences == []


def test_verify_response_one_unsourced_sentence_blocks_all_verified() -> None:
    """La règle d'or : UNE phrase non sourcée suffit à invalider la réponse."""
    chunks = {"bilan-1/note:0": "Texte attendu présent dans le chunk."}
    response = (
        "Texte attendu présent dans le chunk. [CITE:bilan-1/note:0] "
        "Mais voici une phrase libre sans citation."
    )
    report = verify_response(response, chunks=chunks)
    assert report.all_verified is False
    assert report.n_sourced_verified == 1
    assert report.n_unsourced == 1
    assert len(report.refused_sentences) == 1
    assert "phrase libre sans citation" in report.refused_sentences[0]


def test_verify_response_empty_text_returns_not_verified() -> None:
    report = verify_response("", chunks={})
    assert report.all_verified is False
    assert report.sentences == []


# ---------------------------------------------------------------------------
# Refus explicite du LLM via [CITE:none]
# ---------------------------------------------------------------------------


def test_verify_sentence_refusal_marker_returns_refused_by_llm() -> None:
    """Une phrase avec [CITE:none] seul = refus explicite, verdict REFUSED_BY_LLM."""
    chunks = {"bilan-1/note:0": "Texte arbitraire."}
    sentence = "Je ne peux pas répondre à partir des sources disponibles. [CITE:none]"
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.REFUSED_BY_LLM
    assert v.citations == ["none"]
    assert "refus explicite" in v.reason


def test_verify_response_with_only_refusal_marks_all_verified() -> None:
    """Si la réponse n'est QUE la phrase de refus, all_verified=True
    (le refus est légitime, le pipeline doit l'exposer telle quelle)."""
    chunks = {"bilan-1/note:0": "Texte arbitraire."}
    response = "Je ne peux pas répondre à partir des sources disponibles. [CITE:none]"
    report = verify_response(response, chunks=chunks)
    assert report.all_verified is True
    assert report.n_refused_by_llm == 1
    assert report.n_sourced_verified == 0
    assert report.refused_sentences == []


def test_verify_response_mix_refusal_and_verified_marks_all_verified() -> None:
    """Mix refus + phrase vérifiée doit rester all_verified=True."""
    chunks = {"bilan-1/note:0": "La fraction défend l'unité ouvrière."}
    response = (
        "La fraction défend l'unité ouvrière. [CITE:bilan-1/note:0] "
        "Je ne peux pas répondre davantage. [CITE:none]"
    )
    report = verify_response(response, chunks=chunks)
    assert report.all_verified is True
    assert report.n_sourced_verified == 1
    assert report.n_refused_by_llm == 1


def test_verify_response_unsourced_blocks_even_with_refusal() -> None:
    """Une phrase UNSOURCED (pas de citation du tout) bloque l'all_verified
    même si on a aussi un refus légitime [CITE:none]."""
    chunks: dict[str, str] = {}
    response = "Phrase libre sans citation. Je ne peux pas répondre davantage. [CITE:none]"
    report = verify_response(response, chunks=chunks)
    assert report.all_verified is False
    assert report.n_unsourced == 1
    assert report.n_refused_by_llm == 1


# ---------------------------------------------------------------------------
# Seuil fuzzy adaptatif (plus strict sur phrases courtes)
# ---------------------------------------------------------------------------


def test_adaptive_threshold_short_sentence_rejects_substitution() -> None:
    """Sur 5 mots, le seuil est 100 (substring exact requis). Une substitution
    lexicale qui passerait sous seuil 95 doit échouer."""
    chunks = {"bilan-1/intro:0": "Le matérialisme dialectique reste central."}
    # Phrase 5 mots : "Le matérialisme historique reste central." — substitue
    # "dialectique" → "historique". Avec threshold 95 standard, fuzzy serait ~88-95.
    # Avec threshold adaptatif (5 mots → 100), exige substring exact.
    sentence = "Le matérialisme historique reste central. [CITE:bilan-1/intro:0]"
    v = verify_sentence(sentence, chunks=chunks, fuzzy_threshold=95)
    assert v.verdict == CitationVerdict.SOURCED_UNVERIFIED, (
        f"Substitution sur phrase courte (5 mots) devrait être refusée. "
        f"Score actuel : {v.best_score:.1f}, reason : {v.reason}"
    )


def test_adaptive_threshold_long_sentence_tolerates_small_variation() -> None:
    """Sur 15+ mots, le seuil reste 95. Une variation typographique mineure passe."""
    chunks = {
        "bilan-1/intro:0": (
            "Notre fraction se réclame d'un long passé politique d'une "
            "tradition profonde dans le mouvement italien et international."
        )
    }
    # Phrase 17 mots avec apostrophe typographique différente.
    sentence = (
        "Notre fraction se réclame d’un long passé politique d’une "  # noqa: RUF001
        "tradition profonde dans le mouvement italien et international. "
        "[CITE:bilan-1/intro:0]"
    )
    v = verify_sentence(sentence, chunks=chunks, fuzzy_threshold=95)
    assert v.verdict == CitationVerdict.SOURCED_VERIFIED, (
        f"Phrase longue avec variation mineure devrait passer. Reason : {v.reason}"
    )


# ---------------------------------------------------------------------------
# Citation littérale ≠ citation honnête — détection de réfutation
# ---------------------------------------------------------------------------


def test_verify_sentence_flags_citation_attributed_to_adversary() -> None:
    """Un fragment littéralement exact mais que le contexte source prête à un
    adversaire (« les opportunistes prétendent que… ») → SOURCED_VERIFIED_FLAGGED.

    C'est l'exemple canonique de `citation-honest-vs-literal.md` : la citation
    passe la vérification littérale mais détourne le sens de l'auteur.
    """
    chunks = {
        "bilan-1/note:0": (
            "Les opportunistes prétendent que la révolution est terminée et achevée."
        )
    }
    sentence = "La révolution est terminée et achevée. [CITE:bilan-1/note:0]"
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_VERIFIED_FLAGGED, (
        f"Citation prêtée à un adversaire devrait être flaggée. Reason : {v.reason}"
    )
    assert "prétend" in v.reason


def test_verify_sentence_not_flagged_when_connector_carried_in_response() -> None:
    """Si la phrase générée reprend elle-même le connecteur d'attribution
    (« Les opportunistes prétendent que… »), il n'y a pas de détournement."""
    chunks = {
        "bilan-1/note:0": (
            "Les opportunistes prétendent que la révolution est terminée et achevée."
        )
    }
    sentence = (
        "Les opportunistes prétendent que la révolution est terminée et achevée. "
        "[CITE:bilan-1/note:0]"
    )
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_VERIFIED


def test_verify_sentence_honest_quote_not_flagged() -> None:
    """Une citation d'une assertion propre de l'auteur, sans connecteur de
    réfutation dans le contexte, reste SOURCED_VERIFIED."""
    chunks = {
        "bilan-1/note:0": (
            "La fraction défend l'unité ouvrière. Cette position guide toute son action "
            "politique dans la période ouverte par la défaite."
        )
    }
    sentence = "La fraction défend l'unité ouvrière. [CITE:bilan-1/note:0]"
    v = verify_sentence(sentence, chunks=chunks)
    assert v.verdict == CitationVerdict.SOURCED_VERIFIED


def test_verify_response_flagged_sentence_blocks_all_verified() -> None:
    """Une phrase SOURCED_VERIFIED_FLAGGED casse `all_verified` et figure dans
    `flagged_sentences` ET `refused_sentences` (le pipeline l'écarte)."""
    chunks = {
        "bilan-1/note:0": (
            "Les centristes affirmaient ce triomphe ; certes le Front populaire a vaincu "
            "aux élections, mais cette victoire prépare l'écrasement du prolétariat."
        )
    }
    response = "Le Front populaire a vaincu aux élections. [CITE:bilan-1/note:0]"
    report = verify_response(response, chunks=chunks)
    assert report.all_verified is False
    assert report.n_sourced_verified_flagged == 1
    assert len(report.flagged_sentences) == 1
    assert report.flagged_sentences == report.refused_sentences

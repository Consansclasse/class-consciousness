# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests unitaires du parser TEI P5.

Règle d'or : aucune normalisation destructive ; offsets char préservés.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from cc_corpus.tei import TeiDocument, parse


def test_parse_extracts_required_header_fields(canonical_tei_path: Path) -> None:
    doc = parse(canonical_tei_path)

    assert isinstance(doc, TeiDocument)
    assert doc.title == "Fixture de test — pipeline ingestion"
    assert doc.author_name == "Conscience de classe — équipe technique"
    assert doc.date_iso == "2026-01-01"
    assert doc.ark == "ark:/00000/test-bilan-001"
    assert "CC0" in doc.license
    assert "test synthétique" in doc.source_desc
    assert doc.full_text  # non vide
    assert len(doc.paragraphs) == 3


def test_parse_preserves_paragraph_offsets(canonical_tei_path: Path) -> None:
    doc = parse(canonical_tei_path)

    for para in doc.paragraphs:
        slice_ = doc.full_text[para.char_start : para.char_end]
        assert slice_ == para.text, (
            f"offsets corrompus pour paragraphe (start={para.char_start}, "
            f"end={para.char_end}) : attendu={para.text[:40]!r}, "
            f"obtenu={slice_[:40]!r}"
        )


def test_parse_paragraphs_are_monotonic_non_overlapping(canonical_tei_path: Path) -> None:
    doc = parse(canonical_tei_path)

    for prev, curr in zip(doc.paragraphs, doc.paragraphs[1:], strict=False):
        assert prev.char_end <= curr.char_start, "chevauchement détecté"
        assert prev.char_start < prev.char_end, "paragraphe vide"


def test_parse_raises_when_ark_missing(invalid_no_ark_path: Path) -> None:
    with pytest.raises(ValueError, match=r"(?i)ark"):
        parse(invalid_no_ark_path)


def test_parse_raises_when_license_missing(invalid_no_license_path: Path) -> None:
    with pytest.raises(ValueError, match=r"(?i)licen[cs]e"):
        parse(invalid_no_license_path)


def test_parse_preserves_typography_no_normalization(canonical_tei_path: Path) -> None:
    doc = parse(canonical_tei_path)

    assert "—" in doc.title  # cadratin préservé
    assert "é" in doc.author_name  # accent préservé
    bodytext = doc.full_text
    assert "matérialisme" in bodytext
    assert "lutte des classes" in bodytext


def test_paragraph_text_matches_itertext(canonical_tei_path: Path) -> None:
    doc = parse(canonical_tei_path)
    expected_starts = [
        "Premier paragraphe",
        "Deuxième paragraphe",
        "Troisième paragraphe",
    ]
    for para, expected in zip(doc.paragraphs, expected_starts, strict=True):
        assert para.text.startswith(expected)


def test_parse_returns_immutable_dataclasses(canonical_tei_path: Path) -> None:
    doc = parse(canonical_tei_path)
    with pytest.raises((AttributeError, TypeError)):
        doc.title = "mutated"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        doc.paragraphs[0].text = "mutated"  # type: ignore[misc]


def test_parse_rejects_external_entities(tmp_path: Path) -> None:
    """XXE : un TEI avec entité externe doit ignorer l'entité (resolve_entities=False)."""
    payload = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE TEI [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
  <teiHeader><fileDesc>
    <titleStmt><title>x</title><author>x</author></titleStmt>
    <publicationStmt>
      <date when="2026-01-01">2026</date>
      <idno type="ARK">ark:/00000/x</idno>
      <availability><licence>CC0</licence></availability>
    </publicationStmt>
    <sourceDesc><p>s</p></sourceDesc>
  </fileDesc></teiHeader>
  <text><body><p>&xxe;</p></body></text>
</TEI>
"""
    p = tmp_path / "xxe.tei.xml"
    p.write_text(payload, encoding="utf-8")
    doc = parse(p)
    # l'entité ne doit JAMAIS être résolue vers le contenu du fichier système
    assert "root:" not in doc.full_text

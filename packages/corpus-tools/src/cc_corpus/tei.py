# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser TEI P5 — extraction stricte des métadonnées et du body avec offsets.

Aucune normalisation destructive : on conserve les accents, la typographie d'époque,
les espaces fines. Les offsets `char_start`/`char_end` sont absolus dans `full_text`
(texte plat du body, paragraphes joints par `SEPARATOR`).

Sécurité XXE : `resolve_entities=False, no_network=True`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
SEPARATOR = "\n\n"


@dataclass(frozen=True)
class Paragraph:
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class TeiDocument:
    title: str
    author_name: str
    date_iso: str
    ark: str
    license: str
    source_desc: str
    full_text: str
    paragraphs: list[Paragraph] = field(default_factory=list)


def _safe_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        dtd_validation=False,
        load_dtd=False,
        huge_tree=False,
    )


def _text_of(elem: etree._Element | None) -> str:
    if elem is None:
        return ""
    parts: list[str] = []
    for t in elem.itertext():
        parts.append(t if isinstance(t, str) else t.decode("utf-8", errors="replace"))
    return "".join(parts)


def _require(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValueError(
            f"champ TEI requis manquant : {field_name} — vérifier le <teiHeader> du fichier source"
        )
    return value


def parse(path: Path) -> TeiDocument:
    """Parse un fichier TEI P5 et retourne ses métadonnées + paragraphes avec offsets.

    Lève `ValueError` si un champ requis (title, author, date, ARK, licence, sourceDesc)
    est absent. Les offsets `char_start`/`char_end` sont absolus dans `full_text`.
    """
    tree = etree.parse(str(path), parser=_safe_parser())
    root = tree.getroot()

    title = _text_of(root.find(".//tei:titleStmt/tei:title", NS)).strip()
    author = _text_of(root.find(".//tei:titleStmt/tei:author", NS)).strip()

    date_elem = root.find(".//tei:publicationStmt/tei:date", NS)
    date_iso = ""
    if date_elem is not None:
        date_iso = (date_elem.get("when") or _text_of(date_elem)).strip()

    ark_elem = root.find(".//tei:publicationStmt/tei:idno[@type='ARK']", NS)
    ark = _text_of(ark_elem).strip() if ark_elem is not None else ""

    licence_elem = root.find(".//tei:publicationStmt/tei:availability/tei:licence", NS)
    licence = ""
    if licence_elem is not None:
        target = licence_elem.get("target", "").strip()
        body_text = _text_of(licence_elem).strip()
        licence = body_text or target

    source_desc = _text_of(root.find(".//tei:sourceDesc", NS)).strip()

    _require(title, "title (<titleStmt>/<title>)")
    _require(author, "author (<titleStmt>/<author>)")
    _require(date_iso, "date (<publicationStmt>/<date when='…'>)")
    _require(ark, "ARK (<publicationStmt>/<idno type='ARK'>)")
    _require(licence, "licence (<publicationStmt>/<availability>/<licence>)")
    _require(source_desc, "sourceDesc (<fileDesc>/<sourceDesc>)")

    paragraphs: list[Paragraph] = []
    parts: list[str] = []
    cursor = 0
    for p_elem in root.findall(".//tei:text/tei:body/tei:p", NS):
        text = _text_of(p_elem).strip()
        if not text:
            continue
        start = cursor
        end = cursor + len(text)
        paragraphs.append(Paragraph(text=text, char_start=start, char_end=end))
        parts.append(text)
        cursor = end + len(SEPARATOR)
    full_text = SEPARATOR.join(parts)

    if not paragraphs:
        raise ValueError("aucun paragraphe <p> trouvé dans <text>/<body>")

    return TeiDocument(
        title=title,
        author_name=author,
        date_iso=date_iso,
        ark=ark,
        license=licence,
        source_desc=source_desc,
        full_text=full_text,
        paragraphs=paragraphs,
    )

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Parser TEI P5 — extraction stricte des métadonnées et du body avec offsets.

Deux niveaux supportés :
- `parse_issue(path)` : 1 TEI = 1 numéro de revue contenant N articles
  (chaque article est un `<div type="article">` dans le body).
- `parse(path)` : compat ancienne — 1 TEI = 1 article simple (juste des `<p>`).

Aucune normalisation destructive : accents, typographie d'époque, espaces fines
préservés. Offsets `char_start`/`char_end` absolus dans le texte plat du body.
Sécurité XXE : `resolve_entities=False, no_network=True`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

TEI_NS = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI_NS}
SEPARATOR = "\n\n"

_ISSUE_TITLE_RE = re.compile(r"^\s*([\w' \-]+?)\s*n[°ºo]\s*(\d+)", re.IGNORECASE | re.UNICODE)


@dataclass(frozen=True)
class Paragraph:
    text: str
    char_start: int
    char_end: int


@dataclass(frozen=True)
class TeiDocument:
    """Compat ancienne — un seul article."""

    title: str
    author_name: str
    date_iso: str
    ark: str
    license: str
    source_desc: str
    full_text: str
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass(frozen=True)
class ArticleData:
    """Article à l'intérieur d'un Issue. Offsets relatifs à `full_text` de l'article."""

    slug: str
    title: str
    author_name: str
    full_text: str
    paragraphs: list[Paragraph]


@dataclass(frozen=True)
class IssueDocument:
    """Issue = 1 numéro de revue contenant N articles."""

    slug: str
    journal_title: str
    issue_number: int | None
    title: str
    date_iso: str
    ark: str
    license: str
    source_desc: str
    articles: list[ArticleData] = field(default_factory=list)


def slugify(text: str) -> str:
    """Slug ASCII court pour URL : « Note liminaire » → « note-liminaire »."""
    decomposed = unicodedata.normalize("NFD", text)
    ascii_only = "".join(c for c in decomposed if c.isascii() and (c.isalnum() or c in " -_"))
    lowered = ascii_only.strip().lower()
    return re.sub(r"-+", "-", re.sub(r"[\s_]+", "-", lowered)).strip("-")


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


def _extract_journal_meta(title: str) -> tuple[str, int | None]:
    """Extrait (journal_title, issue_number) depuis « Bilan n°1 — Novembre 1933 »."""
    m = _ISSUE_TITLE_RE.match(title)
    if m:
        return m.group(1).strip(), int(m.group(2))
    return title, None


def _parse_header(root: etree._Element, path: Path) -> tuple[str, str, str, str, str, str]:
    """Extrait (title, author_fallback, date_iso, ark, license, source_desc)."""
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

    _require(title, f"title ({path})")
    _require(author, f"author ({path})")
    _require(date_iso, f"date ({path})")
    _require(ark, f"ARK ({path})")
    _require(licence, f"licence ({path})")
    _require(source_desc, f"sourceDesc ({path})")

    return title, author, date_iso, ark, licence, source_desc


def parse(path: Path) -> TeiDocument:
    """Parse un TEI simple (1 article, paragraphes directs dans <body>).

    Compat ancienne signature. Pour les TEI hiérarchiques, utiliser `parse_issue`.
    """
    tree = etree.parse(str(path), parser=_safe_parser())
    root = tree.getroot()
    title, author, date_iso, ark, licence, source_desc = _parse_header(root, path)

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


def parse_issue(path: Path) -> IssueDocument:
    """Parse un TEI représentant un numéro de revue avec N articles.

    Le `<body>` doit contenir des `<div type="article">` avec :
    - `<head>` (titre de l'article)
    - `<byline>` ou `<byline><author>` (auteur — fallback sur l'auteur du teiHeader)
    - plusieurs `<p>` (paragraphes du corps)

    Si aucun `<div type="article">` n'est trouvé, l'issue est traitée comme
    1 article unique contenant tous les `<p>` directs du body (cas du TEI simple).
    """
    tree = etree.parse(str(path), parser=_safe_parser())
    root = tree.getroot()
    title, author_fallback, date_iso, ark, licence, source_desc = _parse_header(root, path)

    journal_title, issue_number = _extract_journal_meta(title)
    issue_slug = slugify(f"{journal_title}-{issue_number}" if issue_number else title)

    article_divs = root.findall(".//tei:text/tei:body/tei:div[@type='article']", NS)
    articles: list[ArticleData] = []

    def _build_article(
        slug: str, title_str: str, author_str: str, p_elems: list[etree._Element]
    ) -> ArticleData:
        """Construit un ArticleData avec offsets relatifs à son propre full_text."""
        paragraphs: list[Paragraph] = []
        parts: list[str] = []
        cursor = 0
        for p_elem in p_elems:
            text = _text_of(p_elem).strip()
            if not text:
                continue
            start = cursor
            end = cursor + len(text)
            paragraphs.append(Paragraph(text=text, char_start=start, char_end=end))
            parts.append(text)
            cursor = end + len(SEPARATOR)
        if not paragraphs:
            raise ValueError(f"article '{title_str or slug}' sans <p> non-vide dans {path}")
        return ArticleData(
            slug=slug,
            title=title_str,
            author_name=author_str,
            full_text=SEPARATOR.join(parts),
            paragraphs=paragraphs,
        )

    if article_divs:
        for div in article_divs:
            head = _text_of(div.find("tei:head", NS)).strip()
            byline = _text_of(div.find("tei:byline", NS)).strip()
            article_author = byline or author_fallback
            article_slug = div.get("{http://www.w3.org/XML/1998/namespace}id") or slugify(head)
            if not head:
                raise ValueError(f"article {article_slug} sans <head> (titre) dans {path}")
            articles.append(
                _build_article(article_slug, head, article_author, div.findall("tei:p", NS))
            )
    else:
        # Pas de <div type="article"> → l'issue est un article unique avec les <p> du body.
        all_p = root.findall(".//tei:text/tei:body/tei:p", NS)
        articles.append(_build_article(slugify(title), title, author_fallback, all_p))

    return IssueDocument(
        slug=issue_slug,
        journal_title=journal_title,
        issue_number=issue_number,
        title=title,
        date_iso=date_iso,
        ark=ark,
        license=licence,
        source_desc=source_desc,
        articles=articles,
    )

#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Scrape la collection Bilan (1933-1938) depuis archivesautonomies.org → TEI P5.

Pré-requis : lxml (déjà dans `packages/corpus-tools` deps), uv en venv actif.

Conformément à `[[reference_archivesautonomies_legal]]` :
- Rate limit 1.5s/req (serveur SPIP modeste).
- Cache HTML local (`/tmp/bilan_cache/`) pour éviter de re-fetch.
- User-Agent Firefox standard (WebFetch reçoit 429, curl-style fonctionne).
- Attribution obligatoire dans le `sourceDesc` TEI.

Usage :
    uv run python scripts/scrape_bilan.py --list                     # liste tous les numéros
    uv run python scripts/scrape_bilan.py --issue 4                  # génère bilan-004.tei.xml
    uv run python scripts/scrape_bilan.py --all                      # génère tous les bilan-NNN.tei.xml
    uv run python scripts/scrape_bilan.py --issue 4 --issue 5        # plusieurs numéros
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import time
import unicodedata
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = REPO_ROOT / "corpus" / "bilan"
CACHE_DIR = Path("/tmp/bilan_cache")
INDEX_URL = "https://archivesautonomies.org/spip.php?article29"
ARTICLE_URL_TMPL = "https://archivesautonomies.org/spip.php?article{id}"
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64; rv:124.0) Gecko/20100101 Firefox/124.0"
RATE_LIMIT_SECONDS = 1.5

# Mois français → mois numérique (pour date_iso).
MONTHS_FR = {
    "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "août": 8, "septembre": 9, "octobre": 10, "novembre": 11, "décembre": 12,
}


@dataclass(frozen=True)
class ArticleRef:
    """Référence d'un article dans l'index Bilan."""

    article_id: int
    title: str  # titre tel qu'apparu dans l'index


@dataclass(frozen=True)
class IssueRef:
    """Référence d'un numéro Bilan dans l'index."""

    issue_number: int
    date_label: str  # "Décembre 1933", "Janvier 1934", etc.
    articles: tuple[ArticleRef, ...]


@dataclass(frozen=True)
class ArticleContent:
    """Contenu extrait d'un article Bilan."""

    article_id: int
    title: str
    soustitle: str  # le {Bilan} n°X - Mois Année
    author_byline: str  # auteur lisible (déduit du titre/contenu)
    paragraphs: tuple[str, ...]  # paragraphes nettoyés


# ---------------------------------------------------------------------------
# Fetch + cache
# ---------------------------------------------------------------------------


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR / name


def _fetch(url: str, cache_name: str) -> str:
    """Fetch URL avec cache local + rate limit + UA Firefox."""
    cached = _cache_path(cache_name)
    if cached.exists():
        return cached.read_text(encoding="utf-8")
    print(f"  → fetching {url}", file=sys.stderr)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data: bytes = resp.read()
    text = data.decode("utf-8", errors="replace")
    cached.write_text(text, encoding="utf-8")
    time.sleep(RATE_LIMIT_SECONDS)
    return text


def fetch_index() -> str:
    return _fetch(INDEX_URL, "index.html")


def fetch_article(article_id: int) -> str:
    return _fetch(ARTICLE_URL_TMPL.format(id=article_id), f"art{article_id}.html")


# ---------------------------------------------------------------------------
# Parsing : index → liste des numéros et articles
# ---------------------------------------------------------------------------


_ISSUE_HEADER_RE = re.compile(
    r"<strong>\s*Bilan\s*n(?:°|&#176;)\s*(\d+)\s*-\s*([^<]+?)\s*</strong>", re.IGNORECASE
)
_ARTICLE_LINK_RE = re.compile(
    r'<a\s+href="(?:https://archivesautonomies\.org/)?spip\.php\?article(\d+)"[^>]*>([^<]+)</a>',
    re.IGNORECASE,
)


def parse_index(html_text: str) -> list[IssueRef]:
    """Parse l'index HTML et retourne la liste des numéros + articles."""
    # On découpe sur chaque header `<strong>Bilan n°X - Date</strong>`.
    headers = list(_ISSUE_HEADER_RE.finditer(html_text))
    issues: list[IssueRef] = []
    for idx, match in enumerate(headers):
        issue_number = int(match.group(1))
        date_label = html.unescape(match.group(2)).strip()
        start = match.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(html_text)
        block = html_text[start:end]
        # Le dernier numéro n'a pas de header suivant pour borner son bloc : on
        # le coupe au premier <aside qui démarre la zone « Dans la même rubrique »
        # afin d'éviter d'aspirer des liens vers d'autres numéros/articles.
        aside_pos = block.find("<aside")
        if aside_pos != -1:
            block = block[:aside_pos]
        articles: list[ArticleRef] = []
        for link in _ARTICLE_LINK_RE.finditer(block):
            art_id = int(link.group(1))
            raw_title = html.unescape(link.group(2)).strip()
            # Nettoyer espaces insécables Unicode.
            title = re.sub(r"\s+", " ", raw_title).strip()
            articles.append(ArticleRef(article_id=art_id, title=title))
        issues.append(
            IssueRef(
                issue_number=issue_number,
                date_label=date_label,
                articles=tuple(articles),
            )
        )
    return issues


# ---------------------------------------------------------------------------
# Parsing : article HTML → contenu
# ---------------------------------------------------------------------------


_TITLE_RE = re.compile(r'<div id="titre-article"[^>]*>(.*?)</div>', re.DOTALL)
_SOUSTITLE_RE = re.compile(r'<div id="soustitre-article"[^>]*>(.*?)</div>', re.DOTALL)
_CADRE_ARTICLE_RE = re.compile(r'<div id="cadre-article">(.*?)</div><!-- Fin cadre-article', re.DOTALL)
_ASIDE_RE = re.compile(r"<aside.*?</aside>", re.DOTALL)
_BOUTONS_RE = re.compile(r'<div id="outils-article".*?</div>\s*</aside>', re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")
_P_BLOCK_RE = re.compile(r"<p[^>]*>(.*?)</p>", re.DOTALL)
_NOTES_FOOTER_RE = re.compile(r'<div class="notes">(.*?)</div>', re.DOTALL)


def _clean_text(s: str) -> str:
    """Supprime les balises HTML, décode les entités, normalise les espaces."""
    no_tags = _HTML_TAG_RE.sub("", s)
    decoded = html.unescape(no_tags)
    # Espaces insécables Unicode → espace normal.
    normalized = decoded.replace(" ", " ").replace(" ", " ")
    return re.sub(r"\s+", " ", normalized).strip()


def parse_article(article_id: int, html_text: str) -> ArticleContent:
    """Extrait titre, sous-titre et paragraphes d'un article SPIP."""
    title_m = _TITLE_RE.search(html_text)
    soustitle_m = _SOUSTITLE_RE.search(html_text)
    if title_m is None:
        raise ValueError(f"article {article_id} : <div id='titre-article'> introuvable")
    title = _clean_text(title_m.group(1))
    soustitle = _clean_text(soustitle_m.group(1)) if soustitle_m else ""

    cadre_m = _CADRE_ARTICLE_RE.search(html_text)
    if cadre_m is None:
        raise ValueError(f"article {article_id} : <div id='cadre-article'> introuvable")
    cadre = cadre_m.group(1)

    # Retirer asides (outils, partage, notes-de-pied-de-page seront récupérées séparément).
    notes_block = _NOTES_FOOTER_RE.search(cadre)
    notes_paragraphs: list[str] = []
    if notes_block:
        for p in _P_BLOCK_RE.findall(notes_block.group(1)):
            txt = _clean_text(p)
            if txt:
                notes_paragraphs.append(txt)
    body = _ASIDE_RE.sub("", cadre)
    body = _BOUTONS_RE.sub("", body)

    paragraphs: list[str] = []
    for p in _P_BLOCK_RE.findall(body):
        txt = _clean_text(p)
        if not txt:
            continue
        # Filtrer les boilerplates SPIP (logos imprimer, etc.).
        if "logo imprimer" in txt.lower():
            continue
        if "diminuer la taille" in txt.lower() or "augmenter la taille" in txt.lower():
            continue
        if "article mis en ligne" in txt.lower() or "dernière modification" in txt.lower():
            continue
        if txt in {"par ArchivesAutonomies", "ArchivesAutonomies"}:
            continue
        paragraphs.append(txt)

    # Ajouter notes en fin avec préfixe explicite.
    for i, note in enumerate(notes_paragraphs, 1):
        paragraphs.append(f"Note {i} — {note}")

    author_byline = _deduce_author(title, paragraphs)
    return ArticleContent(
        article_id=article_id,
        title=title,
        soustitle=soustitle,
        author_byline=author_byline,
        paragraphs=tuple(paragraphs),
    )


FRACTION_DEFAULT = "Fraction de Gauche du Parti communiste italien"

# Marqueurs de partie / découpage — un parenthétique de ce type n'est jamais
# un auteur (« (partie 2) », « (suite et fin) », « (6 et fin) »…).
_PART_MARKER = re.compile(r"\b(partie|suite|fin)\b", re.IGNORECASE)


def _looks_like_author(candidate: str) -> bool:
    """Vrai si un parenthétique de fin de titre ressemble à un nom d'auteur.

    Rejette les marqueurs de partie, les fragments de sous-titre descriptifs
    (qui commencent en minuscule ou par « à propos ») et les libellés trop
    longs — sinon « (partie 2) » ou « (À propos de X) » polluaient le champ
    auteur.
    """
    if not (2 <= len(candidate) <= 60):
        return False
    if candidate[0].islower():
        return False
    if candidate.lower().startswith(("résolution", "thèses", "déclaration", "à propos")):
        return False
    return not _PART_MARKER.search(candidate)


def _deduce_author(title: str, paragraphs: tuple[str, ...] | list[str]) -> str:
    """Devine l'auteur via le pattern `(Auteur)` à la fin du titre.

    Le parenthétique final n'est retenu que s'il ressemble à un nom (voir
    `_looks_like_author`). À défaut, l'article est attribué à la Fraction,
    signataire collectif par défaut de Bilan.
    """
    _ = paragraphs  # signature conservée pour stabilité de l'API
    paren = re.search(r"\(([^()]+?)\)\s*$", title)
    if paren:
        candidate = paren.group(1).strip()
        if _looks_like_author(candidate):
            return candidate
    return FRACTION_DEFAULT


# ---------------------------------------------------------------------------
# Helpers : slugify, date_iso
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Slug ASCII identique à `cc_corpus.tei.slugify` (compat avec parse_issue)."""
    decomposed = unicodedata.normalize("NFD", text)
    ascii_only = "".join(c for c in decomposed if c.isascii() and (c.isalnum() or c in " -_"))
    lowered = ascii_only.strip().lower()
    return re.sub(r"-+", "-", re.sub(r"[\s_]+", "-", lowered)).strip("-")


def date_iso_from_label(label: str) -> str:
    """Convertit 'Décembre 1933' → '1933-12-01'. Best-effort, défaut au 1er du mois."""
    m = re.search(r"([A-Za-zéÉûÛâÂ]+)\s+(\d{4})", label)
    if not m:
        return "1933-01-01"
    month_name = m.group(1).lower()
    year = int(m.group(2))
    month = MONTHS_FR.get(month_name, 1)
    return f"{year:04d}-{month:02d}-01"


# ---------------------------------------------------------------------------
# Construction TEI
# ---------------------------------------------------------------------------


def _xml(text: str) -> str:
    """Échappe les caractères XML."""
    return xml_escape(text, entities={"'": "&apos;", '"': "&quot;"})


def build_tei(issue: IssueRef, contents: Iterable[ArticleContent]) -> str:
    """Construit le TEI P5 d'un numéro Bilan complet."""
    issue_title = f"Bilan n°{issue.issue_number} — {issue.date_label}"
    issue_ark = f"ark:/00000/bilan-{issue.issue_number:03d}"
    date_iso = date_iso_from_label(issue.date_label)
    today = time.strftime("%Y-%m-%d")
    source_desc = (
        f"Bilan, revue mensuelle de la Fraction de Gauche du Parti communiste italien, "
        f"n°{issue.issue_number}, {issue.date_label}. Transcription : "
        f"archivesautonomies.org/spip.php?article29, consultée le {today}."
    )

    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">',
        "  <teiHeader>",
        "    <fileDesc>",
        "      <titleStmt>",
        f"        <title>{_xml(issue_title)}</title>",
        "        <author>Fraction de Gauche du Parti communiste italien</author>",
        "      </titleStmt>",
        "      <publicationStmt>",
        "        <publisher>class-consciousness.org</publisher>",
        f'        <date when="{date_iso}">{_xml(issue.date_label)}</date>',
        f'        <idno type="ARK">{_xml(issue_ark)}</idno>',
        '        <availability status="free">',
        '          <licence target="https://creativecommons.org/licenses/by-sa/4.0/">CC-BY-SA-4.0</licence>',
        "        </availability>",
        "      </publicationStmt>",
        "      <sourceDesc>",
        f"        <p>{_xml(source_desc)}</p>",
        "      </sourceDesc>",
        "    </fileDesc>",
        "  </teiHeader>",
        "  <text>",
        "    <body>",
    ]

    for art in contents:
        if not art.paragraphs:
            continue  # skip articles vides (parse échoué)
        art_slug = slugify(art.title)
        # NCName XML interdit `xml:id` commençant par un chiffre. Si le slug
        # commence par un chiffre (« 1er-mai-1934 »), on omet `xml:id` :
        # `parse_issue` retombera sur `slugify(<head>)` et retrouvera le même slug.
        if art_slug and art_slug[0].isalpha():
            parts.append(f'      <div type="article" xml:id="{_xml(art_slug)}">')
        else:
            parts.append('      <div type="article">')
        parts.append(f"        <head>{_xml(art.title)}</head>")
        parts.append(f"        <byline>{_xml(art.author_byline)}</byline>")
        for para in art.paragraphs:
            parts.append(f"        <p>{_xml(para)}</p>")
        parts.append("      </div>")

    parts.extend(["    </body>", "  </text>", "</TEI>", ""])
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def cmd_list(issues: list[IssueRef]) -> None:
    print(f"Bilan : {len(issues)} numéros indexés")
    for issue in issues:
        print(f"  n°{issue.issue_number:2d} — {issue.date_label:30s} ({len(issue.articles):2d} articles)")


def cmd_issue(issues: list[IssueRef], issue_number: int) -> Path:
    """Génère le TEI d'un numéro et l'écrit dans corpus/bilan/bilan-NNN.tei.xml."""
    issue = next((i for i in issues if i.issue_number == issue_number), None)
    if issue is None:
        raise SystemExit(f"Numéro {issue_number} introuvable dans l'index.")
    print(f"→ Bilan n°{issue.issue_number} ({issue.date_label}) : {len(issue.articles)} articles")
    contents: list[ArticleContent] = []
    for art_ref in issue.articles:
        try:
            raw = fetch_article(art_ref.article_id)
            content = parse_article(art_ref.article_id, raw)
        except Exception as exc:  # noqa: BLE001
            print(f"  ⚠ art{art_ref.article_id} ({art_ref.title[:50]}…) : {exc}")
            continue
        print(
            f"  ✓ art{art_ref.article_id}: {len(content.paragraphs):3d} paragraphes — {content.title[:60]}"
        )
        contents.append(content)

    tei = build_tei(issue, contents)
    out = CORPUS_DIR / f"bilan-{issue.issue_number:03d}.tei.xml"
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(tei, encoding="utf-8")
    print(f"  → {out} ({len(tei):,} chars)")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="liste les numéros indexés")
    parser.add_argument(
        "--issue", action="append", type=int, default=[], help="numéro Bilan à générer (répétable)"
    )
    parser.add_argument("--all", action="store_true", help="générer tous les numéros")
    args = parser.parse_args()

    print(f"Index : {INDEX_URL}", file=sys.stderr)
    raw_index = fetch_index()
    issues = parse_index(raw_index)
    if not issues:
        raise SystemExit("Index parsé : 0 numéros. Vérifier le HTML.")

    if args.list:
        cmd_list(issues)
        return

    target_numbers: list[int] = []
    if args.all:
        target_numbers = [i.issue_number for i in issues]
    elif args.issue:
        target_numbers = sorted(set(args.issue))
    else:
        cmd_list(issues)
        print("\nSpécifie --issue N ou --all pour générer les TEI.", file=sys.stderr)
        return

    for n in target_numbers:
        cmd_issue(issues, n)


if __name__ == "__main__":
    main()

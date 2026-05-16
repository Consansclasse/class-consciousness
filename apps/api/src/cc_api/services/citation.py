# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vérification de citation par phrase — règle d'or du pipeline RAG.

Aucune phrase d'une réponse RAG ne doit exister sans une citation rattachée à
un passage du corpus ET cette citation doit être *littéralement* présente dans
le passage source (substring exact OU `rapidfuzz.partial_ratio ≥ threshold`).

Voir `.claude/rules/no-unsourced-rag.md` et `[[feedback_no_unsourced_answers]]`.

## Format de citation imposé au LLM

Chaque phrase de la réponse doit se terminer par UN ou PLUSIEURS marqueurs
`[CITE:source_id]` où `source_id` = `{issue_slug}/{article_slug}:{chunk_idx}`.
Exemple : « La position de Bilan est claire. [CITE:bilan-1/note-liminaire:0] ».

## Stratégie de vérification

1. Extraire les `source_id` cités via regex.
2. Reconstituer le texte de la phrase sans les marqueurs CITE.
3. Pour chaque source_id cité, vérifier que le texte de la phrase apparaît
   dans le chunk pointé (substring exact OU `partial_ratio ≥ threshold`).
4. Verdict par phrase : SOURCED_VERIFIED / SOURCED_VERIFIED_FLAGGED /
   SOURCED_UNVERIFIED / UNSOURCED.

`partial_ratio` mesure la similarité optimale entre la phrase courte et
n'importe quelle sous-séquence du chunk long. Seuil par défaut : 95.

## Citation littérale ≠ citation honnête

Une citation peut être littéralement exacte mais sémantiquement détournée :
le fragment extrait peut être réfuté par son contexte immédiat, ou prêté par
l'auteur à un adversaire. Après un match, on scanne donc un anneau de contexte
autour du fragment dans le chunk source : si un connecteur de réfutation ou
d'attribution adverse y figure SANS être reporté dans la phrase générée, le
verdict est `SOURCED_VERIFIED_FLAGGED` (et non `SOURCED_VERIFIED`).

Voir `.claude/rules/citation-honest-vs-literal.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz

# Pattern de citation : [CITE:bilan-1/note-liminaire:0] ou [CITE:autre_id]
_CITE_PATTERN = re.compile(r"\[CITE:([^\]\s]+)\]")

# Abréviations françaises qui contiennent un `.` mais ne terminent pas une phrase.
# On exclut volontairement les initiales seules (K. F. V. J. R. L. G. A. P. S.) :
# trop ambiguës car ces lettres apparaissent aussi en fin de phrase normale
# (« paragraphe A. », « point F. »). Le compromis : « K. Marx » donnera deux
# phrases mais ne casse pas la sémantique du pipeline RAG.
_FR_ABBREVIATIONS = frozenset(
    {
        # titres
        "M.",
        "Mme.",
        "Mlle.",
        "Dr.",
        "Pr.",
        "Me.",
        # latin / académique
        "cf.",
        "etc.",
        "ibid.",
        "id.",
        "op.",
        "loc.",
        "vol.",
        "fol.",
        "p.",
        "pp.",
        "n°.",
        "n°",
        "ch.",
        "art.",
        "fig.",
        "tab.",
        "sec.",
        "ms.",
        # éditions / références
        "éd.",
        "ed.",
        "coll.",
        "trad.",
        "rééd.",
        "réimpr.",
        # syntaxiques courants
        "c.-à-d.",
        "p.ex.",
        "p.s.",
        "n.b.",
        "i.e.",
        "e.g.",
    }
)

# Pattern : « 1 ou plusieurs `[CITE:...]` éventuellement séparés par des espaces ».
_LEADING_CITES_PATTERN = re.compile(r"((?:\[CITE:[^\]\s]+\]\s*)+)")


class CitationVerdict(str, Enum):  # noqa: UP042 — cohérence avec MembershipTier (compat sérialisation)
    """Verdict de vérification d'une phrase.

    `REFUSED_BY_LLM` distingue le cas où le LLM a explicitement refusé
    de répondre via le marqueur réservé `[CITE:none]` (phrase de refus
    standard imposée par le prompt système). Ce verdict est compté comme
    "all_verified" car le refus est légitime et attendu.

    `SOURCED_VERIFIED_FLAGGED` : la phrase est littéralement présente dans le
    chunk cité, mais son contexte source porte un connecteur de réfutation ou
    d'attribution adverse non reporté dans la réponse — citation possiblement
    détournée. Ce verdict N'EST PAS compté comme "all_verified" : le pipeline
    le traite comme une phrase à écarter (silence préférable à la distorsion).
    """

    SOURCED_VERIFIED = "SOURCED_VERIFIED"
    SOURCED_VERIFIED_FLAGGED = "SOURCED_VERIFIED_FLAGGED"
    SOURCED_UNVERIFIED = "SOURCED_UNVERIFIED"
    UNSOURCED = "UNSOURCED"
    REFUSED_BY_LLM = "REFUSED_BY_LLM"


# Citation réservée : le LLM utilise `[CITE:none]` pour signaler un refus
# explicite et conforme au prompt système. Cf. SYSTEM_PROMPT de rag.py.
REFUSAL_CITATION = "none"


@dataclass(frozen=True)
class SentenceVerdict:
    """Résultat de la vérification d'une phrase."""

    sentence: str
    cleaned_sentence: str  # sentence sans marqueurs CITE
    citations: list[str]  # source_ids cités
    verdict: CitationVerdict
    best_score: float  # max partial_ratio sur les chunks cités (0..100)
    reason: str  # explication humaine


@dataclass(frozen=True)
class CitationReport:
    """Synthèse de la vérification d'une réponse complète.

    `all_verified` est `True` si chaque phrase est soit `SOURCED_VERIFIED`,
    soit `REFUSED_BY_LLM` (refus explicite). Une phrase `UNSOURCED`,
    `SOURCED_UNVERIFIED` ou `SOURCED_VERIFIED_FLAGGED` casse cette propriété.

    `flagged_sentences` liste les phrases littéralement sourcées mais signalées
    comme possiblement détournées (connecteur de réfutation non reporté) ;
    elles figurent aussi dans `refused_sentences` car le pipeline les écarte.
    """

    sentences: list[SentenceVerdict]
    all_verified: bool
    n_sourced_verified: int
    n_sourced_unverified: int
    n_unsourced: int
    n_refused_by_llm: int = 0
    n_sourced_verified_flagged: int = 0
    refused_sentences: list[str] = field(default_factory=list)
    flagged_sentences: list[str] = field(default_factory=list)


def split_sentences(text: str) -> list[str]:
    """Découpe `text` en phrases françaises en respectant les abréviations
    ET en rattachant les marqueurs `[CITE:...]` à la phrase qui les précède.

    Le LLM écrit naturellement `"Phrase X. [CITE:src]"` : sans traitement,
    le split sur `.\\s+` séparerait `[CITE:src]` de la phrase X et le collerait
    à la phrase suivante, perdant la traçabilité. On corrige par une phase 2
    qui réattache les CITE traînants à la phrase précédente.
    """
    if not text.strip():
        return []
    # Phase 1 : split sur `.!?` suivi d'un espace, en accumulant les abréviations.
    raw_parts = re.split(r"(?<=[.!?])\s+", text.strip())
    phase1: list[str] = []
    buffer = ""
    for part in raw_parts:
        candidate = (buffer + " " + part).strip() if buffer else part
        tokens = candidate.split()
        last_token = tokens[-1] if tokens else ""
        # Si fragment finit sur abréviation ET n'est pas le dernier raw_part, on accumule.
        if last_token in _FR_ABBREVIATIONS and part is not raw_parts[-1]:
            buffer = candidate
            continue
        phase1.append(candidate)
        buffer = ""
    if buffer:
        phase1.append(buffer)

    # Phase 2 : si une phrase commence par `[CITE:...]`, on rattache ces CITE
    # à la phrase précédente, et on garde le reste (s'il existe) comme nouvelle
    # phrase autonome.
    merged: list[str] = []
    for s in phase1:
        stripped = s.lstrip()
        if not stripped:
            continue
        match = _LEADING_CITES_PATTERN.match(stripped)
        if match and merged:
            citations_block = match.group(1).strip()
            remainder = stripped[match.end() :].strip()
            merged[-1] = merged[-1].rstrip() + " " + citations_block
            if remainder:
                merged.append(remainder)
        else:
            merged.append(stripped)

    return [s for s in merged if s.strip()]


def extract_citations(sentence: str) -> list[str]:
    """Renvoie la liste des `source_id` cités dans la phrase (ordre d'apparition)."""
    return _CITE_PATTERN.findall(sentence)


def strip_citations(sentence: str) -> str:
    """Renvoie la phrase sans les marqueurs `[CITE:...]` et espaces redondants."""
    cleaned = _CITE_PATTERN.sub("", sentence)
    return re.sub(r"\s+", " ", cleaned).strip()


def _adaptive_threshold(cleaned_sentence: str, base_threshold: int) -> int:
    """Renvoie un seuil fuzzy plus strict pour les phrases courtes.

    `rapidfuzz.partial_ratio` est très indulgent sur les phrases courtes :
    sur 5 mots, une substitution lexicale (dialectique → historique) peut
    encore donner 88-92%. On élève donc le seuil pour les phrases < 10 mots.

    - 10+ mots → `base_threshold` (95 par défaut)
    - 9 mots → 96
    - 8 mots → 97
    - 7 mots → 98
    - 6 mots → 99
    - ≤ 5 mots → 100 (substring exact requis)
    """
    n_words = len(cleaned_sentence.split())
    if n_words >= 10:
        return base_threshold
    return min(100, base_threshold + (10 - n_words))


# Repli typographique : guillemets/apostrophes/tirets courbes → forme ASCII.
# Le corpus emploie des guillemets français (« … ») avec espaces insérés ; le
# LLM peut produire des guillemets droits. Cette variation purement
# typographique ne doit pas faire échouer une citation fidèle (cf. la tolérance
# « variations typographiques mineures » de la règle d'or). Clés = codepoints
# pour éviter tout caractère ambigu dans le source.
_TYPO_FOLD = str.maketrans(
    {
        0x00AB: '"', 0x00BB: '"',  # guillemets français
        0x201C: '"', 0x201D: '"',  # guillemets-virgules doubles
        0x2018: "'", 0x2019: "'",  # apostrophes courbes
        0x2013: "-", 0x2014: "-",  # tirets demi/cadratin
    }
)


def _fold_typography(text: str) -> str:
    """Normalise guillemets/apostrophes/tirets + espaces collés aux guillemets."""
    return re.sub(r'\s*"\s*', '"', text.translate(_TYPO_FOLD))


# Anneau de contexte (en caractères) scanné de part et d'autre du fragment cité
# pour y déceler un connecteur de réfutation.
_REFUTATION_RING = 200

# Connecteurs FR de réfutation et d'attribution adverse. Leur présence à
# proximité d'un fragment cité — DANS le chunk source mais ABSENTE de la phrase
# générée — signale une citation littéralement exacte mais potentiellement
# détournée (l'auteur réfutait ce fragment, ou le prêtait à un adversaire).
#
# On retient volontairement des connecteurs HAUTE PRÉCISION : les contrastes
# génériques (« mais », « cependant », « toutefois », « pourtant ») ont été
# écartés car ubiquitaires en prose théorique — ils marquent le plus souvent
# une articulation interne du raisonnement, pas une réfutation du fragment, et
# généraient des faux positifs massifs (mesurés sur le corpus Bilan).
# Cf. `.claude/rules/citation-honest-vs-literal.md`.
_REFUTATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p)
    for p in (
        # Attribution à un adversaire — l'auteur prête le propos à un tiers.
        r"\bprétend\w*",
        r"\bsoi-disant\b",
        r"\bse réclam\w+",
        r"\bexult\w+",
        # Réfutation explicite — l'auteur récuse le propos.
        r"\bcertes\b",
        r"\ben réalité\b",
        r"\bcontrairement à\b",
        r"\bà l'opposé\b",
        r"\bil est faux\b",
        r"\bse tromp\w+",
        r"\bà tort\b",
    )
)


def _detect_uncarried_refutation(
    chunk_lower: str, match_start: int, match_end: int, sentence_lower: str
) -> str | None:
    """Cherche un connecteur de réfutation autour du fragment cité.

    Renvoie le connecteur fautif si un marqueur de réfutation ou d'attribution
    adverse apparaît dans l'anneau ±`_REFUTATION_RING` autour du match dans le
    chunk, SANS être présent dans la phrase générée — signe d'une citation
    littéralement exacte mais peut-être sémantiquement détournée. `None` sinon.

    `chunk_lower` et `sentence_lower` sont attendus en minuscules ; les
    apostrophes typographiques sont normalisées pour fiabiliser les motifs.
    """
    chunk_norm = chunk_lower.replace(chr(0x2019), "'")
    sentence_norm = sentence_lower.replace(chr(0x2019), "'")
    pre = chunk_norm[max(0, match_start - _REFUTATION_RING) : match_start]
    post = chunk_norm[match_end : match_end + _REFUTATION_RING]
    for pattern in _REFUTATION_PATTERNS:
        if pattern.search(sentence_norm):
            continue  # connecteur reporté dans la réponse — pas de détournement
        hit = pattern.search(pre) or pattern.search(post)
        if hit:
            return hit.group(0)
    return None


def verify_sentence(
    sentence: str,
    *,
    chunks: dict[str, str],
    fuzzy_threshold: int = 95,
) -> SentenceVerdict:
    """Vérifie qu'une phrase est littéralement adossée à au moins un chunk cité.

    Stratégie :
    - Si la phrase ne cite QUE `[CITE:none]` → `REFUSED_BY_LLM` (refus légitime,
      le LLM signale qu'il ne peut pas répondre depuis le contexte fourni).
    - Sinon extraire les vrais `source_id` cités. Si aucun → `UNSOURCED`.
    - Pour chaque `source_id` cité, vérifier :
        * substring exact dans `chunks[source_id]` (insensible casse + espaces),
        * sinon `rapidfuzz.fuzz.partial_ratio` ≥ seuil adaptatif (95-100 selon
          la longueur de la phrase — voir `_adaptive_threshold`).
    - Si au moins un chunk valide la phrase → `SOURCED_VERIFIED`.
    - Si chunks cités existent mais aucun ne valide → `SOURCED_UNVERIFIED`.
    """
    citations = extract_citations(sentence)
    cleaned = strip_citations(sentence)
    if not citations:
        return SentenceVerdict(
            sentence=sentence,
            cleaned_sentence=cleaned,
            citations=[],
            verdict=CitationVerdict.UNSOURCED,
            best_score=0.0,
            reason="aucune citation [CITE:source_id] détectée",
        )

    # Refus explicite du LLM via [CITE:none] (cf. SYSTEM_PROMPT de rag.py).
    # On accepte aussi le mélange [CITE:none] + autres citations comme refus
    # si TOUTES les citations sont 'none'. Sinon on filtre les 'none' et on
    # continue avec les vraies citations.
    real_citations = [c for c in citations if c != REFUSAL_CITATION]
    if not real_citations:
        return SentenceVerdict(
            sentence=sentence,
            cleaned_sentence=cleaned,
            citations=citations,
            verdict=CitationVerdict.REFUSED_BY_LLM,
            best_score=0.0,
            reason="refus explicite du LLM (citation réservée [CITE:none])",
        )

    if not cleaned:
        # Phrase entièrement composée de marqueurs CITE — pas de contenu à vérifier.
        return SentenceVerdict(
            sentence=sentence,
            cleaned_sentence="",
            citations=citations,
            verdict=CitationVerdict.SOURCED_UNVERIFIED,
            best_score=0.0,
            reason="phrase vide après suppression des marqueurs CITE",
        )

    effective_threshold = _adaptive_threshold(cleaned, fuzzy_threshold)
    best_score = 0.0
    best_source: str | None = None
    for source_id in real_citations:
        chunk_text = chunks.get(source_id)
        if chunk_text is None:
            continue
        # Substring exact (rapide, casse + espace tolérants).
        # On retire la ponctuation finale `.!?` qui n'apparaît typiquement pas
        # à l'identique dans le chunk source (la phrase RAG peut clore une
        # citation mais le fragment cité ne se termine pas forcément par un point).
        norm_sentence = _fold_typography(re.sub(r"\s+", " ", cleaned)).lower().strip()
        norm_sentence_trimmed = re.sub(r"[.!?]+$", "", norm_sentence).strip()
        norm_chunk = _fold_typography(re.sub(r"\s+", " ", chunk_text)).lower()
        if norm_sentence_trimmed and norm_sentence_trimmed in norm_chunk:
            idx = norm_chunk.find(norm_sentence_trimmed)
            flagged = _detect_uncarried_refutation(
                norm_chunk, idx, idx + len(norm_sentence_trimmed), norm_sentence
            )
            if flagged is not None:
                return SentenceVerdict(
                    sentence=sentence,
                    cleaned_sentence=cleaned,
                    citations=citations,
                    verdict=CitationVerdict.SOURCED_VERIFIED_FLAGGED,
                    best_score=100.0,
                    reason=(
                        f"substring exact dans {source_id} mais connecteur de "
                        f"réfutation « {flagged} » présent dans le contexte source "
                        f"et absent de la réponse — citation possiblement détournée"
                    ),
                )
            return SentenceVerdict(
                sentence=sentence,
                cleaned_sentence=cleaned,
                citations=citations,
                verdict=CitationVerdict.SOURCED_VERIFIED,
                best_score=100.0,
                reason=f"substring exact dans {source_id}",
            )
        # Fuzzy partial_ratio : trouve la meilleure sous-séquence dans le chunk.
        score = float(
            fuzz.partial_ratio(_fold_typography(cleaned), _fold_typography(chunk_text))
        )
        if score > best_score:
            best_score = score
            best_source = source_id

    if best_score >= effective_threshold and best_source is not None:
        chunk_text = chunks[best_source]
        align = fuzz.partial_ratio_alignment(cleaned, chunk_text)
        flagged = (
            _detect_uncarried_refutation(
                chunk_text.lower(), align.dest_start, align.dest_end, cleaned.lower()
            )
            if align is not None
            else None
        )
        base_reason = (
            f"fuzzy {best_score:.1f}% ≥ {effective_threshold}% dans {best_source} "
            f"(seuil adaptatif sur {len(cleaned.split())} mots)"
        )
        if flagged is not None:
            return SentenceVerdict(
                sentence=sentence,
                cleaned_sentence=cleaned,
                citations=citations,
                verdict=CitationVerdict.SOURCED_VERIFIED_FLAGGED,
                best_score=best_score,
                reason=(
                    f"{base_reason} mais connecteur de réfutation « {flagged} » "
                    f"présent dans le contexte source et absent de la réponse — "
                    f"citation possiblement détournée"
                ),
            )
        return SentenceVerdict(
            sentence=sentence,
            cleaned_sentence=cleaned,
            citations=citations,
            verdict=CitationVerdict.SOURCED_VERIFIED,
            best_score=best_score,
            reason=base_reason,
        )

    return SentenceVerdict(
        sentence=sentence,
        cleaned_sentence=cleaned,
        citations=citations,
        verdict=CitationVerdict.SOURCED_UNVERIFIED,
        best_score=best_score,
        reason=(
            f"meilleur match fuzzy {best_score:.1f}% < {effective_threshold}% "
            f"(source candidate : {best_source}, {len(cleaned.split())} mots)"
            if best_source
            else f"aucun chunk cité ({real_citations}) n'est dans `chunks` fourni"
        ),
    )


def verify_response(
    response_text: str,
    *,
    chunks: dict[str, str],
    fuzzy_threshold: int = 95,
) -> CitationReport:
    """Découpe la réponse en phrases et vérifie chaque phrase.

    `all_verified` est `True` si chaque phrase est soit `SOURCED_VERIFIED`,
    soit `REFUSED_BY_LLM` (refus explicite). Une phrase `UNSOURCED` ou
    `SOURCED_UNVERIFIED` casse cette propriété.
    """
    sentences = split_sentences(response_text)
    verdicts = [
        verify_sentence(s, chunks=chunks, fuzzy_threshold=fuzzy_threshold) for s in sentences
    ]
    n_verified = sum(1 for v in verdicts if v.verdict == CitationVerdict.SOURCED_VERIFIED)
    n_unverified = sum(1 for v in verdicts if v.verdict == CitationVerdict.SOURCED_UNVERIFIED)
    n_unsourced = sum(1 for v in verdicts if v.verdict == CitationVerdict.UNSOURCED)
    n_refused_llm = sum(1 for v in verdicts if v.verdict == CitationVerdict.REFUSED_BY_LLM)
    n_flagged = sum(
        1 for v in verdicts if v.verdict == CitationVerdict.SOURCED_VERIFIED_FLAGGED
    )
    # Une phrase qui n'est ni SOURCED_VERIFIED ni REFUSED_BY_LLM est problématique
    # (cela inclut SOURCED_VERIFIED_FLAGGED — citation possiblement détournée).
    refused = [
        v.sentence
        for v in verdicts
        if v.verdict not in (CitationVerdict.SOURCED_VERIFIED, CitationVerdict.REFUSED_BY_LLM)
    ]
    flagged = [
        v.sentence for v in verdicts if v.verdict == CitationVerdict.SOURCED_VERIFIED_FLAGGED
    ]
    all_ok = len(verdicts) > 0 and (n_verified + n_refused_llm) == len(verdicts)
    return CitationReport(
        sentences=verdicts,
        all_verified=all_ok,
        n_sourced_verified=n_verified,
        n_sourced_unverified=n_unverified,
        n_unsourced=n_unsourced,
        n_refused_by_llm=n_refused_llm,
        n_sourced_verified_flagged=n_flagged,
        refused_sentences=refused,
        flagged_sentences=flagged,
    )

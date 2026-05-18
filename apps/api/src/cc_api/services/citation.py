# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vérification d'ancrage par phrase — règle d'or du pipeline RAG.

Le LLM produit sa dissertation en **sortie structurée** (`AnthropicClient.
generate`, tool-use forcé) : la réponse arrive déjà découpée en paragraphes et
en phrases, chaque phrase portant explicitement ses `citations` (source_ids) et
ses `citations_directes` (fragments cités mot pour mot). Ce module ne re-segmente
donc RIEN — il n'y a plus de découpage de prose par regex, donc plus de phrase
mal coupée ni de citation orpheline.

Règle d'or : aucune phrase ne doit affirmer quoi que ce soit qui ne soit
*soutenu* par un passage cité, et toute citation directe doit être littérale.
Deux gardes-fous, appliqués phrase par phrase :

1. **Contrôle littéral des citations directes** — chaque fragment de
   `citations_directes` doit apparaître mot pour mot (substring exact ou
   `rapidfuzz.partial_ratio ≥ seuil adaptatif`) dans l'un des chunks cités.

2. **Juge sémantique d'entailment** — chaque phrase d'analyse est soumise au
   2ᵉ passage LLM (`AnthropicClient.judge`, tool-use schématisé) qui statue
   ENTAILED / NOT_ENTAILED / CONTRADICTED.

Une phrase n'est `SUPPORTED` que si elle passe les deux contrôles. Tout autre
verdict casse `all_verified` : le pipeline écarte la phrase (mode partiel) ou
refuse la réponse — « le silence est préférable à la distorsion ».

Voir `.claude/rules/no-unsourced-rag.md` et `.claude/rules/citation-honest-vs-literal.md`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from rapidfuzz import fuzz

from cc_api.clients.anthropic import (
    AnthropicClient,
    GeneratedAnswer,
    GeneratedPhrase,
)
from cc_api.core.logging import get_logger

log = get_logger(__name__)

# Citation réservée : le LLM signale un refus explicite via `citations=["none"]`.
REFUSAL_CITATION = "none"


class CitationVerdict(str, Enum):  # noqa: UP042 — cohérence sérialisation
    """Verdict de vérification d'une phrase.

    - `SUPPORTED` : citations directes vérifiées littéralement ET juge sémantique
      ENTAILED. Seul verdict comptant comme « vérifié ».
    - `QUOTE_UNVERIFIED` : un fragment cité directement n'apparaît pas mot pour
      mot dans un chunk cité.
    - `NOT_SUPPORTED` : juge NOT_ENTAILED — la phrase affirme un élément que les
      passages cités ne soutiennent pas.
    - `CONTRADICTED` : juge CONTRADICTED — la phrase détourne ou inverse le sens
      du passage. Aussi grave qu'une hallucination.
    - `UNSOURCED` : aucune citation.
    - `REFUSED_BY_LLM` : refus explicite (`citations=["none"]`) — légitime.
    """

    SUPPORTED = "SUPPORTED"
    QUOTE_UNVERIFIED = "QUOTE_UNVERIFIED"
    NOT_SUPPORTED = "NOT_SUPPORTED"
    CONTRADICTED = "CONTRADICTED"
    UNSOURCED = "UNSOURCED"
    REFUSED_BY_LLM = "REFUSED_BY_LLM"


# Verdicts qui rendent une phrase légitimement exposable dans `answer`.
_LEGITIMATE = (CitationVerdict.SUPPORTED, CitationVerdict.REFUSED_BY_LLM)

_JUDGE_MAP = {
    "ENTAILED": CitationVerdict.SUPPORTED,
    "NOT_ENTAILED": CitationVerdict.NOT_SUPPORTED,
    "CONTRADICTED": CitationVerdict.CONTRADICTED,
}


@dataclass(frozen=True)
class SentenceVerdict:
    """Résultat de la vérification d'une phrase, et son rang dans la réponse."""

    phrase: GeneratedPhrase
    paragraphe: int  # index du paragraphe d'origine
    verdict: CitationVerdict
    best_score: float  # meilleur match littéral des citations directes (0..100)
    reason: str

    @property
    def text(self) -> str:
        return self.phrase.texte

    @property
    def citations(self) -> list[str]:
        return self.phrase.citations

    @property
    def verified(self) -> bool:
        """`True` si la phrase est légitimement exposable (SUPPORTED ou refus)."""
        return self.verdict in _LEGITIMATE


@dataclass(frozen=True)
class CitationReport:
    """Synthèse de la vérification d'une réponse complète.

    `all_verified` est `True` si chaque phrase est `SUPPORTED` ou
    `REFUSED_BY_LLM`. `flagged_sentences` liste les phrases `CONTRADICTED`
    (détournement sémantique) ; elles figurent aussi dans `refused_sentences`.
    """

    sentences: list[SentenceVerdict]
    all_verified: bool
    n_supported: int
    n_rejected: int
    n_refused_by_llm: int = 0
    n_contradicted: int = 0
    refused_sentences: list[str] = field(default_factory=list)
    flagged_sentences: list[str] = field(default_factory=list)


# --- Contrôle littéral ------------------------------------------------------

# Repli typographique : guillemets/apostrophes/tirets courbes → forme ASCII.
_TYPO_FOLD = str.maketrans(
    {
        0x00AB: '"', 0x00BB: '"',  # guillemets français
        0x201C: '"', 0x201D: '"',  # guillemets-virgules doubles
        0x2018: "'", 0x2019: "'",  # apostrophes courbes
        0x2013: "-", 0x2014: "-",  # tirets demi/cadratin
        0x2026: "...",  # points de suspension
    }
)


def _normalize(text: str) -> str:
    """Forme canonique pour comparaison littérale : typographie repliée,
    espaces compactés, minuscules, sans guillemets ni ponctuation de bord."""
    folded = re.sub(r'\s*"\s*', '"', text.translate(_TYPO_FOLD))
    folded = re.sub(r"\s+", " ", folded).lower().strip()
    return re.sub(r'^["\s.,;:!?]+|["\s.,;:!?]+$', "", folded)


def _adaptive_threshold(fragment: str, base_threshold: int) -> int:
    """Seuil fuzzy plus strict pour les fragments courts.

    `partial_ratio` est indulgent sur les fragments courts : on élève le seuil
    pour les fragments < 10 mots, jusqu'à 100 (substring exact requis).
    """
    n_words = len(fragment.split())
    if n_words >= 10:
        return base_threshold
    return min(100, base_threshold + (10 - n_words))


def _fragment_score(fragment: str, chunk_texts: list[str]) -> float:
    """Meilleur score (0..100) du `fragment` parmi les chunks cités.

    Substring exact → 100. Sinon `partial_ratio` maximal.
    """
    norm_fragment = _normalize(fragment)
    if not norm_fragment:
        return 0.0
    best = 0.0
    for chunk in chunk_texts:
        norm_chunk = re.sub(r"\s+", " ", chunk.translate(_TYPO_FOLD)).lower()
        if norm_fragment in norm_chunk:
            return 100.0
        best = max(best, float(fuzz.partial_ratio(norm_fragment, norm_chunk)))
    return best


# --- Classement local (sans LLM) --------------------------------------------

# Sentinelle : phrase qui a passé les contrôles locaux et attend le juge.
_PENDING = "pending"


def _classify(
    phrase: GeneratedPhrase, paragraphe: int, chunks: dict[str, str], fuzzy_threshold: int
) -> SentenceVerdict:
    """Pré-classement local d'une phrase, AVANT le juge sémantique.

    Tranche sans LLM : `UNSOURCED`, `REFUSED_BY_LLM`, `QUOTE_UNVERIFIED`, ou les
    cas où aucun chunk cité n'est disponible. Sinon renvoie un verdict provisoire
    de reason `pending` : la phrase doit passer le juge sémantique.
    """
    citations = phrase.citations
    if not citations:
        return SentenceVerdict(
            phrase, paragraphe, CitationVerdict.UNSOURCED, 0.0,
            "aucune citation : phrase non ancrée",
        )
    real = [c for c in citations if c != REFUSAL_CITATION]
    if not real:
        return SentenceVerdict(
            phrase, paragraphe, CitationVerdict.REFUSED_BY_LLM, 0.0,
            "refus explicite du LLM (citations=['none'])",
        )
    cited_texts = [chunks[c] for c in real if c in chunks]
    if not cited_texts:
        return SentenceVerdict(
            phrase, paragraphe, CitationVerdict.NOT_SUPPORTED, 0.0,
            f"aucun chunk cité ({real}) n'est présent dans le contexte fourni",
        )

    best_quote = 0.0
    for fragment in phrase.citations_directes:
        threshold = _adaptive_threshold(fragment, fuzzy_threshold)
        score = _fragment_score(fragment, cited_texts)
        best_quote = max(best_quote, score)
        if score < threshold:
            return SentenceVerdict(
                phrase, paragraphe, CitationVerdict.QUOTE_UNVERIFIED, score,
                f"citation directe « {fragment} » : meilleur match {score:.1f}% "
                f"< {threshold}% — non retrouvée mot pour mot dans {real}",
            )

    return SentenceVerdict(
        phrase, paragraphe, CitationVerdict.NOT_SUPPORTED, best_quote, _PENDING
    )


# --- Juge sémantique d'entailment -------------------------------------------

_JUDGE_SYSTEM = """Tu es relecteur scientifique d'une archive marxiste à \
standards de publication académique. On te donne des PHRASES extraites d'une \
réponse, et pour chacune le ou les PASSAGES sources qu'elle cite. Pour chaque \
phrase, statue UNIQUEMENT à partir des passages fournis — aucune connaissance \
extérieure — et appelle l'outil `rendre_verdicts` :

- ENTAILED : tout ce que la phrase affirme se déduit des passages cités, sans \
ajout, sans extrapolation, sans généralisation non fondée.
- NOT_ENTAILED : la phrase affirme un élément (fait, date, nom, thèse, nuance, \
lien) que les passages ne soutiennent pas.
- CONTRADICTED : la phrase dit le contraire d'un passage ou en détourne le sens \
— elle présente comme thèse de l'auteur un propos qu'il réfute, l'attribue à un \
adversaire, ou prend une question rhétorique pour une affirmation.

En cas de doute entre ENTAILED et NOT_ENTAILED, choisis NOT_ENTAILED : le \
silence est préférable à la distorsion."""


def _judge_payload(items: list[tuple[int, SentenceVerdict, list[str]]]) -> str:
    """Assemble le payload du juge : phrase + passages cités, indexés."""
    blocks: list[str] = []
    for idx, sv, cited_texts in items:
        real = [c for c in sv.citations if c != REFUSAL_CITATION]
        passages = "\n".join(
            f"--- {sid} ---\n{text}" for sid, text in zip(real, cited_texts, strict=False)
        )
        blocks.append(
            f"### Phrase {idx}\nAffirmation : {sv.text}\n"
            f"Passage(s) cité(s) :\n{passages}\n"
        )
    return "\n".join(blocks)


async def verify_response(
    answer: GeneratedAnswer,
    *,
    chunks: dict[str, str],
    anthropic: AnthropicClient,
    fuzzy_threshold: int = 95,
    verifier_enabled: bool = True,
    judge_model: str | None = None,
) -> CitationReport:
    """Vérifie l'ancrage de chaque phrase de la réponse structurée.

    1. Pré-classement local (`_classify`) — UNSOURCED / REFUSED / QUOTE_UNVERIFIED.
    2. Les phrases « pending » sont soumises en un seul appel au juge sémantique
       (`AnthropicClient.judge`), qui statue SUPPORTED / NOT_SUPPORTED /
       CONTRADICTED.
    3. Si `verifier_enabled` est faux (kill-switch), les phrases « pending » sont
       refusées par précaution (`NOT_SUPPORTED`) — jamais approuvées sans juge.
    """
    flat: list[tuple[int, GeneratedPhrase]] = [
        (para_idx, phrase)
        for para_idx, para in enumerate(answer.paragraphes)
        for phrase in para
    ]
    verdicts = [_classify(ph, pi, chunks, fuzzy_threshold) for pi, ph in flat]
    pending = [i for i, v in enumerate(verdicts) if v.reason == _PENDING]

    if pending and not verifier_enabled:
        for i in pending:
            v = verdicts[i]
            verdicts[i] = SentenceVerdict(
                v.phrase, v.paragraphe, CitationVerdict.NOT_SUPPORTED, v.best_score,
                "juge sémantique désactivé (kill-switch) — phrase refusée par précaution",
            )
    elif pending:
        items: list[tuple[int, SentenceVerdict, list[str]]] = []
        for i in pending:
            v = verdicts[i]
            real = [c for c in v.citations if c != REFUSAL_CITATION]
            items.append((i, v, [chunks[c] for c in real if c in chunks]))
        raw = await anthropic.judge(
            system=_JUDGE_SYSTEM, payload=_judge_payload(items), model=judge_model
        )
        judged = {jv.index: jv for jv in raw}
        for i in pending:
            v = verdicts[i]
            jv = judged.get(i)
            if jv is None:
                verdicts[i] = SentenceVerdict(
                    v.phrase, v.paragraphe, CitationVerdict.NOT_SUPPORTED, v.best_score,
                    "juge sémantique : phrase non évaluée — rejetée par précaution",
                )
                continue
            new_verdict = _JUDGE_MAP.get(jv.verdict, CitationVerdict.NOT_SUPPORTED)
            verdicts[i] = SentenceVerdict(
                v.phrase, v.paragraphe, new_verdict, v.best_score,
                f"juge sémantique : {jv.verdict} — {jv.justification}",
            )

    n_supported = sum(1 for v in verdicts if v.verdict == CitationVerdict.SUPPORTED)
    n_refused_llm = sum(1 for v in verdicts if v.verdict == CitationVerdict.REFUSED_BY_LLM)
    n_contradicted = sum(1 for v in verdicts if v.verdict == CitationVerdict.CONTRADICTED)
    refused = [v.text for v in verdicts if not v.verified]
    flagged = [v.text for v in verdicts if v.verdict == CitationVerdict.CONTRADICTED]
    all_ok = len(verdicts) > 0 and all(v.verified for v in verdicts)
    log.info(
        "citation.verified",
        n_sentences=len(verdicts),
        n_supported=n_supported,
        n_rejected=len(refused),
        n_contradicted=n_contradicted,
        all_verified=all_ok,
    )
    return CitationReport(
        sentences=verdicts,
        all_verified=all_ok,
        n_supported=n_supported,
        n_rejected=len(refused),
        n_refused_by_llm=n_refused_llm,
        n_contradicted=n_contradicted,
        refused_sentences=refused,
        flagged_sentences=flagged,
    )


def assemble_answer(verdicts: list[SentenceVerdict], *, only_verified: bool) -> str:
    """Reconstruit le texte de la réponse à partir des phrases.

    `only_verified=True` (mode partiel) ne garde que les phrases `verified`.
    Les paragraphes d'origine sont préservés (séparés par une ligne vide).
    """
    paragraphs: dict[int, list[str]] = {}
    for v in verdicts:
        if only_verified and not v.verified:
            continue
        paragraphs.setdefault(v.paragraphe, []).append(v.text)
    return "\n\n".join(
        " ".join(textes) for _, textes in sorted(paragraphs.items()) if textes
    )

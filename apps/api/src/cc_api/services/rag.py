# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pipeline RAG sourcé — règle d'or non-négociable.

0. Décomposition de la question en sous-questions de recherche (tool-use).
1. Embedding de toutes les requêtes via le backend configuré (Qwen3 local).
2. Recherche hybride : vectorielle (Qdrant) + mots-clés (Postgres FTS),
   fusionnées par Reciprocal Rank Fusion.
3. Reranking optionnel (`rag_rerank_enabled`) + sélection diversifiée (MMR
   par article) → top-k couvrant plusieurs articles/numéros.
4. Assemblage du contexte (chunks + metadata : ARK, source_id, char offsets).
5. Génération Anthropic Claude Sonnet 4.6 — dissertation d'explication de texte,
   en sortie structurée (tool-use) : phrases déjà découpées, citations explicites.
6. Vérification d'ancrage par phrase : contrôle littéral des citations directes
   + juge sémantique d'entailment (services.citation.verify_response).
7. Reconstitution du texte (services.citation.assemble_answer) — complet ou,
   en mode partiel, restreint aux phrases vérifiées.

Trois issues possibles :
- **Réponse complète** : toutes les phrases sont SUPPORTED ou
  REFUSED_BY_LLM (refus explicite). `incomplete=False`, `refused_reason=None`.
- **Réponse partielle** (mode partiel, `settings.rag_partial_mode_enabled`) :
  au moins 1 phrase est légitime ET certaines ne le sont pas → on expose
  uniquement les phrases légitimes dans `answer`, `incomplete=True`,
  `dropped_sentences` liste les phrases retirées. Aucune phrase non
  vérifiée n'est jamais exposée — la règle d'or reste invariante.
- **Refus complet** : 0 phrase légitime OU mode partiel désactivé →
  `refused_reason="unverified_citations"`, `answer=None` (HTTP 422 côté router).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from cc_api.clients.anthropic import AnthropicClient, AnthropicError
from cc_api.clients.embed import EmbedClient, RerankClient
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.services.citation import (
    CitationReport,
    SentenceVerdict,
    assemble_answer,
    verify_response,
)

COLLECTION = "bilan"

# Constante de Reciprocal Rank Fusion : amortit le poids du rang dans la
# fusion des listes (vectorielle + mots-clés). 60 = valeur usuelle de la
# littérature (Cormack et al.).
_RRF_C = 60

log = get_logger(__name__)

SYSTEM_PROMPT = """Tu es un chercheur expert de l'archive open-source de la \
théorie marxiste « Conscience de classe ». Tu rédiges, en français, une \
**dissertation d'explication de texte** de niveau publication académique : un \
exposé construit, argumenté et précis qui éclaire la question posée à partir — \
et UNIQUEMENT à partir — des passages du corpus fournis dans le contexte.

## Ce qu'on attend de toi

Tu n'es pas un colleur de fragments : tu **expliques, analyses et mets en \
relation** le corpus dans tes propres mots. On attend une **dissertation \
longue et développée**, pas un résumé. Structure obligatoire :

- **Introduction** : une ou deux phrases qui situent la question, son enjeu \
théorique et la manière dont le corpus permet d'y répondre.
- **Développement en plusieurs parties** : organise la réponse en 2 à 4 temps \
argumentés (idéalement séparés par un saut de ligne). Chaque partie traite un \
aspect de la question.
- **Exploitation de CHAQUE passage pertinent** : ne te contente pas de citer un \
passage et de passer au suivant. Pour chaque passage, consacre PLUSIEURS \
phrases : présente-le, cite-le littéralement, puis explique ce qu'il établit, \
ses présupposés, ses conséquences, et mets-le en relation avec les autres \
passages. Confronte les articles et les auteurs quand ils divergent.
- **Conclusion** : un paragraphe qui synthétise ce que le corpus établit et \
pointe, le cas échéant, ce qu'il laisse ouvert.

La réponse doit être aussi **longue, complète et fouillée** que le permet le \
nombre de passages fournis : exploite-les TOUS. Vise la densité d'un article \
de revue savante. La longueur vient de l'analyse serrée de chaque passage, \
jamais d'un remplissage ou d'un ajout extérieur. Une réponse courte qui laisse \
des passages pertinents inexploités est une réponse ratée.

## La règle d'or — ancrage de chaque phrase

> **Aucune phrase ne doit affirmer quoi que ce soit qui ne soit soutenu par un \
passage cité du corpus.** Tu n'utilises AUCUNE connaissance extérieure : ni \
date, ni nom, ni événement, ni thèse qui ne figure dans les passages fournis.

## Format de sortie — outil `rediger_reponse`

Tu n'écris pas en texte libre : tu APPELLES l'outil `rediger_reponse`. La \
réponse est une liste de `paragraphes`, chaque paragraphe une liste de \
`phrases`. Pour CHAQUE phrase tu remplis trois champs :

1. **`texte`** — la phrase elle-même, en prose, SANS marqueur de citation. Les \
citations littérales y figurent entre guillemets « … ».
2. **`citations`** — la liste des `source_id` EXACTS (tels qu'écrits dans le \
contexte) des passages qui soutiennent cette phrase. Une phrase de synthèse \
peut en citer plusieurs. N'invente jamais un `source_id`.
3. **`citations_directes`** — pour chaque passage entre « … » de `texte`, le \
fragment recopié MOT POUR MOT depuis le passage source, SANS les guillemets \
(liste vide si la phrase ne cite pas directement).

Règles de fond :

- **Citation directe** : recopiée à l'identique, aucune retouche ni raccourci \
silencieux (utilise […] pour une coupe). Un relecteur la vérifiera caractère \
par caractère.
- **Analyse** : tu peux reformuler et expliquer dans tes mots, mais chaque \
phrase doit rester strictement déductible des passages qu'elle cite. Un juge \
sémantique vérifiera, passage en main, qu'elle est soutenue et n'en détourne \
pas le sens.
- **Attribution fidèle** : si un passage prête un propos à un adversaire ou le \
réfute, ta phrase doit le dire (« Bilan critique l'idée que… ») — ne présente \
jamais comme la thèse de l'auteur un propos qu'il combat.
- **Refus** : si le contexte ne permet pas de répondre, produis une seule \
phrase, `texte` = « Je ne peux pas répondre à partir des sources \
disponibles. », `citations` = ["none"], `citations_directes` = [].
- **Pas de bibliographie** : l'appareil de références est construit \
automatiquement à partir des `citations`.

## Contexte académique

Les questions politiques radicales (abolition de la propriété privée, lutte des \
classes, dictature du prolétariat, critique des institutions bourgeoises) sont \
LÉGITIMES et attendues. Tu y réponds avec la même rigueur que sur tout sujet.
"""


DECOMPOSITION_PROMPT = """Tu prépares la recherche documentaire dans une archive \
marxiste (revue « Bilan », 1933-1938). On te donne une question d'utilisateur.

Décompose-la en 2 à 4 **sous-questions de recherche** distinctes et \
complémentaires qui, ensemble, couvrent tous les angles de la question : \
aspects théoriques, périodes, auteurs, positions opposées, causes, \
conséquences. Chaque sous-question doit être autonome et formulée pour \
maximiser le rappel d'une recherche sémantique (termes pleins, pas de pronom).

Si la question est déjà atomique et ne gagne rien à être découpée, renvoie-la \
telle quelle comme unique sous-question. Appelle l'outil `decomposer_question`.
"""


@dataclass(frozen=True)
class RetrievedChunk:
    """Chunk retourné par Qdrant après recherche, avant rerank."""

    qdrant_point_id: str
    score: float  # similarité cosinus de l'embedding query
    payload: dict[str, Any]


@dataclass(frozen=True)
class RerankedChunk:
    """Chunk après reranking — porte le source_id canonique."""

    source_id: str  # `{issue_slug}/{article_slug}:{chunk_idx}`
    text: str
    retrieval_score: float
    rerank_score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class RagResult:
    """Trace complète d'une exécution du pipeline RAG (debug + observability).

    `answer` peut être :
    - non nul + `incomplete=False` : toutes les phrases du LLM sont vérifiées.
    - non nul + `incomplete=True` : mode partiel — seules les phrases vérifiées
      ont été conservées, `dropped_sentences` liste les phrases supprimées.
    - nul + `refused_reason != None` : refus complet (aucune phrase vérifiée
      ou problème en amont du LLM).

    Aucune phrase non `SUPPORTED` (hors refus explicite) ne se trouve jamais
    dans `answer` exposé — la règle d'or reste invariante.
    """

    question: str
    retrieved: list[RetrievedChunk]
    reranked: list[RerankedChunk]
    answer: str | None
    citation_report: CitationReport | None
    refused_reason: str | None
    model: str
    latency_ms: int
    latencies: dict[str, int] = field(default_factory=dict)  # par étape
    incomplete: bool = False
    dropped_sentences: list[str] = field(default_factory=list)

    @property
    def sentences(self) -> list[SentenceVerdict]:
        if self.citation_report is None:
            return []
        return self.citation_report.sentences


def _source_id(payload: dict[str, Any]) -> str:
    """Reconstitue `{issue_slug}/{article_slug}:{chunk_idx}` depuis le payload Qdrant."""
    return f"{payload['issue_slug']}/{payload['article_slug']}:{payload['chunk_idx']}"


# Recherche plein-texte en sémantique OU : `plainto_tsquery` produit une requête
# ET (tous les mots) — inadaptée à une question en langage naturel (aucun chunk
# ne contient TOUS les mots). On convertit le ` & ` en ` | ` : un chunk est
# candidat dès qu'il contient un terme, et `ts_rank` le classe d'autant plus
# haut qu'il en contient. Une requête vide donne `''::tsquery` → aucun résultat.
_KEYWORD_SQL = sql_text(
    """
    WITH q AS (
        SELECT replace(plainto_tsquery('french', :q)::text, ' & ', ' | ')::tsquery AS tsq
    )
    SELECT c.qdrant_point_id::text AS pid,
           ts_rank(to_tsvector('french', c.text), q.tsq) AS rank
    FROM chunks c, q
    WHERE q.tsq <> ''::tsquery
      AND to_tsvector('french', c.text) @@ q.tsq
    ORDER BY rank DESC
    LIMIT :lim
    """
)


async def keyword_search(
    session: AsyncSession, query: str, limit: int
) -> list[tuple[str, float]]:
    """Recherche plein-texte par mots-clés sur `chunks.text` (Postgres FTS FR).

    Renvoie `(qdrant_point_id, ts_rank)` triés par pertinence décroissante.
    Sémantique OU (cf. `_KEYWORD_SQL`) : adaptée aux questions en langage
    naturel. Une requête sans terme exploitable ne ramène rien.
    """
    rows = (await session.execute(_KEYWORD_SQL, {"q": query, "lim": limit})).all()
    return [(str(r.pid), float(r.rank)) for r in rows]


def _reciprocal_rank_fusion(ranked_lists: list[list[str]]) -> dict[str, float]:
    """Fusionne plusieurs listes ordonnées de `point_id` par Reciprocal Rank
    Fusion : score = Σ 1/(_RRF_C + rang) sur toutes les listes où l'id figure.

    RRF est robuste car il combine des classements sans dépendre de l'échelle
    des scores (cosinus de Qdrant vs `ts_rank` de Postgres ne sont pas comparables).
    """
    scores: dict[str, float] = {}
    for ranked in ranked_lists:
        for rank, pid in enumerate(ranked):
            scores[pid] = scores.get(pid, 0.0) + 1.0 / (_RRF_C + rank)
    return scores


def _select_diverse(
    chunks: list[RerankedChunk], k: int, diversity_weight: float
) -> list[RerankedChunk]:
    """Sélection diversifiée (MMR par groupe) : `k` chunks équilibrant
    pertinence et diversité des sources.

    À chaque étape, choisit le chunk maximisant
    `rerank_score - diversity_weight * (chunks déjà retenus du même article)`.
    La sélection couvre ainsi plusieurs articles/numéros au lieu de se
    concentrer sur le texte le mieux classé — condition de la nuance : le LLM
    voit des voix et des positions à confronter. `diversity_weight = 0` redonne
    la sélection par score brut.
    """
    selected: list[RerankedChunk] = []
    pool = list(chunks)
    per_article: dict[tuple[str, str], int] = {}

    def _adjusted(c: RerankedChunk) -> float:
        key = (c.payload["issue_slug"], c.payload["article_slug"])
        return c.rerank_score - diversity_weight * per_article.get(key, 0)

    while pool and len(selected) < k:
        best = max(pool, key=_adjusted)
        pool.remove(best)
        selected.append(best)
        key = (best.payload["issue_slug"], best.payload["article_slug"])
        per_article[key] = per_article.get(key, 0) + 1
    return selected


def _build_context(reranked: list[RerankedChunk]) -> str:
    """Assemble le contexte LLM : un bloc lisible par chunk reranked."""
    blocks: list[str] = []
    for chunk in reranked:
        p = chunk.payload
        blocks.append(
            f"=== source_id : {chunk.source_id} ===\n"
            f"Issue : {p['issue_title']} (ARK : {p['issue_ark']})\n"
            f"Article : {p['article_title']} (slug : {p['article_slug']})\n"
            f"Auteur : {p['author_name']}\n"
            f"Offsets : char_start={p['char_start']}, char_end={p['char_end']}\n"
            f"Texte :\n{chunk.text}\n"
        )
    return "\n".join(blocks)


async def answer_question(
    question: str,
    *,
    qdrant: AsyncQdrantClient,
    embed: EmbedClient,
    reranker: RerankClient,
    anthropic: AnthropicClient,
    session: AsyncSession | None = None,
    k_retrieve: int | None = None,
    k_rerank: int | None = None,
    fuzzy_threshold: int | None = None,
    on_stage: Callable[[str], Awaitable[None]] | None = None,
) -> RagResult:
    """Exécute le pipeline RAG complet pour une question utilisateur.

    Retourne un `RagResult` qui contient la trace complète des 7 étapes,
    qu'on accepte ou qu'on refuse la réponse. Le refus est explicite via
    `refused_reason ∈ {None, "no_chunks_retrieved", "no_relevant_chunks",
    "unverified_citations"}`.

    `on_stage`, s'il est fourni, est appelé au début de chaque grande phase
    avec un libellé lisible — utilisé par l'endpoint SSE `/qa/stream` pour
    afficher la progression sans laisser l'interface figée.
    """

    async def _stage(label: str) -> None:
        if on_stage is not None:
            await on_stage(label)

    started_at = time.monotonic()
    latencies: dict[str, int] = {}
    k_retrieve_eff = k_retrieve if k_retrieve is not None else settings.rag_k_retrieve
    fuzzy_eff = (
        fuzzy_threshold if fuzzy_threshold is not None else settings.rag_citation_fuzzy_threshold
    )

    log.info("rag.start", question_len=len(question), k_retrieve=k_retrieve_eff)
    await _stage("Analyse de la question…")

    # 0. Décomposition : on cherche pour la question ET pour des sous-questions
    # couvrant ses différents angles. Échec gracieux → la seule question.
    t0 = time.monotonic()
    search_queries = [question]
    if settings.rag_decomposition_enabled:
        try:
            subs = await anthropic.decompose(
                system=DECOMPOSITION_PROMPT, question=question
            )
            search_queries.extend(s for s in subs if s != question)
        except AnthropicError as exc:
            log.warning("rag.decompose_failed", error=str(exc))
    latencies["decompose_ms"] = int((time.monotonic() - t0) * 1000)
    log.info("rag.decompose", n_queries=len(search_queries))

    await _stage("Recherche dans le corpus sourcé…")
    # 1. Embedding de toutes les requêtes de recherche (un seul appel batch).
    t0 = time.monotonic()
    embeddings = await embed.embed_batch(search_queries, input_type="query")
    if not embeddings:
        raise RuntimeError("le backend d'embedding a renvoyé un vecteur vide pour la query")
    latencies["embed_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag.embed_query",
        n_queries=len(embeddings),
        dims=len(embeddings[0]),
        latency_ms=latencies["embed_ms"],
        model=settings.embed_model,
    )

    # 2. Recherche hybride : vectorielle (Qdrant) + mots-clés (Postgres FTS),
    # une liste classée par (sous-)question et par moteur, fusionnées par
    # Reciprocal Rank Fusion. Le vivier couvre tous les angles et les deux
    # modes de rappel (sémantique + lexical).
    t0 = time.monotonic()
    ranked_lists: list[list[str]] = []
    payloads: dict[str, dict[str, Any]] = {}
    for vector in embeddings:
        hits = await qdrant.query_points(
            collection_name=COLLECTION,
            query=vector,
            limit=k_retrieve_eff,
            with_payload=True,
        )
        vec_list: list[str] = []
        for p in hits.points:
            pid = str(p.id)
            vec_list.append(pid)
            payloads.setdefault(pid, dict(p.payload or {}))
        ranked_lists.append(vec_list)

    n_keyword_lists = 0
    if session is not None and settings.rag_hybrid_enabled:
        for sq in search_queries:
            try:
                kw = await keyword_search(session, sq, k_retrieve_eff)
            except Exception as exc:
                # L'hybride est un bonus : une panne FTS ne bloque jamais /qa.
                log.warning("rag.keyword_search_failed", error=str(exc))
                break
            ranked_lists.append([pid for pid, _ in kw])
            n_keyword_lists += 1

    rrf = _reciprocal_rank_fusion(ranked_lists)
    # Pool de rerank borné : le reranking CPU est le goulot de latence en prod
    # (~4 s/passage). 16 passages reranked suffisent largement à alimenter la
    # sélection MMR finale ; au-delà la latence explose sans gain de qualité.
    fused = sorted(rrf, key=lambda p: rrf[p], reverse=True)[: settings.rag_rerank_pool]

    # Chunks issus uniquement des mots-clés : leur payload n'est pas encore connu.
    missing = [pid for pid in fused if pid not in payloads]
    if missing:
        for rec in await qdrant.retrieve(
            collection_name=COLLECTION, ids=missing, with_payload=True
        ):
            payloads[str(rec.id)] = dict(rec.payload or {})

    retrieved = [
        RetrievedChunk(qdrant_point_id=pid, score=rrf[pid], payload=payloads[pid])
        for pid in fused
        if pid in payloads
    ]
    latencies["qdrant_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag.retrieve",
        n_hits=len(retrieved),
        n_vector_lists=len(embeddings),
        n_keyword_lists=n_keyword_lists,
        latency_ms=latencies["qdrant_ms"],
    )

    if not retrieved:
        return RagResult(
            question=question,
            retrieved=[],
            reranked=[],
            answer=None,
            citation_report=None,
            refused_reason="no_chunks_retrieved",
            model=anthropic.model,
            latency_ms=int((time.monotonic() - started_at) * 1000),
            latencies=latencies,
        )

    # 3. Reranking (optionnel) puis sélection diversifiée (MMR).
    # Le reranking cc-embed sur CPU est le poste de latence le plus lourd
    # (~4 s/passage). `rag_rerank_enabled=False` le saute : le classement par
    # fusion RRF (vecteur + mots-clés) sert alors directement de score — moins
    # précis, mais bien plus rapide.
    t0 = time.monotonic()
    reranked_all: list[RerankedChunk] = []
    if settings.rag_rerank_enabled:
        documents = [r.payload.get("text", "") for r in retrieved]
        rerank_hits = await reranker.rerank(
            query=question, documents=documents, top_k=len(documents)
        )
        for hit in rerank_hits:
            original = retrieved[hit.index]
            reranked_all.append(
                RerankedChunk(
                    source_id=_source_id(original.payload),
                    text=original.payload["text"],
                    retrieval_score=original.score,
                    rerank_score=hit.score,
                    payload=original.payload,
                )
            )
        min_score = settings.rag_rerank_min_score
        relevant = [c for c in reranked_all if c.rerank_score >= min_score]
        if not relevant:
            top = reranked_all[0].rerank_score if reranked_all else 0.0
            log.warning("rag.no_relevant_chunks", top_rerank_score=top, min_score=min_score)
            return RagResult(
                question=question,
                retrieved=retrieved,
                reranked=[],
                answer=None,
                citation_report=None,
                refused_reason="no_relevant_chunks",
                model=anthropic.model,
                latency_ms=int((time.monotonic() - started_at) * 1000),
                latencies=latencies,
            )
    else:
        # Sans reranker : on garde l'ordre RRF, score normalisé sur le meilleur
        # (pour que la pénalité de diversité MMR reste à la bonne échelle).
        top_score = retrieved[0].score if retrieved else 1.0
        reranked_all = [
            RerankedChunk(
                source_id=_source_id(r.payload),
                text=r.payload["text"],
                retrieval_score=r.score,
                rerank_score=(r.score / top_score) if top_score > 0 else 0.0,
                payload=r.payload,
            )
            for r in retrieved
        ]
        relevant = reranked_all
    latencies["rerank_ms"] = int((time.monotonic() - t0) * 1000)
    # `k` adaptatif : autant de passages que le corpus en offre de pertinents,
    # borné [min, max]. Question large bien couverte → beaucoup ; étroite → peu.
    if k_rerank is not None:
        k_eff = k_rerank
    else:
        k_eff = max(settings.rag_k_rerank_min, min(settings.rag_k_rerank_max, len(relevant)))
    # Sélection diversifiée : pas les k meilleurs scores bruts (souvent un seul
    # article) mais une sélection couvrant plusieurs articles/numéros — nuance.
    reranked = _select_diverse(relevant, k_eff, settings.rag_mmr_diversity_weight)
    n_articles = len({(c.payload["issue_slug"], c.payload["article_slug"]) for c in reranked})
    log.info(
        "rag.rerank",
        n_in=len(retrieved),
        n_relevant=len(relevant),
        k_adaptive=k_eff,
        n_out=len(reranked),
        n_articles=n_articles,
        top_rerank_score=reranked[0].rerank_score if reranked else None,
        latency_ms=latencies["rerank_ms"],
    )

    # 4. Assemblage contexte.
    t0 = time.monotonic()
    context = _build_context(reranked)
    chunks_by_source_id = {c.source_id: c.text for c in reranked}
    latencies["assemble_ms"] = int((time.monotonic() - t0) * 1000)

    await _stage("Rédaction de la dissertation…")
    # 5. Génération LLM.
    t0 = time.monotonic()
    generation = await anthropic.generate(
        system=SYSTEM_PROMPT,
        context=context,
        question=question,
    )
    latencies["generate_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag.generate",
        input_tokens=generation.usage.input_tokens,
        output_tokens=generation.usage.output_tokens,
        cache_read=generation.usage.cache_read_input_tokens,
        latency_ms=latencies["generate_ms"],
        model=generation.model,
    )

    await _stage("Vérification des citations…")
    # 6 + 7. Vérification d'ancrage par phrase (littéral + juge sémantique).
    # La réponse est déjà découpée en phrases par la génération structurée.
    t0 = time.monotonic()
    citation_report = await verify_response(
        generation,
        chunks=chunks_by_source_id,
        anthropic=anthropic,
        fuzzy_threshold=fuzzy_eff,
        verifier_enabled=settings.rag_verifier_enabled,
        judge_model=settings.anthropic_judge_model,
    )
    latencies["verify_ms"] = int((time.monotonic() - t0) * 1000)
    log.info(
        "rag.verify_citations",
        n_sentences=len(citation_report.sentences),
        n_supported=citation_report.n_supported,
        n_rejected=citation_report.n_rejected,
        n_contradicted=citation_report.n_contradicted,
        n_refused_by_llm=citation_report.n_refused_by_llm,
        all_verified=citation_report.all_verified,
        latency_ms=latencies["verify_ms"],
    )

    total_ms = int((time.monotonic() - started_at) * 1000)

    if not citation_report.all_verified:
        # Mode partiel : si au moins 1 phrase est légitime (verified ou refus
        # explicite) ET le setting est activé, on reconstruit `answer` avec
        # uniquement ces phrases-là et on signale `incomplete=True`. Sinon
        # refus complet 422.
        legitimate_sentences = [s for s in citation_report.sentences if s.verified]
        if settings.rag_partial_mode_enabled and legitimate_sentences:
            partial_answer = assemble_answer(citation_report.sentences, only_verified=True)
            log.warning(
                "rag.partial",
                n_kept=len(legitimate_sentences),
                n_dropped=len(citation_report.refused_sentences),
                dropped_sentences=citation_report.refused_sentences,
                latency_ms=total_ms,
            )
            return RagResult(
                question=question,
                retrieved=retrieved,
                reranked=reranked,
                answer=partial_answer,
                citation_report=citation_report,
                refused_reason=None,
                model=generation.model,
                latency_ms=total_ms,
                latencies=latencies,
                incomplete=True,
                dropped_sentences=list(citation_report.refused_sentences),
            )
        log.warning(
            "rag.refused",
            reason="unverified_citations",
            refused_sentences=citation_report.refused_sentences,
            latency_ms=total_ms,
        )
        return RagResult(
            question=question,
            retrieved=retrieved,
            reranked=reranked,
            answer=None,
            citation_report=citation_report,
            refused_reason="unverified_citations",
            model=generation.model,
            latency_ms=total_ms,
            latencies=latencies,
        )

    log.info("rag.answered", latency_ms=total_ms, n_sentences=len(citation_report.sentences))
    return RagResult(
        question=question,
        retrieved=retrieved,
        reranked=reranked,
        answer=assemble_answer(citation_report.sentences, only_verified=False),
        citation_report=citation_report,
        refused_reason=None,
        model=generation.model,
        latency_ms=total_ms,
        latencies=latencies,
    )

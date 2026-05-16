---
name: debug-rag
description: Dumper l'intégralité du pipeline RAG pour une question donnée — embedding query, top-k Qdrant, reranking, contexte assemblé, prompt final, réponse LLM, et vérification que CHAQUE phrase de la réponse est citée et que la citation est littéralement présente dans le passage source. Cœur de la règle d'or RAG.
---

# /debug-rag — Inspection du pipeline RAG

Tu prends une question utilisateur (en français) et tu dumps chaque étape du pipeline RAG. Tu termines par la vérification de citation, qui est **non-négociable** : aucune phrase produite par le pipeline ne doit exister sans citation littéralement vérifiable dans le corpus source.

Voir `.claude/rules/no-unsourced-rag.md`, `[[feedback_no_unsourced_answers]]`, et `apps/api/src/cc_api/services/rag.py` (`answer_question`).

## Entrée

Une question en français. Si non précisée, demander à l'utilisateur.

## Pré-flight (étape 0)

Vérifier avant tout que les services et clés sont prêts :

```bash
# Services up (postgres, qdrant, redis) + alembic head + corpus seedé.
make agent-status

# Clés API présentes dans l'env (ne JAMAIS les afficher en clair) :
grep -E "^(ANTHROPIC_API_KEY|VOYAGE_API_KEY)" .env >/dev/null && echo "keys ok"

# Corpus Bilan ingéré :
curl -sf http://localhost:8000/__debug/state | jq '.postgres.tables, .qdrant'
```

Si manquant : `make agent-bootstrap`, puis `POST /__debug/seed` (fixture canonique) ou `uv run cc-corpus ingest corpus/bilan/bilan-001.tei.xml` (corpus réel).

## Pipeline réel à inspecter

Le pipeline est implémenté dans `apps/api/src/cc_api/services/rag.py:answer_question`. Pour un dump interactif, deux options :

**Option A — Via l'endpoint HTTP** (déclenche le vrai pipeline + retourne la trace dans `QaResponse`) :

```bash
curl -sf -X POST http://localhost:8000/qa \
  -H 'Content-Type: application/json' \
  -d '{"question":"<la question>"}' | jq
```

La réponse contient déjà `sentences[*].citations`, `sentences[*].verified`, `sentences[*].bestScore`, `sentences[*].reason`, et `citedChunks[*]` avec `sourceId`, `issueArk`, `articleArk`, `charStart`, `charEnd`, `retrievalScore`, `rerankScore`, `quotedText`. Le 422 est explicit en cas de refus avec `refusedReason` et `refusedSentences`.

**Option B — Appel direct du service** (pour debug avec contexte modifiable, dans un REPL Python ou un script) :

```python
import asyncio
from cc_api.clients.anthropic import get_anthropic_client
from cc_api.clients.qdrant import get_qdrant
from cc_api.clients.voyage import get_voyage_client
from cc_api.clients.voyage_rerank import get_voyage_rerank_client
from cc_api.services.rag import answer_question

async def main(q: str) -> None:
    result = await answer_question(
        q,
        qdrant=get_qdrant(),
        voyage_embed=get_voyage_client(),
        voyage_rerank=get_voyage_rerank_client(),
        anthropic=get_anthropic_client(),
    )
    print(result)  # RagResult contient TOUTES les étapes

asyncio.run(main("Que dit Bilan sur le bureau international d'information ?"))
```

## Les 7 étapes que le dump doit exposer

1. **Embedding query** : `voyage-4` (1024 dims). Dump : `query`, `dimensions`, premières valeurs du vecteur.
2. **Qdrant top-k retrieve** : `k_retrieve=20` par défaut (`settings.rag_k_retrieve`). Dump : par hit, `qdrant_point_id`, `score`, `payload[issue_slug, article_slug, chunk_idx, char_start, char_end]`, et 200 premiers caractères de `payload[text]`.
3. **Rerank** : Voyage `rerank-2.5`, sortie `k_rerank=5`. Dump : nouveaux scores et changements d'ordre par rapport à l'étape 2.
4. **Contexte assemblé** : 5 chunks avec `source_id = {issue_slug}/{article_slug}:{chunk_idx}` + ARK + offsets. Dump : longueur totale tokens, liste des `source_id` retenus.
5. **Prompt final** : système (`SYSTEM_PROMPT` de `rag.py` — règle d'or stricte) + contexte assemblé + question. Dump : prompt complet (tronqué si > 1000 lignes).
6. **Réponse brute LLM** : texte intégral retourné par Claude Opus 4.7. Dump : tel quel.
7. **Vérification citation par phrase** — étape critique :
   - Découpage en phrases via `services.citation.split_sentences` (gère abréviations FR + rattache les `[CITE:...]` à la phrase précédente).
   - Pour chaque phrase : extraction des `source_id` cités via regex `\[CITE:([^\]\s]+)\]`, puis vérification que le texte de la phrase apparaît dans le chunk pointé :
     * **substring exact** (insensible casse/espace, ponctuation finale trimmed),
     * sinon **`rapidfuzz.fuzz.partial_ratio ≥ 95`** (seuil configurable via `settings.rag_citation_fuzzy_threshold`).
   - Marquer chaque phrase : `✅ SOURCED_VERIFIED` / `⚠️ SOURCED_UNVERIFIED` / `❌ UNSOURCED`.

## Verdict final

Trois sorties possibles selon `result` :

- **Réponse complète** (`refused_reason is None`, `incomplete=False`) : afficher la réponse intégrale. Toutes les phrases sont ✅ SOURCED_VERIFIED ou ⓘ REFUSED_BY_LLM.
- **Réponse partielle** (`refused_reason is None`, `incomplete=True`) : afficher uniquement `answer` (phrases vérifiées seules) ET un disclaimer : « ⚠ Réponse partielle : N phrase(s) retirée(s) pour défaut de citation : … ». La liste est dans `result.dropped_sentences`. Mode contrôlé par `settings.rag_partial_mode_enabled`.
- **Refus complet** (`refused_reason="unverified_citations"`, HTTP 422) : afficher le détail des phrases problématiques (`result.citation_report.refused_sentences`), proposer :
  - (a) re-essayer avec contraintes plus serrées (réduire `k_rerank` ou augmenter le seuil fuzzy),
  - (b) déclarer ne pas savoir,
  - (c) demander à l'utilisateur si le seuil fuzzy doit être ajusté (jamais en dessous de 90 sans justification écrite).

**Verdict par phrase** (`result.sentences[i].verdict`) :
- ✅ `SOURCED_VERIFIED` : phrase littéralement adossée à un chunk.
- ⓘ `REFUSED_BY_LLM` : refus explicite via `[CITE:none]` (légitime).
- ⚠️ `SOURCED_UNVERIFIED` : phrase citée mais texte non retrouvable dans le chunk.
- ❌ `UNSOURCED` : aucune citation `[CITE:...]` détectée.

## Format de sortie attendu du skill

```
═══ /debug-rag : « {question} » ═══

[0] Pre-flight                : services ✓, ANTHROPIC_API_KEY ✓, VOYAGE_API_KEY ✓
[1] Embedding query           : voyage-4, 1024d, début=[0.012, -0.045, …]
[2] Qdrant top-20             :
    1. {source_id_1}  retrieval=0.871  "…"
    2. {source_id_2}  retrieval=0.852  "…"
    … (jusqu'à 20)
[3] Rerank top-5              : ordre = (2, 1, 5, 8, 3), top_rerank=0.95
[4] Contexte assemblé         : 5 chunks, ~2410 tokens, source_ids=[…]
[5] Prompt système + contexte : (tronqué si > 1000 lignes ; afficher uniquement le système + 1er chunk)
[6] Réponse brute LLM         : « … »
[7] Vérification citation :
    Phrase 1: "…"   ✅  cite={src1} score=100.0 reason="substring exact dans src1"
    Phrase 2: "…"   ❌  cite=[] reason="aucune citation [CITE:source_id] détectée"
    Phrase 3: "…"   ⚠️  cite={src2} score=82.4 reason="meilleur fuzzy 82.4% < 95% (source candidate : src2)"

VERDICT : ❌ 2 phrases non conformes → réponse refusée (HTTP 422).
```

## Anti-patterns à refuser

- Phrase « probablement de Marx » sans `source_id` concret.
- Citation paraphrasée (« Marx dit en substance que… »).
- Tolérance « ça doit être quelque part dans Capital ».
- Hallucination de titres ou de pages.
- Abaisser le seuil fuzzy sous 90 sans justification écrite et accord utilisateur.
- Modifier le `SYSTEM_PROMPT` pour relâcher la règle de citation par phrase.

## En cas d'investigation

- Pour comparer une question à plusieurs configurations (k_retrieve, k_rerank, fuzzy_threshold) : itérer en variant les paramètres passés à `answer_question(...)` directement.
- Pour reproduire un cas de production : récupérer la question dans les logs (`grep "rag.refused" apps/api/logs/`) et la rejouer via Option B.
- Pour traquer une hallucination spécifique : inspecter `result.citation_report.sentences` et chercher quelle phrase a `verdict != SOURCED_VERIFIED`, lire son `reason` pour la cause exacte.

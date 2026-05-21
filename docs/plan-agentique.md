# Plan d'exécution — agentification du pipeline RAG

> Plan d'implémentation, découpé en lots `G0`–`G6`. Complète
> [`strategie-agentique.md`](strategie-agentique.md) (le *pourquoi* : recherche,
> diagnostic, patterns priorisés) par le *comment / quand*. Validé le 2026-05-20.

## Principes (rappel)

1. **Règle d'or invariante** — le juge sémantique en bout de chaîne reste le
   garde-fou absolu ; aucune brique agentique ne l'affaiblit. Corpus clos.
2. **Incréments à flag** — chaque lot = un `CC_API_RAG_*` désactivé par défaut,
   activé après validation. Déployable sur `main`, réversible.
3. **Mesurer avant d'optimiser** — evals (`tests/eval/`) en baseline + gate.
4. **Budget d'abord** — plafonds durs (itérations, tokens, temps). Agentique
   *sélective* : System 1 rapide par défaut, System 2 seulement si nécessaire.

## État d'avancement

| Lot | Objet | État |
|---|---|---|
| **G0** | Refactoring composable du pipeline | 🔨 codé, en validation |
| **G1** | Prompt caching Anthropic | ⏳ à faire |
| **G2** | Cache sémantique Redis | ⏳ à faire |
| **G3** | Routage de complexité | ⏳ à faire |
| **G4** | CRAG léger (évaluation des passages) | ⏳ à faire |
| **G5** | Récupération itérative bornée | ⏳ à faire |
| **G6** | Observabilité agentique + quality gate | ⏳ à faire |

## Détail des lots

### G0 — Rendre le pipeline composable *(fondation)*

`answer_question` était un monolithe linéaire (~330 lignes). Extraction de trois
étapes pures et rappelables, sans changer le comportement :

- `_decompose(question, *, anthropic) -> (search_queries, ms)`
- `_retrieve(search_queries, *, qdrant, embed, session, k_retrieve) -> (chunks, latences)`
- `_rerank_and_select(retrieved, question, *, reranker, k_rerank) -> (chunks, refused_reason, ms)`

`answer_question` les orchestre. Sans étapes rappelables, pas de boucle (G5).
- *Fichier* : `services/rag.py` · *Validation* : `test_pipeline_rag.py` vert (zéro régression).

### G1 — Prompt caching Anthropic

Marquer `SYSTEM_PROMPT` (volumineux) + contexte stable en `cache_control:
ephemeral`, éléments stables **avant** les dynamiques (ne pas casser le cache).
- *Fichier* : `clients/anthropic.py` · *Gain* : −40 à −80 % de coût sur tokens système répétés · *Risque* : faible · *Indépendant de G0.*

### G2 — Cache sémantique Redis

Avant le pipeline : embed la question, chercher une question déjà répondue
(cos ≥ 0,95) ; hit → renvoyer la réponse mémorisée.
- *Fichiers* : `services/rag.py`, `clients/redis.py` · *Flag* : `CC_API_RAG_SEMANTIC_CACHE`
- **Garde-fous** : ne cacher QUE `all_verified=True` (jamais partiel/refusé) ;
  seuil conservateur ; **clé versionnée par hash du corpus** (invalidation à la ré-ingestion).

### G3 — Routage de complexité

Routeur : *simple* (un concept, définition) → pipeline 1-passe ; *complexe*
(comparaison, multi-auteurs, évolution) → décomposition + itératif. Décision
**par question** (remplace le flag binaire `rag_decomposition_enabled`). v1
heuristique (connecteurs, entités, longueur), v2 classifieur léger.
- *Fichiers* : `services/rag.py` (+ `services/routing.py`) · **Garde-fou : doute → complexe ; décision tracée.**

### G4 — CRAG léger (évaluation des passages)

Après rerank, verdict de couverture (*suffisant / ambigu / insuffisant*) ;
insuffisant → déclenche G5 ou refus motivé. v1 sur scores de rerank (le seuil
`no_relevant_chunks` en est déjà un proto), v2 un appel Haiku.
- **Garde-fou : pré-filtre seulement — le juge sémantique aval reste intact.**

### G5 — Récupération itérative bornée *(la boucle, niveau 3)*

`retrieve → CRAG → (si insuffisant ET budget) reformuler → re-retrieve`.
- *Fichier* : `services/rag.py` · *Flag* : `CC_API_RAG_ITERATIVE`
- **Garde-fous : cap 3 itérations DUR · plafonds tokens/temps par requête ·
  arrêt si non-progrès (mêmes chunks) · juge final invariant.**
- *Dépend de G0, G3, G4.*

### G6 — Observabilité agentique + quality gate

Étendre `RagInteraction` (`route`, `n_iterations`, `crag_verdict`, `cache_hit`)
+ migration + métriques Prometheus. Brancher `tests/eval/` comme quality gate
CI : bloquer toute régression de fidélité.
- *Fichiers* : `models/rag_interaction.py` (+ migration), `core/metrics.py`, CI.

## Ordre recommandé

`G0 → G1 → G2 → G3 → G4 → G5 → G6`. Fondation d'abord, puis gains immédiats à
faible risque (caching), puis l'agentique progressive (routage → CRAG →
itératif), enfin la consolidation. G6 est transverse : chaque lot ajoute ses
propres traces.

## Garde-fous transverses (à chaque lot)

`test_pipeline_rag.py` vert · evals ≥ baseline · `/debug-rag` reflète les
nouvelles décisions · plafonds budget respectés · architecture cible
« System 1 + System 2 sélectif » (le budget se dépense là où il change le résultat).

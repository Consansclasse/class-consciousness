# ADR-0003 — Architecture RAG avec validation littérale des citations

- **Statut** : accepté
- **Date** : 2026-04-27

## Contexte

Principe non-négociable du projet : aucune phrase générée sans citation littéralement vérifiée. Le RAG doit refuser plutôt que d'halluciner. Cf. `feedback_no_unsourced_answers.md`.

## Décision

Pipeline déterministe en 7 étapes, écrit en ~400 lignes Python lisibles, **sans framework RAG** :

1. **Pré-traitement** (Claude Haiku 4.5) : réécriture, extraction d'entités, décomposition multi-questions, détection hors-périmètre.
2. **Recherche hybride Qdrant** : Query API avec `prefetch` (sparse BM25 top 50) + (dense top 50) + fusion RRF in-engine → top 30. Filtres payload (auteur, œuvre, langue, période, concept) appliqués in-engine.
3. **Reranking** (Voyage `rerank-2.5`) : top 30 → top 8.
4. **Génération** (Claude Opus 4.7) :
   - Prompt système cacheable : règles de citation strictes, format JSON imposé.
   - Contexte cacheable : taxonomie SKOS, glossaire mainteneur.
   - Contexte non-cacheable : 8 chunks + métadonnées (auteur, ARK, page).
   - Output JSON structuré : `{ confidence, sentences: [{ text, citations: [{chunk_ark, span}] }], bibliography }`.
5. **Validation post-génération** (déterministe, hors LLM) :
   - Chaque phrase doit avoir ≥ 1 citation
   - Pour chaque citation : `chunk_ark` existe ; `text_chunk[span]` apparaît littéralement dans `sentence.text` (Levenshtein ≤ 5 %)
   - Si > 20 % phrases invalides OU confidence < 0.7 → replay (max 2) → sinon refus motivé
6. **Streaming par phrase** (pas par token) : on ne flush qu'après validation.
7. **Logging RGPD-conforme** : hash question, chunks récupérés, prompt_hash, model_version, latency. Rétention 90 j max.

## Conséquences

Bénéfices :
- Validation déterministe, auditable, indépendante du LLM
- Refus motivés acceptables car corpus sourcé est la promesse du projet
- Pas de framework opaque (LangChain/LlamaIndex rejetés en ADR-0001)

Coûts :
- Coût LLM significatif (mitigation : prompt caching agressif, cache Redis questions, quotas durs)
- Latence p95 ~8s acceptée dans les SLOs
- Implémentation maison à maintenir (~400 lignes ; bornable)

## Anti-hallucination — garde-fous

- Mode `strict` par défaut (confidence ≥ 0.7, ≥ 4 chunks pertinents)
- Pas de chain-of-thought visible
- Hash du prompt système + version modèle dans chaque réponse
- Anthropic Citations API utilisée en double validation si disponible [VÉRIFIER]
- Refus poli sur questions interprétatives (« commenter », « juger ») → redirection vers commentaires signés ou recherche
- Test set red-team versionné dans `tests/rag-eval/`, eval CI hebdo

## Alternatives rejetées

- Generation libre + post-fact-check : fuite d'hallucinations en streaming
- LangChain / LlamaIndex : abstractions opaques difficiles à auditer pour la promesse de citation
- RAG « long-context » brut (200k tokens dans Opus sans retrieval) : coût prohibitif et qualité moindre que retrieval ciblé
- Self-RAG / CRITIC-style : intéressants en recherche, immatures pour production avec garantie littérale

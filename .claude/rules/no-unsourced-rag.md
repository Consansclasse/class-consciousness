# Règle d'or — Aucune phrase sans citation littéralement vérifiée

S'applique à : tout endpoint qui produit une réponse RAG (`apps/api/src/cc_api/routers/qa.py`, `services/rag.py`, et tout pipeline d'extraction citationnelle).

## Règle

Aucune phrase d'une réponse RAG ne doit exister **sans** une citation rattachée à un passage du corpus, ET cette citation doit être **littéralement présente** dans le passage source (vérifiée par substring matching ou fuzzy ≥ 95%).

## Pourquoi

C'est le cœur scientifique et éthique du projet : une archive marxiste open-source qui hallucine ses sources serait pire qu'inutile, elle serait politiquement dangereuse. L'utilisateur attend une rigueur de niveau publication académique.

## Comment l'appliquer

1. **Pipeline RAG** : chaque chunk retourné contient `(text, source_id, char_start, char_end)`. Après génération, vérifier que chaque phrase produite cite au moins un `source_id` et que le texte cité existe dans le chunk pointé.
2. **Échec** : si une phrase ne peut pas être sourcée, marquer `[NON SOURCÉ]` et déclencher un re-essai avec contraintes plus serrées, OU refuser la réponse.
3. **Tests** : `apps/api/tests/integration/test_pipeline_rag.py` doit inclure un test `test_every_sentence_has_verified_citation` qui parse la réponse et vérifie chaque phrase.
4. **Skill** : `/debug-rag` dump toutes les étapes et flagge les phrases non-sourcées en rouge.

## Anti-patterns à refuser

- Citations « à peu près », paraphrasées ou résumées.
- Citations sans `source_id` ni offsets.
- Tolérance "ça doit être dans Capital tome X quelque part".
- Hallucinations de titres ou de pages.

Voir aussi : `[[feedback_no_unsourced_answers]]` dans l'auto-memory utilisateur.

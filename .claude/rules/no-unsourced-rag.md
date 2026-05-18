# Règle d'or — Aucune phrase sans ancrage vérifié dans le corpus

S'applique à : tout endpoint qui produit une réponse RAG (`apps/api/src/cc_api/routers/qa.py`, `services/rag.py`, `services/citation.py`, et tout pipeline d'extraction citationnelle).

## Règle

Une réponse RAG est une **dissertation d'explication de texte** : l'assistant
explique et analyse le corpus *dans ses propres mots*. Mais :

> Aucune phrase ne doit affirmer quoi que ce soit qui ne soit **soutenu par un
> passage cité du corpus**, et toute citation directe (entre « ») doit être
> reproduite **mot pour mot**. L'assistant n'utilise **aucune connaissance
> extérieure** : ni date, ni nom, ni événement, ni thèse hors des passages
> fournis.

C'est un assouplissement *encadré* de l'ancienne règle « chaque phrase est un
substring littéral du corpus » : on autorise la reformulation et l'analyse, mais
on la **vérifie** par un second mécanisme. La paraphrase est permise ; l'ajout
non sourcé reste interdit.

## Pourquoi

C'est le cœur scientifique et éthique du projet : une archive marxiste
open-source qui hallucine ses sources serait pire qu'inutile, elle serait
politiquement dangereuse. L'utilisateur attend une rigueur de niveau publication
académique. La pure recherche citationnelle (recollage de fragments) produisait
des réponses pauvres ; l'explication de texte les rend riches **à condition** de
garder un garde-fou anti-hallucination.

## Comment l'appliquer — deux gardes-fous

Chaque chunk du contexte porte `(text, source_id, char_start, char_end)`. Après
génération, `services/citation.py` vérifie **chaque phrase** :

1. **Contrôle littéral des citations directes.** Tout fragment entre guillemets
   « … » doit apparaître mot pour mot dans un chunk cité (substring exact ou
   `rapidfuzz.partial_ratio ≥ seuil adaptatif`). Échec → verdict
   `QUOTE_UNVERIFIED`.
2. **Juge sémantique d'entailment.** Chaque phrase d'analyse est soumise à un
   2ᵉ passage LLM (`AnthropicClient.judge`) qui statue, passage en main :
   - `ENTAILED` → la phrase est entièrement déductible des passages cités.
   - `NOT_ENTAILED` → elle affirme un élément absent → verdict `NOT_SUPPORTED`.
   - `CONTRADICTED` → elle détourne ou inverse le sens → verdict `CONTRADICTED`.

Une phrase n'est `SUPPORTED` que si elle passe **les deux** contrôles. Tout
autre verdict (`QUOTE_UNVERIFIED`, `NOT_SUPPORTED`, `CONTRADICTED`, `UNSOURCED`)
casse `all_verified`.

3. **Échec.** Phrase non `SUPPORTED` → écartée (mode partiel → `incomplete=true`)
   ou réponse refusée (422). Le silence est préférable à la distorsion.
4. **Tests** : `apps/api/tests/integration/test_pipeline_rag.py` vérifie que
   toute phrase exposée est `SUPPORTED` ou refus explicite.
5. **Skill** : `/debug-rag` dump toutes les étapes et flagge en rouge les
   phrases non `SUPPORTED`.

## Anti-patterns à refuser

- Toute affirmation reposant sur une connaissance hors corpus.
- Citation directe « … » paraphrasée, résumée ou retouchée silencieusement.
- Phrase d'analyse sans `source_id` dans son champ `citations`.
- Relâcher les seuils fuzzy ou désactiver le juge sémantique en prod pour
  augmenter le taux de réponse.
- Tolérance « ça doit être dans Capital tome X quelque part ».

Voir aussi : `.claude/rules/citation-honest-vs-literal.md` et
`[[feedback_no_unsourced_answers]]` dans l'auto-memory utilisateur.

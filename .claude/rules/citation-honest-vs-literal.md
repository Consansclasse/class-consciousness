# Règle d'or — Citation littérale ≠ citation honnête

S'applique à : tout pipeline RAG du projet (`apps/api/src/cc_api/services/rag.py`,
`services/citation.py`) et à toute extension future (multi-tour, exports CSL, etc.).

## Pourquoi cette règle

La règle `no-unsourced-rag.md` impose que chaque phrase RAG soit soutenue par un
passage cité, et que toute citation directe soit littérale. C'est solide contre
l'invention pure.

**Mais une citation littérale peut être malhonnête.** Le fragment extrait peut
inverser ou détourner le sens du paragraphe environnant.

### Exemple canonique

Chunk source :
> « Les opportunistes prétendent que la révolution est terminée, mais ils se
> trompent gravement : la lutte se poursuit. »

Le LLM extrait littéralement :
> « La révolution est terminée. » (citée comme `bilan-1/article:5`)

Le contrôle littéral **passe** (substring exact). Mais la phrase **inverse le
sens** de l'auteur, qui disait précisément le contraire. C'est une
**hallucination sourcée** : techniquement vérifiée, sémantiquement fausse. Pour
une archive marxiste à standards académiques, le pipeline pourrait faire dire à
Lénine l'inverse de Lénine en citant littéralement.

## Mécanisme implémenté — le juge sémantique

Depuis le passage au mode « dissertation d'explication de texte », la détection
de distorsion n'est plus lexicale mais **sémantique**. Chaque phrase est soumise
au 2ᵉ passage LLM `AnthropicClient.judge` (`services/citation.py`,
`verify_response`), qui statue passage en main :

- `ENTAILED` → phrase soutenue → verdict `SUPPORTED`.
- `NOT_ENTAILED` → élément non soutenu → verdict `NOT_SUPPORTED`.
- `CONTRADICTED` → la phrase dit le contraire du passage, OU présente comme
  thèse de l'auteur un propos qu'il réfute / attribue à un adversaire / pose en
  question rhétorique → verdict `CONTRADICTED`.

Le verdict `CONTRADICTED` casse `all_verified` : la phrase est écartée (mode
partiel → `incomplete=true`) ou la réponse refusée. C'est le successeur de
l'ancien détecteur lexical `_REFUTATION_PATTERNS` (connecteurs `prétend*`,
`certes`, `en réalité`…), retiré car le juge sémantique couvre le même risque
sans faux positifs lexicaux.

Le prompt du juge (`_JUDGE_SYSTEM`) impose explicitement : en cas de doute entre
`ENTAILED` et `NOT_ENTAILED`, choisir `NOT_ENTAILED` — le silence est préférable
à la distorsion.

## Anti-patterns à refuser quand on construit ou évalue le pipeline

- Citer un fragment court extrait d'une phrase qui le réfute.
- Citer des mots prêtés par l'auteur à un adversaire idéologique (fréquent dans
  Bilan qui cite l'IC et Trotsky pour les critiquer).
- Présenter une question rhétorique comme une affirmation.
- Affaiblir le prompt du juge ou désactiver `rag_verifier_enabled` en prod.

## Pour l'IA agentique : conduite obligatoire

1. **Ne jamais désactiver** le juge sémantique en production (`rag_verifier_enabled`).
2. **Toujours préserver** le verdict `REFUSED_BY_LLM` comme légitime.
3. **Lors d'un audit**, lire le chunk source COMPLET (pas juste l'extraction)
   pour vérifier la cohérence sémantique de la phrase produite.
4. **En cas de doute**, refuser la réponse. Le silence est préférable à la
   distorsion historique.

Voir aussi :
- `.claude/rules/no-unsourced-rag.md`
- `[[feedback_no_unsourced_answers]]` dans l'auto-memory utilisateur
- `apps/api/src/cc_api/services/rag.py` (`SYSTEM_PROMPT`)
- `apps/api/src/cc_api/services/citation.py` (`verify_response`, `_JUDGE_SYSTEM`)

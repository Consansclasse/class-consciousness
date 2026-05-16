# Règle d'or — Citation littérale ≠ citation honnête

S'applique à : tout pipeline RAG du projet (`apps/api/src/cc_api/services/rag.py`,
`services/citation.py`) et à toute extension future (multi-tour, exports CSL, etc.).

## Pourquoi cette règle

La règle d'or actuelle (`no-unsourced-rag.md`) impose que chaque phrase RAG soit
littéralement adossée à un chunk source (substring exact OU `rapidfuzz.partial_ratio`
≥ seuil adaptatif). C'est solide contre l'hallucination pure.

**Mais une citation littérale peut être malhonnête.** Le passage extrait peut
inverser ou détourner le sens global du paragraphe environnant.

### Exemple canonique

Chunk source :
> « Les opportunistes prétendent que la révolution est terminée, mais ils se
> trompent gravement : la lutte se poursuit. »

Le LLM extrait littéralement :
> « La révolution est terminée. [CITE:bilan-1/article:5] »

Vérification fuzzy ≥ 95% : **passe** (substring exact). Mais la phrase **inverse
le sens** de l'auteur, qui disait précisément le contraire.

C'est une **hallucination sourcée** : techniquement vérifiée, sémantiquement
fausse. Pour une archive marxiste à standards académiques, c'est un risque
éditorial sérieux : le pipeline pourrait faire dire à Lénine l'inverse de Lénine
en citant littéralement.

## Statut actuel d'implémentation

| Garde-fou | Statut | Fichier |
|---|---|---|
| Phrase d'attribution obligatoire au sujet (« La fraction défend X » ≠ « X est défendu ») | ✅ Couverte par `SYSTEM_PROMPT` | `services/rag.py` |
| Seuil fuzzy adaptatif sur phrases courtes (100 si ≤ 5 mots) | ✅ Implémenté | `services/citation.py:_adaptive_threshold` |
| Refus explicite via `[CITE:none]` (verdict `REFUSED_BY_LLM`) | ✅ Implémenté | `services/citation.py:verify_sentence` |
| Contexte étendu (anneau ±200 caractères autour du match) | ✅ Implémenté | `services/citation.py:_detect_uncarried_refutation` |
| Détection lexicale réfutation/attribution adverse → verdict `SOURCED_VERIFIED_FLAGGED` | ✅ Implémenté | `services/citation.py:_REFUTATION_PATTERNS` |
| Test « citation tronquée hostile » | ✅ Implémenté | `tests/integration/test_citation_verification.py` |

## Anti-patterns à refuser quand on construit ou évalue le pipeline

- Citer un fragment court (< 8 mots) extrait d'une phrase qui le réfute.
- Citer des mots prêtés par l'auteur à un adversaire idéologique (fréquent dans
  Bilan qui cite l'IC et Trotsky pour les critiquer).
- Présenter une question rhétorique comme une affirmation.
- Détacher une citation d'un connecteur de réfutation (« mais », « or »,
  « contrairement à », « il est faux que », « prétendent que »).

## Mécanisme implémenté — détection de réfutation

Après qu'une phrase a passé la vérification littérale (substring ou fuzzy),
`verify_sentence` scanne un anneau de ±200 caractères autour du fragment dans
le chunk source (`_detect_uncarried_refutation`). Si un connecteur de
réfutation ou d'attribution adverse y figure **sans** être reporté dans la
phrase générée, le verdict devient `SOURCED_VERIFIED_FLAGGED` au lieu de
`SOURCED_VERIFIED`. Ce verdict casse `all_verified` : le pipeline RAG écarte
la phrase (mode partiel → `incomplete=true`), conformément au principe
« le silence est préférable à la distorsion ».

### Connecteurs retenus — haute précision uniquement

- **Attribution adverse** : `prétend*`, `soi-disant`, `se réclam*`, `exult*`
- **Réfutation explicite** : `certes`, `en réalité`, `contrairement à`,
  `à l'opposé`, `il est faux`, `se tromp*`, `à tort`

Les contrastes génériques (`mais`, `cependant`, `toutefois`, `pourtant`) ont
été **délibérément écartés** : ubiquitaires en prose théorique, ils marquent
le plus souvent une articulation interne du raisonnement et non une réfutation
du fragment cité — leur inclusion produisait des faux positifs massifs
(mesurés sur le corpus Bilan : ~40 % des phrases honnêtes faussement flaggées).
Le biais assumé est la **précision** : mieux vaut manquer une distorsion subtile
que rendre `incomplete` la majorité des réponses honnêtes.

Le réglage (`_REFUTATION_PATTERNS`, `_REFUTATION_RING`) ne doit jamais être
relâché sans nouvelle mesure de faux positifs sur le corpus.

### 3. Test eval dédié

Fixture TEI minimaliste avec une structure « X affirme A, mais A est faux ».
Question piégeuse : « Que dit le texte sur A ? ». Vérifier que le pipeline :
- soit refuse,
- soit attribue correctement (« Le texte critique l'idée que A »),
- soit (au pire) flag la réponse comme incomplete.

## Pour l'IA agentique : conduite obligatoire

Quand tu travailles sur le pipeline RAG ou la vérification de citation :

1. **Ne jamais relâcher** les seuils fuzzy ou adaptatifs sous prétexte d'augmenter
   le taux de réponse.
2. **Toujours préserver** le verdict `REFUSED_BY_LLM` comme légitime.
3. **Lors d'un audit**, lire le chunk source COMPLET (pas juste l'extraction) pour
   vérifier la cohérence sémantique de la citation produite.
4. **En cas de doute**, refuser la réponse. Le silence est préférable à la
   distorsion historique.

Voir aussi :
- `.claude/rules/no-unsourced-rag.md`
- `[[feedback_no_unsourced_answers]]` dans l'auto-memory utilisateur
- `apps/api/src/cc_api/services/rag.py` (`SYSTEM_PROMPT`)
- `apps/api/src/cc_api/services/citation.py` (`verify_sentence`, `_adaptive_threshold`)

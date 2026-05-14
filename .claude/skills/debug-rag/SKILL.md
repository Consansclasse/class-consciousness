---
name: debug-rag
description: Dumper l'intégralité du pipeline RAG pour une question donnée — embedding query, top-k Qdrant, reranking, contexte assemblé, prompt final, réponse LLM, et vérification que CHAQUE phrase de la réponse est citée et que la citation est littéralement présente dans le passage source. Cœur de la règle d'or RAG.
---

# /debug-rag — Inspection du pipeline RAG

Tu prends une question utilisateur (en français) et tu dumps chaque étape du pipeline RAG. Tu termines par la vérification de citation, qui est **non-négociable** : aucune phrase produite par le pipeline ne doit exister sans citation littéralement vérifiable dans le corpus source.

Voir `.claude/rules/no-unsourced-rag.md` et `[[feedback_no_unsourced_answers]]`.

## Entrée

Une question en français. Si non précisée, demander à l'utilisateur.

## Étapes (avec dump)

1. **Embedding de la query** : appeler le service d'embedding (Voyage `voyage-4`, 1024 dims).
   Dump : `query`, `dimensions`, `first 10 values`.

2. **Recherche Qdrant top-k** : k=20 par défaut.
   Dump : pour chaque hit, `source_id`, `score`, `text[:200]`, `char_offsets`.

3. **Reranking Voyage `rerank-2.5`** : k=20 → top 5.
   Dump : nouveaux scores et changements d'ordre.

4. **Contexte assemblé** : concaténation des 5 chunks avec leurs métadonnées (titre œuvre, auteur, page, ARK).
   Dump : longueur totale tokens, source_ids retenus.

5. **Prompt final envoyé à Claude Opus** : système + contexte + question.
   Dump : prompt complet.

6. **Réponse brute du LLM** : avant tout post-processing.
   Dump : texte intégral.

7. **Vérification citation par phrase** — étape critique :
   - Découper la réponse en phrases (regex sur `.!?` + abréviations FR).
   - Pour chaque phrase : extraire les `source_id` cités, vérifier que la citation est **littéralement** (ou fuzzy ≥ 95%) présente dans le chunk pointé.
   - Marquer chaque phrase : `✅ sourcée et vérifiée` / `⚠️ sourcée mais non vérifiée` / `❌ non sourcée`.

8. **Verdict final** :
   - Si **toutes** les phrases sont ✅ : afficher la réponse.
   - Sinon : afficher le détail des phrases problématiques, **refuser la réponse**, et proposer (a) re-essayer avec contraintes plus serrées, (b) déclarer ne pas savoir, (c) demander à l'utilisateur si la marge de fuzzy doit être ajustée.

## Format de sortie

```
═══ /debug-rag : « {question} » ═══

[1] Embedding         : voyage-4, 1024d, début=[0.012, -0.045, …]
[2] Qdrant top-20     :
    1. Capital_T1_p234  score=0.871  "..."
    2. Manifeste_p4     score=0.852  "..."
    ...
[3] Reranking         : top 1 = (2) Manifeste_p4 (rerank=0.95)
[4] Contexte assemblé : 5 chunks, 2410 tokens
[5] Prompt            : <texte tronqué dans le dump si > 1000 lignes>
[6] Réponse brute     :
    "..."
[7] Vérification citation :
    Phrase 1: "..." ✅  (cite Manifeste_p4, vérifié)
    Phrase 2: "..." ❌  (aucune citation)
    Phrase 3: "..." ⚠️  (cite Capital_T1_p234 mais texte non trouvé)

VERDICT : ❌ 2 phrases non conformes → réponse refusée.
```

## Anti-patterns à refuser

- Phrase "probablement de Marx" sans source_id concrète.
- Citation paraphrasée ("Marx dit en substance que…").
- Tolérance "ça doit être quelque part dans Capital".
- Hallucination de titres ou de pages.

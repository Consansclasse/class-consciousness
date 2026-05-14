---
name: test-fix
description: Boucle de réparation des tests cassés — analyser le rapport d'échec, identifier la cause racine (UI brisée, sélecteur drift, régression API, fixture cassée, drift de schéma DB), corriger, relancer le test ciblé. Réutilise le pattern healer de Playwright Agents.
---

# /test-fix — Réparation ciblée

Tu identifies la cause racine d'un échec de test et tu corriges. **Tu ne modifies jamais le test pour le faire passer** : tu corriges le code qui le casse, ou tu mets à jour le test si le comportement attendu a légitimement changé.

## Entrée attendue

Soit le rapport de `/test-full`, soit un nom de test précis. Si le contexte ne précise pas, lancer d'abord `/test-full` pour collecter les échecs.

## Étapes

1. **Catégoriser l'échec** :
   - **UI brisée** : élément DOM absent / différent → vérifier `apps/web/src/`
   - **Sélecteur drift** : test cherche un locator qui n'existe plus → utiliser l'approche healer (chercher un équivalent sémantique) puis corriger le test
   - **Régression API** : statut HTTP / payload différent → vérifier `apps/api/src/cc_api/routers/` et `services/`
   - **Fixture cassée** : seed retourne 500 → vérifier `/__debug/seed` puis pipeline ingestion
   - **Drift schéma DB** : migration manquante → vérifier `apps/api/alembic/versions/`
   - **Hallucination RAG** : phrase sans citation vérifiée → bug **critique**, escalader

2. **Reproduire en isolation** :
   ```bash
   # backend
   uv run pytest apps/api/tests/path/to/test.py::test_name -x -v
   # E2E
   cd apps/web && pnpm exec playwright test specs/file.spec.ts --debug
   ```

3. **Corriger** :
   - Modifier le code de l'app, pas le test.
   - Si le test doit changer (comportement attendu a évolué), expliquer le pourquoi en commit message proposé.

4. **Vérifier** : relancer le test ciblé. S'il passe, relancer la suite complète (`/test-full`).

## Escalation healer (pattern Playwright)

Si après **2 tentatives** un test E2E continue d'échouer pour cause de drift de sélecteur :
- Stop.
- Lister à l'utilisateur les deux locators tentés et leurs échecs.
- Proposer 1-2 hypothèses sur la cause racine.
- Demander une décision avant de toucher au test ou au code applicatif.

> Source : Playwright Healer agent dépasse 75% sur les drifts de sélecteur. Au-delà de cette barre, l'analyse humaine est plus fiable.

## Anti-patterns à refuser

- `pytest.mark.skip` pour "passer" l'échec.
- Commentaire `// @ts-ignore` ou `# type: ignore` pour cacher une erreur.
- Modifier l'assertion pour qu'elle corresponde au comportement bogué.
- "C'est probablement flaky" sans investigation.

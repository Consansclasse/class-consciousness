---
name: test-full
description: Orchestrer la suite complète de tests (pytest + vitest + Playwright E2E) et consolider un rapport unique en français. À utiliser après une modification non-triviale ou avant de signaler une fonctionnalité comme terminée.
---

# /test-full — Suite complète

Tu orchestres la suite de tests complète du repo `class-consciousness` et produis un rapport unique consolidé en français.

## Étapes (séquentielles)

1. **Vérifier l'environnement** :
   - `make agent-status` — services up, alembic OK ?
   - Si un service est down, lancer `make dev` ou `docker compose -f infra/docker-compose.yml up -d` et attendre healthcheck.

2. **Tests unitaires + intégration backend** :
   ```bash
   uv run pytest -q --cov=apps/api/src --cov-report=term
   ```

3. **Tests vitest frontend** :
   ```bash
   cd apps/web && pnpm test
   ```

4. **Tests E2E Playwright** :
   ```bash
   cd apps/web && pnpm exec playwright test --reporter=list
   ```
   Si échec : récupérer le rapport HTML dans `apps/web/playwright-report/` et les traces dans `apps/web/test-results/`.

## Format de rapport (français)

```
═══ /test-full — rapport ═══

[1/3] Backend pytest        : X passés / Y échoués / Z skipped — couverture N%
[2/3] Frontend vitest       : X passés / Y échoués
[3/3] E2E Playwright        : X passés / Y échoués / Z flaky

ÉCHECS DÉTAILLÉS :
- tests/integration/test_debug_routes.py::test_X — AssertionError: ...
  → Cause probable : ...
  → Action proposée : /test-fix ou correction manuelle ?

VERDICT : ✅ tout vert / ⚠️ N tests rouges / ❌ stack non démarrable
```

## Garde-fous

- **Ne JAMAIS modifier les tests pour qu'ils passent** sans comprendre la cause.
- **Ne JAMAIS skipper un test** sauf si l'utilisateur le demande explicitement.
- Si un test fait apparaître une hallucination RAG (réponse sans citation vérifiée), c'est un échec **critique** — escalader immédiatement.
- Si Playwright MCP retourne des erreurs `mcp__playwright__*`, c'est probablement le bug Issue #1359 : vérifier que `.mcp.json` pointe bien sur `@playwright/mcp@0.0.41`.

## Suite logique

En cas d'échec → proposer `/test-fix` pour la boucle de réparation.
En cas de succès → confirmer brièvement et passer au prochain chantier.

# CLAUDE.md — apps/web

Frontend Astro 5 + îlots React. Port 3000. API consommée via `PUBLIC_API_BASE_URL` (par défaut `http://localhost:8000`).

## Arborescence

```
src/
├── pages/          # routes Astro (file-based routing)
├── components/     # composants Astro + îlots React
├── layouts/        # gabarits
└── lib/            # client API typé, utils
tests/
├── e2e/
│   ├── specs/      # tests Playwright (auto-générés ou manuels)
│   ├── plans/      # plans markdown (Playwright Planner agent)
│   └── fixtures/   # fixtures partagées (seed via /__debug/seed)
```

## Lancer / tester

```bash
pnpm dev                    # Astro dev server, port 3000
pnpm test                   # vitest unit tests
npx playwright test         # tests E2E
npx playwright test --ui    # mode interactif
```

## Conventions Playwright (importantes — caveats MCP)

**Sélecteurs** : toujours sémantiques (`getByRole`, `getByLabel`, `getByText`). Pas de CSS class ni d'IDs générés.

**Pas de `browser_snapshot` complet via MCP** : la version 2026 retourne tout le DOM (50-540 KB) et déborde le contexte après 2-3 visites de page. Préférer :
- `page.locator(...)` ciblé en code Playwright.
- Via MCP : `browser_click(role, name)` direct ou `browser_evaluate(js)` sur sélection précise.

**Accessibilité = pré-requis** : tous les composants doivent avoir `aria-label`, rôles ARIA corrects, structure heading propre. Sinon le Planner agent produit des plans pourris.

**Traces & screenshots** : `traces: 'on-first-retry'`, `screenshots: 'only-on-failure'`. Les artefacts vont dans `test-results/`.

## Conventions Astro

- Composants Astro `.astro` par défaut. Îlots React uniquement quand interactif (`<MyComp client:idle />`).
- Pas de routing client : reload server-side (sauf îlots).
- Client API typé dans `src/lib/api.ts` (généré depuis OpenAPI de l'API → TODO chantier ultérieur).

## Tests E2E

- `specs/00-smoke.spec.ts` est le test ancre — ne jamais le supprimer.
- Avant tout test qui dépend de données : appeler la fixture `seededCorpus` qui POST `/__debug/seed`.
- En CI, les tests tournent contre le docker-compose dev complet (job `e2e` dans `.github/workflows/ci.yml`).

## Playwright Agents (planner/generator/healer)

Installés via `npx playwright init-agents --loop=claude` (Playwright 1.56+). Génère `.claude/agents/planner.md`, `generator.md`, `healer.md`. Orchestrés par les skills `/test-full` et `/test-fix`.

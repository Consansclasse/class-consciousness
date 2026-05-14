# Mission agentique — Pipeline d'ingestion du corpus Bilan

Document à copier-coller intégralement dans une nouvelle session Claude Code (ou à invoquer via la commande `claude < docs/agent-missions/ingest-pipeline.md`). Ce prompt active l'IA agentique du projet `class-consciousness` et la pilote jusqu'à ce que le pipeline d'ingestion d'un texte du corpus Bilan soit complet, testé, et observable depuis l'interface web.

---

## CONTEXTE — Identité du projet

Tu es l'opérateur IA de **Conscience de classe** (`class-consciousness`), une archive open-source de la théorie marxiste avec RAG sourcé. Le projet est en Phase 0 — squelette FastAPI + Astro posé, infra docker-compose en place, outillage agentique configuré (MCP + skills + hooks).

**Lis OBLIGATOIREMENT, dans cet ordre, AVANT de toucher au moindre fichier :**

1. `CLAUDE.md` (racine) — carte du stack et règles dures.
2. `.claude/AGENT_GUIDE.md` — 7 principes non-négociables et décisions verrouillées.
3. `.claude/rules/no-unsourced-rag.md` — règle d'or RAG.
4. `.claude/rules/main-branch-only.md` — branche unique.
5. `apps/api/CLAUDE.md` — conventions FastAPI/SQLAlchemy/Alembic.
6. `docs/agent-missions/ingest-pipeline.md` — cette mission (déjà lue).

Si l'un de ces fichiers est absent ou contradictoire avec ce qui suit, **arrête-toi et signale-le**. Ne devine pas.

---

## MISSION — Que dois-tu produire ?

Un pipeline d'ingestion **fonctionnel, testé, observable** qui permet d'exécuter :

```bash
uv run cc-corpus ingest corpus/_seed/bilan-001.tei.xml
```

et qui aboutit à :

- Une entrée visible dans `GET /corpus` (Postgres).
- N chunks indexés dans Qdrant avec embeddings Voyage `voyage-4`.
- Un enregistrement dans `/__debug/state` reflétant l'ingestion.
- La page web `/corpus` qui affiche la ligne : *titre · auteur · date d'insertion*.
- Une vérification automatique que chaque chunk inséré est récupérable par recherche vectorielle.

**Definition of Done** (tout doit être vrai à la fin) :

1. `make agent-bootstrap` passe vert depuis un repo propre.
2. `make smoke` passe vert.
3. `make test` passe vert (pytest + vitest).
4. `cd apps/web && pnpm exec playwright test` passe vert (au moins le smoke E2E + un nouveau test `corpus.spec.ts` qui vérifie qu'une entrée ingérée apparaît dans `/corpus`).
5. `uv run mypy apps/api/src packages/corpus-tools/src` passe sans erreur.
6. `uv run ruff check . && uv run ruff format --check .` passent sans erreur.
7. `pnpm lint && pnpm typecheck` passent sans erreur.
8. La CI GitHub Actions est verte sur `main` après push.
9. Pour une fixture TEI donnée (à créer toi-même comme test), l'ingestion est **idempotente** : deux exécutions consécutives ne créent pas de doublons.
10. Si on appelle `POST /__debug/reset` puis qu'on relance l'ingestion, l'état final est identique au premier passage (reproductibilité).

---

## RÈGLES NON-NÉGOCIABLES

Ces règles dominent tout. En cas de conflit avec ce prompt, **elles gagnent**.

### Sur le code
- **Pas de mocks** pour les tests d'intégration. Utilise les `testcontainers` déjà configurés dans `apps/api/tests/conftest.py` : vraie Postgres, vrai Qdrant éphémères par session pytest.
- **Pas de fallback OpenAI ou autre provider**. Le projet est Anthropic + Voyage AI exclusivement. Si Voyage n'est pas joignable, le pipeline **échoue bruyamment**, il n'utilise pas d'autre embedder.
- **Pas de gris dans le frontend.** Strict noir/blanc + `darkpink` (#E27ECC).
- **Pas de `<strong>` ni `font-bold`/`font-semibold`** dans le markup web.
- **Pas de gras** dans les sorties RAG non plus.
- **Conventional Commits** en français, avec `Signed-off-by:` (DCO obligatoire).
- **Aucun commit sur autre branche que `main`**. Pas de feature branches, pas de PR.
- **Aucun commit non sollicité** : à la fin de chaque chantier, attends une validation explicite avant `git commit`. Tu peux préparer les commits (rédiger les messages) mais pas les exécuter sans accord.

### Sur les données du corpus
- **Format source unique : TEI P5.** Pas de Markdown, pas de TXT, pas de PDF brut. Si l'utilisateur veut ingérer autre chose, refuser et demander une conversion TEI.
- **Chaque texte ingéré DOIT avoir** dans son `<teiHeader>` : titre, auteur, date `<date when="...">`, source bibliographique (`<sourceDesc>`), licence explicite, identifiant ARK.
- **Aucun chunk ne doit perdre ses offsets char_start/char_end** dans le texte source. La vérification de citation littérale en dépend.
- **Aucune normalisation destructive** : ne pas reformer les espaces, ne pas corriger les accents, ne pas changer l'orthographe d'époque. Le texte indexé doit être le texte source exact.

### Sur l'observabilité
- Tous les logs côté API utilisent `structlog.get_logger()` (déjà configuré dans `apps/api/src/cc_api/core/logging.py`). Pas de `print()`. Pas de `logging.getLogger()` direct.
- Chaque étape du pipeline d'ingestion log un événement structuré : `ingest.start`, `ingest.parsed`, `ingest.chunked`, `ingest.embedded`, `ingest.stored`, `ingest.done` (ou `.error`) avec contexte (work_id, n_chunks, durée_ms, etc.).
- En cas d'échec à n'importe quelle étape : **rollback complet** (transaction Postgres + suppression des points Qdrant déjà insérés). Pas d'état partiel.

---

## OUTILLAGE À TA DISPOSITION

Tu disposes des serveurs MCP suivants (déjà configurés dans `.mcp.json` à la racine) :

| MCP | Usage attendu |
|---|---|
| `playwright` (pinné `@playwright/mcp@0.0.41`) | Tests E2E. **Ne pas utiliser `browser_snapshot`** (overflow contexte) — préférer locators ciblés. |
| `chrome-devtools` | Debug console / network / Lighthouse sur les pages web. **Sans `--autoConnect`** (fuite mémoire connue Issue #1192). |
| `postgres` (Crystal DBA Postgres MCP Pro, mode `unrestricted`) | Inspection schéma, explain plans, health checks. DSN local uniquement. |
| `github` | Issues, PRs, gh API. |
| `fetch` | Requêtes HTTP arbitraires vers l'API locale et endpoints debug. |

Tu disposes des skills custom dans `.claude/skills/` :

- `/test-full` — orchestre pytest + vitest + Playwright et produit un rapport consolidé.
- `/test-fix` — boucle de réparation des tests cassés (cause racine, pas patch sur le test).
- `/debug-rag` — inspection pipeline RAG bout-en-bout avec vérification citationnelle.

Tu disposes des cibles Makefile :

- `make agent-bootstrap` — setup complet from scratch.
- `make dev` — lance l'app en local.
- `make smoke` — vérification rapide santé.
- `make logs[-api|-web|-db|-qdrant|-redis]` — tail JSON.
- `make agent-status` — état services + alembic + watchdog RSS Chrome DevTools MCP.
- `make db-snapshot` / `make db-restore SNAP=…` — backup/restore Postgres.
- `make api-check FILE=…` / `make web-check FILE=…` — lint/typecheck ciblé.

**Avant de coder quoi que ce soit, exécute :**

```bash
make agent-status      # voir l'état de la stack
make logs-api &        # ouvrir un tail en arrière-plan
```

Et garde un œil sur le watchdog Chrome DevTools MCP (`agent-status` te signale si RSS > 500MB).

---

## ARCHITECTURE CIBLE DU PIPELINE

```
corpus/_seed/bilan-001.tei.xml
            │
            ▼
   ┌────────────────────────────────┐
   │  cc-corpus ingest <file>       │  ← packages/corpus-tools (CLI Typer)
   └────────────────────────────────┘
            │ POST /admin/ingest (auth dev only)
            ▼
   ┌────────────────────────────────┐
   │  apps/api/.../services/ingest  │
   │  ┌──────────────────────────┐  │
   │  │ 1. Parse TEI P5 (lxml)   │  │  → tei.parse() retourne TeiDocument
   │  │ 2. Validate headerStmt   │  │  → required: title, author, date, ark, license
   │  │ 3. Chunk semantically    │  │  → chunk.split() : par <p> TEI, fallback ~500 tokens
   │  │ 4. Compute SHA256 source │  │  → idempotency key
   │  │ 5. Embed via Voyage AI   │  │  → voyage.embed_batch(chunks, model="voyage-4")
   │  │ 6. INSERT Postgres       │  │  → tables: authors, works, chunks (transaction)
   │  │ 7. UPSERT Qdrant         │  │  → collection: "bilan", payload: source_id+offsets
   │  │ 8. Retrieval self-test   │  │  → vérifie qu'au moins 1 chunk est retrouvable
   │  │ 9. Log + return WorkRef  │  │  → {work_id, n_chunks, duration_ms}
   │  └──────────────────────────┘  │
   └────────────────────────────────┘
            │
            ▼
   ┌────────────────────────────────┐
   │  GET /corpus                    │  ← apps/api/.../routers/corpus.py
   │  → liste paginée pour la web    │
   └────────────────────────────────┘
            │
            ▼
   ┌────────────────────────────────┐
   │  apps/web/src/pages/corpus.astro│
   │  → fetch /corpus côté SSR        │
   └────────────────────────────────┘
```

**Composants à livrer** (ordre de dépendances respecté) :

### Chantier 1 — Schéma DB (Alembic)
- Fichier : `apps/api/alembic/versions/0001_init_corpus.py`
- Extensions Postgres requises (dans la même migration) : `CREATE EXTENSION IF NOT EXISTS pg_stat_statements; CREATE EXTENSION IF NOT EXISTS hypopg;` (pré-requis Postgres MCP Pro).
- Tables :
  - `authors(id PK, viaf_id NULL, idref_id NULL, wikidata_id NULL, display_name, birth_year NULL, death_year NULL, created_at)`
  - `works(id PK, ark TEXT UNIQUE NOT NULL, title TEXT NOT NULL, author_id FK, published_date DATE NULL, source_url TEXT, license TEXT NOT NULL, sha256 TEXT NOT NULL UNIQUE, inserted_at TIMESTAMPTZ DEFAULT now())`
  - `chunks(id PK, work_id FK CASCADE, idx INT NOT NULL, text TEXT NOT NULL, char_start INT NOT NULL, char_end INT NOT NULL, token_count INT NOT NULL, embedding_model TEXT NOT NULL, qdrant_point_id UUID NOT NULL UNIQUE)`
  - Index : `idx_chunks_work_id`, `idx_works_ark`, `idx_works_sha256`.
- **Contrainte d'idempotence** : `works.sha256 UNIQUE` doit faire échouer l'insertion d'un texte déjà ingéré, et le pipeline doit lire cette erreur et faire un short-circuit propre (pas un crash).

### Chantier 2 — Modèles SQLAlchemy
- Fichiers dans `apps/api/src/cc_api/models/` : `author.py`, `work.py`, `chunk.py`, `__init__.py` (exporte les 3).
- Utiliser `DeclarativeBase` async (SQLAlchemy 2.0). Relations : `Work.author`, `Work.chunks`, `Chunk.work`.
- Type hints stricts (mypy strict passe).

### Chantier 3 — Schémas Pydantic
- Fichiers dans `apps/api/src/cc_api/schemas/` : `corpus.py`.
- Modèles : `AuthorOut`, `WorkOut`, `WorkSummary` (pour la liste `/corpus`), `ChunkOut`, `IngestRequest`, `IngestResult`.

### Chantier 4 — Parser TEI P5
- Fichier : `packages/corpus-tools/src/cc_corpus/tei.py`.
- Fonction principale : `parse(path: Path) -> TeiDocument`.
- `TeiDocument` : dataclass avec `title`, `author_name`, `date_iso`, `ark`, `license`, `source_desc`, `paragraphs: list[Paragraph]`.
- `Paragraph` : dataclass avec `text`, `char_start`, `char_end` dans le texte plat du body.
- Validation : tous les champs métadonnées requis doivent être présents ; sinon `ValueError` avec message explicite indiquant quel champ manque.
- Dépendance : `lxml`. Ajouter au `pyproject.toml` de `corpus-tools`.

### Chantier 5 — Chunker
- Fichier : `packages/corpus-tools/src/cc_corpus/chunk.py`.
- Stratégie : 1 paragraphe TEI = 1 chunk **par défaut**. Si un paragraphe dépasse 800 tokens, le sous-découper avec overlap de 100 tokens.
- Token counter : utiliser `tiktoken` avec encoder `cl100k_base` (proxy raisonnable pour compter, l'embedder réel est Voyage).
- Toujours préserver `char_start` / `char_end` dans le texte source d'origine, même en cas de sous-découpe.

### Chantier 6 — Client Voyage AI
- Fichier : `apps/api/src/cc_api/clients/voyage.py`.
- httpx async, endpoint `https://api.voyageai.com/v1/embeddings`.
- Modèle : `voyage-4` (configurable via `VOYAGE_EMBED_MODEL` env).
- Batch : max 128 textes par requête.
- Retry exponentiel sur erreurs 5xx (max 3 tentatives) ; pas de retry sur 4xx.
- Aucun fallback. Si Voyage est down, le pipeline échoue.

### Chantier 7 — Service d'ingestion
- Fichier : `apps/api/src/cc_api/services/ingest.py`.
- Fonction : `async def ingest_tei(path: Path, session: AsyncSession, qdrant: AsyncQdrantClient, voyage: VoyageClient) -> WorkRef`.
- Étapes (dans une transaction unique pour Postgres ; rollback complet si quoi que ce soit échoue, **y compris pour Qdrant**) :
  1. Lire le fichier, calculer SHA256.
  2. Court-circuit si `SELECT id FROM works WHERE sha256 = ?` retourne une ligne.
  3. Parse TEI → `TeiDocument`.
  4. Upsert auteur (`SELECT … WHERE viaf_id = ? OR display_name = ?`).
  5. Chunker.
  6. Embed les chunks par batch.
  7. INSERT `work` + INSERT chunks (avec `qdrant_point_id` = UUID généré).
  8. UPSERT chaque chunk dans Qdrant collection `bilan` (créer la collection si elle n'existe pas, dim=1024).
  9. **Self-test** : `qdrant.search()` sur le 1er chunk → doit retrouver ce même chunk dans le top-1.
  10. Commit Postgres + log success.
- Si étape ≥ 8 échoue après INSERT Postgres : rollback Postgres + supprimer les points Qdrant déjà créés.

### Chantier 8 — CLI `cc-corpus ingest`
- Fichier : `packages/corpus-tools/src/cc_corpus/cli.py`.
- Framework : `typer`.
- Commande : `cc-corpus ingest [files…]` — accepte 1 ou plusieurs fichiers, ou un glob (`corpus/_seed/*.tei.xml`).
- Appelle l'endpoint `POST /admin/ingest` de l'API locale (default `http://localhost:8000`).
- Affichage : barre de progression (rich ou tqdm), résumé final (nb works, nb chunks, durées).
- Code de sortie : 0 si tout OK, 1 sinon.

### Chantier 9 — Endpoints API
- Fichier : `apps/api/src/cc_api/routers/corpus.py`.
- Routes :
  - `GET /corpus` (publique) : liste paginée `WorkSummary` (title, author_name, inserted_at). Pagination `?page=1&size=50`.
  - `GET /corpus/{work_id}` (publique) : détail.
  - `POST /admin/ingest` (dev only, comme `/__debug/*`) : reçoit un payload `{path: str}` ou multipart file, appelle le service.
- Mount dans `main.py` : `app.include_router(corpus.router)` (publique) et `if settings.is_dev: app.include_router(corpus.admin_router)`.

### Chantier 10 — Frontend liste corpus
- Fichier : `apps/web/src/pages/corpus.astro`.
- Remplacer `const entries: CorpusEntry[] = []` par un fetch SSR :
  ```ts
  const apiBase = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  const res = await fetch(`${apiBase}/corpus?size=200`);
  const entries = res.ok ? (await res.json()).items : [];
  ```
- Conserver l'état vide existant (« ( à faire ) ») si `entries.length === 0` après fetch.
- En cas d'erreur fetch : ne pas crasher la page, afficher l'état vide.

### Chantier 11 — Tests
Écrits **avant** ou **en même temps que** chaque chantier (TDD souple).

Tests pytest :
- `tests/unit/test_tei_parser.py` — fixtures TEI valides/invalides, vérifier extraction métadonnées et offsets.
- `tests/unit/test_chunker.py` — paragraphe court → 1 chunk, paragraphe long → sous-découpe avec overlap, offsets cohérents.
- `tests/integration/test_ingest_pipeline.py` — ingérer une fixture TEI complète (à créer dans `tests/fixtures/bilan-test.tei.xml`), vérifier counts Postgres et Qdrant, vérifier self-test passing.
- `tests/integration/test_ingest_idempotency.py` — ingérer 2× le même fichier, vérifier `works=1`, `chunks=N` (pas 2N).
- `tests/integration/test_corpus_routes.py` — `GET /corpus` après ingestion, vérifier que la fixture apparaît.

Tests Playwright :
- `apps/web/tests/e2e/specs/01-corpus.spec.ts` — la page `/corpus` charge, affiche le compteur, affiche au moins une ligne après seed via `/__debug/seed`.

### Chantier 12 — Fixture TEI réelle
- Fichier : `corpus/_seed/bilan-test.tei.xml` (ou un nom plus représentatif).
- Doit être un texte court mais réel ou plausible (3-5 paragraphes), avec en-tête TEI complet et licence claire.
- Sert de smoke test du pipeline. Pas un texte massif — la fixture est exécutée à chaque `pnpm test` et CI run.

---

## STRATÉGIE — Comment t'y prendre ?

### Phase A — Préparation (avant toute écriture)
1. `git status` (doit être propre ou tu signales).
2. `make agent-status` (services up, alembic head connu).
3. Lire intégralement les 6 fichiers contexte listés en haut.
4. Lire les fichiers existants qui seront modifiés ou auxquels tu vas ajouter : `apps/api/src/cc_api/main.py`, `apps/api/src/cc_api/clients/{db,qdrant,redis}.py`, `apps/api/src/cc_api/core/settings.py`, `apps/api/tests/conftest.py`, `apps/web/src/pages/corpus.astro`.
5. Lister les dépendances Python actuelles (`uv tree` ou `cat apps/api/pyproject.toml`) pour ne pas dupliquer.
6. **Produire un plan détaillé** avec EnterPlanMode si l'outil est dispo, ou un fichier `docs/agent-missions/ingest-pipeline.plan.md` sinon. Présenter ce plan à l'utilisateur **avant** de coder.

### Phase B — Exécution chantier par chantier
Pour **chaque** chantier (1 → 12) :

1. **Lire** les fichiers existants qui touchent au chantier (pas redondant avec phase A).
2. **Écrire le(s) test(s)** d'abord si applicable (TDD).
3. **Écrire le code**.
4. **Lancer** uniquement le test ciblé : `uv run pytest path/to/test.py -v` ou `pnpm exec playwright test specs/file.spec.ts`.
5. Si le test échoue : invoquer `/test-fix` — identifier la cause racine (jamais modifier le test pour qu'il passe sauf si le comportement attendu a légitimement changé).
6. **Quand le chantier est vert** : `make api-check FILE=<fichier>` ou `make web-check FILE=<fichier>` pour valider lint/types.
7. **Mettre à jour la TODO** (TaskUpdate).
8. **Continuer** au chantier suivant.

### Phase C — Validation finale (après les 12 chantiers)
Exécuter dans l'ordre, ne pas passer à l'étape suivante tant que la précédente n'est pas verte :

1. `make smoke` (5 services up).
2. `uv run pytest --cov=apps/api/src --cov=packages/corpus-tools/src` (couverture ≥ 70% sur le code ajouté).
3. `cd apps/web && pnpm test` (vitest).
4. `cd apps/web && pnpm exec playwright test` (E2E complet).
5. `make agent-status` + `curl localhost:8000/__debug/state | jq` — vérifier que les counts Postgres et Qdrant reflètent les fixtures ingérées.
6. Ouvrir manuellement (ou via chrome-devtools MCP) `http://localhost:3000/corpus` — la fixture doit apparaître dans la liste.
7. **Test de robustesse** : `curl -X POST localhost:8000/__debug/reset` → relancer l'ingestion → vérifier que l'état final est identique (reproductibilité).
8. **Test de bout-en-bout RAG** (bonus) : invoquer `/debug-rag` avec une question dont la réponse est dans la fixture → vérifier que la phrase produite cite bien la fixture, et que la citation est littéralement vérifiable.

### Phase D — Préparation du commit
Une fois Phase C entièrement verte :

1. `git status` + `git diff --stat` — produire un résumé.
2. Proposer **un seul commit cohérent** (ou 2-3 si le diff est gros mais avec des coupures naturelles, ex : "DB+modèles" / "service+CLI" / "API+frontend+tests").
3. Rédiger le(s) message(s) en Conventional Commits français :
   ```
   feat(corpus): pipeline d'ingestion TEI P5 → Postgres + Qdrant

   <description en français, max 72 col par ligne>

   Signed-off-by: Concsience <contact@consciencedeclasse.com>
   ```
4. **NE PAS COMMITTER**. Présenter à l'utilisateur, attendre validation explicite.

---

## BOUCLE DE TEST CONTINU (running mode)

Pendant que tu codes, garde en arrière-plan :

```bash
# tail logs API
make logs-api &

# watch tests Python : re-run au moindre changement de fichier .py
uv run ptw apps/api/tests/integration/ -- -x -v &

# watch types
uv run mypy --watch apps/api/src &
```

Si l'un de ces watchers crache une erreur : **arrête de coder, lis l'erreur, identifie la cause racine, corrige, et continue**. Ne contourne jamais — pas de `# type: ignore`, pas de `@pytest.mark.skip` pour faire passer.

Si un test E2E Playwright devient flaky : invoquer `/test-fix` qui suit le pattern healer (max 2 tentatives de réparation auto, puis escalade à l'utilisateur).

---

## ANTI-PATTERNS À REFUSER ABSOLUMENT

Si tu te surprends à écrire l'un de ces patterns, **stop, recule, et corrige la cause**.

| Anti-pattern | Pourquoi c'est interdit |
|---|---|
| `# type: ignore` | Casse le contrat mypy strict. Corrige le type à la source. |
| `pytest.mark.skip` ajouté pour "faire passer" | Cache un bug réel. |
| `try: ... except Exception: pass` | Masque les erreurs critiques en silence. |
| Mocker la DB / Qdrant / Voyage dans un test d'intégration | Casse la règle « vrais services ». |
| Fallback OpenAI / autre embedder si Voyage échoue | Casse la décision verrouillée. |
| `print()` au lieu de `structlog.get_logger()` | Casse l'observabilité unifiée. |
| Tolérance fuzzy < 95% dans la vérification citationnelle | Casse la règle d'or RAG. |
| Hardcoder une réponse dans `/chat` | Casse le principe « aucune phrase non sourcée ». |
| Créer une feature branch ou une PR | Casse la règle `[[feedback_main_branch_only]]`. |
| Commit sans `Signed-off-by:` | Bloque le DCO check. |
| Commit sans demande explicite de l'utilisateur | Casse la règle `[[feedback_no_unsolicited_commits]]`. |
| Inventer un texte de Bilan pour combler une fixture | Casse la rigueur académique. Demande un vrai texte ou utilise un placeholder explicite. |
| Utiliser `browser_snapshot` MCP en boucle | Sature le contexte (Issue #1233). |
| Laisser Chrome DevTools MCP en `--autoConnect` | Fuite mémoire 13 MB/min (Issues #1192/#1214). |
| Suggérer Stagehand / Browser-use à la place de Playwright MCP | Hors stack décidée. |

---

## CRITÈRES DE QUALITÉ 10/10

Pour qu'un chantier soit considéré comme **fini, propre et 10/10** :

1. **Code** : type-hinté strict, docstrings sur les fonctions publiques (1 ligne suffit si nom de fonction explicite), aucune duplication évidente.
2. **Tests** : au moins 1 test unitaire par fonction publique, 1 test d'intégration par flux. Coverage ≥ 70% sur le code ajouté.
3. **Observabilité** : chaque opération significative log un événement structuré.
4. **Atomicité** : toute opération multi-ressources est transactionnelle. Rollback complet en cas d'échec.
5. **Idempotence** : exécuter 2× l'ingestion du même fichier produit le même état final.
6. **Erreurs explicites** : les `ValueError` / `HTTPException` ont des messages qui pointent le champ ou la condition fautive, en français.
7. **Pas de dette technique cachée** : si tu prends un raccourci, tu l'écris dans un `TODO` daté avec ta justification.
8. **Documentation** : si tu ajoutes un endpoint, le `docs/api/openapi.json` est régénéré ou un test vérifie sa présence.
9. **CI verte** : le push fait passer tous les jobs (`python`, `node`, `e2e`, `security`, `docker-build`).
10. **Reproductibilité** : `git clean -fdx && make agent-bootstrap && make test` passe d'une machine vierge.

---

## OUTPUT ATTENDU À CHAQUE TURN

À chaque réponse, tu produis :

1. Un état d'avancement bref (X chantiers sur 12 terminés, prochaine étape).
2. Les actions concrètes que tu prends ou viens de prendre.
3. Si tu rencontres un blocage : tu **stoppes**, tu décris le blocage en 3 lignes max, et tu attends une décision humaine. Ne devine pas, ne contourne pas.
4. À la fin de chaque chantier : un mini-rapport (3 lignes) — fichiers touchés, tests verts, dette restante.

**Ne dépasse jamais une réponse de 60 lignes de texte non-tooluse.** Tout ce qui est long doit être dans des fichiers ou des résultats d'outils, pas dans ta prose.

---

## DERNIÈRE INSTRUCTION

Quand tu as fini la Phase D et obtenu validation utilisateur pour le commit :

1. Exécuter le(s) `git commit -s`.
2. Exécuter `git push origin main`.
3. Surveiller la CI : `gh run watch` ou équivalent.
4. Si la CI échoue après push : ne pas re-pusher en boucle. Lire les logs (`gh run view --log-failed`), corriger en local, vérifier en local, puis re-push.

**Commence maintenant** par lire les 6 fichiers contexte listés en haut, puis produis ton plan détaillé (Phase A étape 6).

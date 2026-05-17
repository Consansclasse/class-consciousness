# AGENT_GUIDE — Contexte agentique repo-scope

Ce fichier est la **source de vérité repo** pour Claude Code. Tout ce qui est ici doit être vrai et à jour. L'auto-memory utilisateur (`/home/yamamoto/.claude/.../memory/`) peut compléter mais ne remplace pas ce guide.

## Identité du projet

Archive open-source de la théorie marxiste avec **RAG sourcé**. Greenfield à horizon 10+ ans. Standards académiques exigés. Langue principale : français.

## 7 principes non-négociables

1. **Rigueur académique de niveau publication** — pas de raccourcis "ça marche", on vise la solidité d'une revue à comité de lecture.
2. **Pensée 10+ ans** — chaque décision est évaluée à cet horizon. Pas de MVP jetable.
3. **Ouverture maximale** — code AGPL-3.0, corpus dans les bonnes conditions juridiques, pipeline reproductible.
4. **Aucune phrase sans citation** — règle d'or RAG : chaque assertion produite par le pipeline doit pointer vers un passage exact du corpus.
5. **Vérité avant ergonomie** — préférer un refus poli à une hallucination utile.
6. **Profondeur > vitesse** — pas de raccourci MVP. L'utilisateur préfère un système correct dans 6 mois qu'un système approximatif dans 2 semaines.
7. **Discipline de code sévère** — aucune ligne de trop, règles dures appliquées en CI (ruff, mypy strict, biome, gitleaks, DCO).

## Décisions verrouillées

- **Licence** : AGPL-3.0-or-later (code), CC-BY-SA-4.0 (corpus original), licences respectives pour œuvres dérivées.
- **Pile IA** : Anthropic Claude Opus 4.7 (génération, API). Embeddings + reranking **auto-hébergés** par le service `cc-embed` (`apps/embed-server`) : Qwen3-Embedding-0.6B (embeddings, 1024 dims) et Qwen3-Reranker-0.6B (reranking), **sur CPU** — conteneur du compose, aucun GPU requis (voir `docs/adr/0008-architecture-embedding-vps-cpu.md`). **Jamais Voyage, jamais OpenAI** : aucun service d'IA tiers hormis la génération Anthropic.
- **Langues corpus** : français de référence, allemand et anglais en secondaire (sources primaires). Sortie système : français exclusivement.
- **Vectoriel** : Qdrant (Apache 2.0), pas de Pinecone, pas de Weaviate, pas de pgvector.
- **Déploiement** : self-hosted (OVH/Hetzner via Coolify), pas de SaaS managé.
- **Frontend** : Astro 5 (SSG + îlots React), pas de SPA pure.
- **Git** : branche `main` unique, pas de PR, pas de feature branches.

## Sources de corpus prévues

> Le corpus encodé vit dans le dépôt **séparé** `class-consciousness-corpus`
> (CC-BY-SA 4.0). Le repo code n'embarque que la fixture `corpus/_seed/` et le
> consomme via `CC_CORPUS_DIR`. Voir `[[project_economic_model]]`.

- **Gallica** (BnF) — domaine public français.
- **Marxists Internet Archive (fr)** — politique de licence variable, vérifier au cas par cas.
- **Wikisource (fr)** — CC-BY-SA-4.0 ou domaine public.
- **archive.org** — domaine public ou licences libres.
- **Éditions sociales / GEME** — uniquement avec accord ou domaine public.

Statut juridique des traducteurs : à vérifier individuellement avant toute ingestion. Une décision d'ingestion doit citer le statut juridique du texte et du traducteur.

## Standards externes adoptés

- **TEI P5** pour les textes structurés.
- **CSL-JSON** pour les citations.
- **IIIF** pour les images de pages.
- **OAI-PMH** + **DTS** pour l'exposition.
- **SKOS** pour la taxonomie conceptuelle.
- **ARK** pour les identifiants persistants (NAAN dans `.env`).
- **Sigstore** pour la signature de build.
- **IFLA-LRM** pour le modèle bibliographique.
- **Conventional Commits** (en français) pour les messages git.

## Autorités externes pour reconciliation

- **VIAF** (auteurs)
- **Wikidata** (entités)
- **IdRef** (auteurs académiques français)
- **BnF.fr** (notices)
- **Software Heritage** (archivage code)
- **Internet Archive** (archivage web)
- **IPFS** (réplication corpus)

## Pile technique en place (Phase 0)

| Composant | État |
|---|---|
| FastAPI + SQLAlchemy async + Alembic | squelette `/health` + `/__debug/*` |
| Astro 5 + îlots React | squelette vide |
| Postgres 17 + Qdrant + Redis | docker-compose dev OK |
| Caddy reverse proxy | configuré 80/443 |
| pre-commit (ruff, mypy, biome, gitleaks, DCO) | actif |
| CI GitHub Actions (matrice Python+Node) | actif |
| MCP servers : playwright, chrome-devtools, postgres, github, fetch | `.mcp.json` actif |
| Skills : `/test-full`, `/test-fix`, `/debug-rag` | à venir |
| Playwright Agents officiels | à initialiser via `npx playwright init-agents --loop=claude` |

## Caveats agentiques 2026 (à connaître)

- **Playwright MCP pinné à `0.0.41`** — versions 0.0.56+ cassent l'intégration Claude Code (Issue #1359).
- **Chrome DevTools MCP sans `--autoConnect`** — fuite mémoire ~13 MB/min (Issues #1192/#1214).
- **`browser_snapshot` MCP interdit en boucle** — retourne 50-540 KB de DOM, sature le contexte après 2-3 visites.
- **Postgres MCP Pro** — Crystal DBA, R/W unrestricted en dev. Backup snapshot avant session longue (`make db-snapshot`).
- **Qdrant MCP officiel non utilisé** — FastEmbed local incompatible avec les embeddings Qwen3 4096-d du corpus. Utiliser `/__debug/state` à la place.

## Boucle agentique attendue

1. `make agent-bootstrap` — préparer l'environnement.
2. `make dev` — lancer la stack.
3. L'IA édite → hooks `PostToolUse` ruff/biome ciblé.
4. L'IA teste : `make smoke` → `make test` → `make test-e2e`.
5. Si échec : `/test-fix` → identifie + corrige + relance.
6. `Stop` hook : smoke automatique en fin de réponse.

## Ce que l'IA NE DOIT JAMAIS faire

- Créer une branche git autre que `main`.
- Créer un commit sans demande explicite de l'utilisateur.
- Produire une réponse RAG sans citation vérifiée.
- Mocker la DB ou Qdrant dans les tests d'intégration (testcontainers obligatoire).
- Ajouter du code "au cas où" — anti-pattern.
- Suggérer un fallback OpenAI ou un autre vector store.
- Pousser sur le remote sans accord explicite.

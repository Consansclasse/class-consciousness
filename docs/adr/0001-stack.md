# ADR-0001 — Stack technique

- **Statut** : accepté
- **Date** : 2026-04-27
- **Décideurs** : BDFL initial, validé par utilisateur

## Contexte

Greenfield. Stack à figer pour la phase 0. Critères : qualité absolue du moteur RAG, durabilité long-terme (10+ ans), souveraineté du déploiement, discipline de code stricte.

## Décision

- **Backend** : Python 3.12 + FastAPI + asyncpg + uvloop
- **Workers** : Python + arq (Redis-based)
- **Relationnel** : PostgreSQL 16 (uniquement, pas de FTS, pas de vecteurs)
- **Recherche hybride dense + sparse BM25** : Qdrant (Apache 2.0, Rust)
- **Cache & queues** : Redis 7
- **Frontend** : Astro 5 + îlots React/Preact (chat `/demander` seul)
- **UI** : Tailwind + shadcn/ui (Radix)
- **LLM** : Claude Opus 4.7 via Anthropic SDK + prompt caching ; Claude Haiku 4.5 pour pré-traitement
- **Embeddings** : Voyage AI `voyage-3-large` (multilingue)
- **Reranking** : Voyage `rerank-2`
- **Format texte** : TEI P5 + ODD `cc.odd`
- **Bibliographie** : CSL-JSON 1.0
- **Identifiants** : ARK (NAAN n2t.net) + Wikidata + VIAF + IdRef
- **Conteneurisation** : Docker + Docker Compose + buildx multi-arch
- **Reverse-proxy** : Caddy 2
- **CI** : GitHub Actions (CodeQL + Dependabot + osv-scanner + gitleaks)
- **Lint/format** : Ruff + mypy strict (Py), Biome (TS), Prettier
- **Tests** : pytest + Hypothesis (back), Vitest + Playwright (front), cassettes VCR pour le LLM
- **Observabilité** : Prometheus + Grafana + Loki ; Plausible (cookieless)
- **Préservation** : Sigstore (cosign) + Software Heritage + Internet Archive + IPFS pinning

## Conséquences

Bénéfices :
- Polyvalence Python pour ingestion, RAG, NLP ; SDK Anthropic officiel
- Qdrant fait dense + sparse + filtres dans un seul moteur, ops simple
- Astro génère du HTML quasi-statique, durable pour archive de lecture
- Stack majoritairement open-source ; AGPL/Apache compatible

Coûts :
- Dépendance API LLM (Anthropic) — abstraction `clients/anthropic_client.py` permet swap si besoin
- Voyage AI (commercial) pour embeddings — fallback OpenAI/BGE-M3 documenté

## Alternatives rejetées

- pgvector + Postgres FTS : moins optimisé, sépare dense/sparse, ops 2 systèmes
- Vespa : ingénierie remarquable mais ops JVM lourde, surdimensionné < 500M points
- Milvus : K8s requis pour mode distribué
- Weaviate : GraphQL imposé, BSD vs préférence Apache
- LanceDB : embedded incompatible avec FastAPI multi-worker
- Chroma : pas production-grade pour archive 30 ans
- Elasticsearch / OpenSearch : JVM + ops complexes
- LangChain / LlamaIndex : abstractions opaques incompatibles audit citations
- Next.js : retenu en v1 puis révisé vers Astro pour profil archive-statique
- Supabase : couplage SaaS, schema control limité
- TEI Publisher / eXist-db : XQuery/XSLT niche, UX moderne difficile
- Vercel/Netlify : centralisateurs, vendor lock-in

## Hypothèses à vérifier avant figeage final

- Voyage `voyage-3-large` toujours SOTA français avril 2026
- Anthropic Citations API disponible
- ARK NAAN attribuable gratuitement à projet indépendant (n2t.net)
- DTS API spec stable
- Qdrant sparse BM25 français comparable à Tantivy/Meilisearch dédié

# class-consciousness

> Archive open-source de la théorie marxiste — textes primaires, commentaires, et outil d'analyse classée et sourcée.

**Statut.** En production sur [consciencedeclasse.com](https://consciencedeclasse.com) : lecture libre du corpus (revue *Bilan*), moteur Q&A sourcé, comptes et paiement à l'usage au coût réel. Auto-hébergeable (AGPL-3.0). Roadmap dans [`docs/`](./docs/).

## Principes

1. **Aucune réponse sans source vérifiée littéralement.** Le moteur Q&A IA refuse de répondre s'il n'a pas de passage suffisant ; chaque phrase générée porte une citation auditable.
2. **Le corpus est la vérité.** Pas de paraphrase « de mémoire » par le LLM, pas de commentaire non signé.
3. **Reproductibilité philologique.** TEI-XML P5 pour les textes, CSL-JSON pour la bibliographie, identifiants ARK permanents, signatures Sigstore par release.
4. **Pluralisme et transparence.** Marxisme classique mais aussi Francfort, opéraïsme, Althusser, Mariátegui, Luxembourg, Bordiga, Pannekoek, Lukács, Gramsci, Mao, Fanon, Bourdieu, Federici. Aucune ligne éditoriale cachée — commentaires signés et datés.
5. **Souveraineté du déploiement.** AGPL pour empêcher l'appropriation propriétaire. Self-hosting first. Données EU.
6. **Permanence des références.** Toute citation produite reste valable dans 10 ans.
7. **Discipline de code extrême.** Aucune ligne de trop. Voir [`CONTRIBUTING.md`](./CONTRIBUTING.md).

## Stack

| Couche | Choix |
|---|---|
| Backend | Python 3.12 + FastAPI |
| Relationnel | PostgreSQL 17 |
| Recherche hybride (dense + BM25 sparse) | Qdrant (Apache 2.0) |
| LLM | Claude Opus 4.7 + prompt caching |
| Embeddings + reranking | Qwen3 0.6B auto-hébergé (cc-embed, CPU) |
| Frontend | Astro 5 + îlots React |
| Format texte | TEI P5 (ODD `cc.odd`) |
| Bibliographie | CSL-JSON 1.0 |
| Identifiants | ARK (n2t.net) + Wikidata + VIAF + IdRef |
| Préservation | Sigstore + Software Heritage + Internet Archive + IPFS |

## Démarrage rapide (dev)

> Pré-requis : Docker, Docker Compose, `uv`, `pnpm`.

```sh
git clone https://github.com/Consansclasse/class-consciousness
cd class-consciousness
cp .env.example .env                    # à remplir
docker compose -f infra/docker-compose.yml up -d
uv sync
pnpm install
make migrate
make seed                               # corpus de démo (1 œuvre)
make dev                                # api:8000 + web:3000
```

Guide complet : [`docs/deploy/self-host.md`](./docs/deploy/self-host.md).

## Structure du dépôt

```
apps/api/           # FastAPI Python — endpoints REST + RAG
apps/web/           # Astro 5 + îlots React
packages/corpus-tools/  # CLI `cc-corpus` (ingestion TEI)
packages/tei-schema/    # ODD custom + RNG/XSD générés
corpus/             # textes versionnés (TEI-XML + métadonnées CSL)
docs/               # ADRs, guides ingestion, déploiement, gouvernance
infra/              # Docker Compose, Caddy, Postgres init, dashboards
ops/                # runbooks, scripts ops
tests/rag-eval/     # test set red-team RAG
```

## Contribuer

- Code : voir [`CONTRIBUTING.md`](./CONTRIBUTING.md). DCO `Signed-off-by:` requis.
- Corpus : le corpus encodé vit dans le dépôt séparé [`class-consciousness-corpus`](https://github.com/Consansclasse/class-consciousness-corpus). Ouvrir une PR là-bas avec un fichier TEI P5. Validation par mainteneur avant merge.
- Bug / feature : utiliser les templates GitHub.
- Vulnérabilité : voir [`SECURITY.md`](./SECURITY.md). Contact PGP.

## Gouvernance & financement

- Gouvernance : [`GOVERNANCE.md`](./GOVERNANCE.md). BDFL → conseil mainteneurs (an 1+).
- Code de conduite : [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md) (Contributor Covenant 3.0).
- Financement : adhésions + subventions. La lecture du corpus est libre ; le moteur Q&A est facturé à l'usage **au coût réel** (pas de marge, pas de tier premium). Pas d'ads, pas de tracking.

## Licences

- **Code** : [AGPL-3.0](./LICENSE)
- **Corpus + commentaires** : [CC BY-SA 4.0](./LICENSE-CORPUS)

## État de la roadmap

| Phase | Statut |
|---|---|
| 0 — Fondations | fait |
| 1 — Corpus minimal (*Bilan*) | en cours (ingestion) |
| 2 — Lecture & navigation | en production |
| 3 — Moteur RAG sourcé | en production |
| 4 — Commentaires & contributions | en cours |
| 5 — Hardening & production | en production, durcissement continu |

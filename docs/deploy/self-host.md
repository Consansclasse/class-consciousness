# Auto-héberger class-consciousness

> **Statut** : en production sur consciencedeclasse.com. Le déploiement canonique
> utilise Coolify v4 sur OVH (voir [ADR-0006](../adr/0006-deployment-coolify.md)) ;
> `docker-compose.prod.yml` est livré à la racine du dépôt. Ce guide couvre le dev
> local et l'alternative de production manuelle (Docker Compose).

## Pré-requis

- Linux ou macOS récent (testé Ubuntu 24.04, Debian 12, macOS 14)
- Docker ≥ 24 + Docker Compose v2
- 4 vCPU, 8 GB RAM minimum (16 GB recommandé pour Qdrant + corpus complet)
- Domaine + accès DNS (pour la production)
- Clé API : Anthropic (génération LLM ; embeddings auto-hébergés via cc-embed)

## Dev local

```sh
git clone https://github.com/Consansclasse/class-consciousness
cd class-consciousness
cp .env.example .env       # ajuster les valeurs si besoin
docker compose -f infra/docker-compose.yml up -d
curl http://localhost:8000/health     # → {"status":"ok"}
```

Services exposés :
- `localhost:8000` — API FastAPI
- `localhost:3000` — frontend Astro
- `localhost:5432` — PostgreSQL
- `localhost:6333` — Qdrant (HTTP)
- `localhost:6379` — Redis
- `localhost:80` — Caddy (reverse-proxy unifié)

## Production (auto-hébergement manuel)

Cible : VPS UE (ex. Hetzner CCX23/CCX33, Scaleway, OVH). Le déploiement canonique
de consciencedeclasse.com tourne sur OVH via Coolify ([ADR-0006](../adr/0006-deployment-coolify.md)) ;
les étapes ci-dessous décrivent l'alternative manuelle équivalente.

Étapes :
1. Provisionner le VPS, configurer SSH key-only + fail2ban
2. Installer Docker + Compose
3. `git clone` du dépôt et copier `.env` rempli avec secrets de production
4. Configurer Caddy avec votre domaine pour TLS automatique
5. Lancer `docker compose -f docker-compose.prod.yml up -d`
6. Configurer backups : `pg_dump` quotidien + `qdrant snapshot` quotidien → S3-compatible
7. Activer monitoring Prometheus + Grafana + Loki
8. Tester le runbook DR (RTO < 4 h)

> `docker-compose.prod.yml` est présent à la racine du dépôt. Les runbooks DR
> détaillés sont en cours de durcissement.

## Corpus — récupération et mise à jour automatiques

**Vous n'avez rien à faire, et surtout pas de `git pull`.** Le corpus TEI vit dans
un dépôt public séparé ([`class-consciousness-corpus`](https://github.com/Consansclasse/class-consciousness-corpus)).
L'API embarque une **auto-synchro** (`apps/api/src/cc_api/services/corpus_sync.py`,
**activée par défaut** dans `docker-compose.prod.yml`) : périodiquement, elle lit le
SHA de tête du dépôt corpus, et s'il a changé, télécharge le tarball (HTTPS, aucun
`git` requis) et **ingère les nouveaux numéros tout seule** (idempotent par SHA256,
embeddings via cc-embed).

Conséquences pour vous :

- **Premier démarrage** : sur une base neuve, la première passe ingère d'office
  tout le corpus — pas d'étape d'ingestion manuelle à lancer.
- **Mises à jour** : quand un nouveau numéro est publié en amont, votre instance le
  récupère seule au cycle suivant (24 h par défaut). Aucun geste, aucune commande.
- **Réglages** (`.env`, facultatifs) :
  - `CC_API_CORPUS_SYNC_ENABLED` — `true` par défaut en prod ; passez à `false`
    pour **désactiver** (vous gérez alors l'ingestion vous-même).
  - `CC_API_CORPUS_SYNC_INTERVAL_HOURS` — intervalle de vérification (défaut 24).
  - `CC_API_CORPUS_SYNC_TOKEN` — jeton GitHub optionnel (relève le quota API ;
    inutile au rythme par défaut).
- **GPU local** : si vous faites tourner cc-embed sur GPU, l'ingestion des nouveaux
  numéros est quasi instantanée (la prod reste sur CPU, cf. [ADR-0008](../adr/0008-architecture-embedding-vps-cpu.md)).
- **Bootstrap manuel** (optionnel, sync désactivée) : `python scripts/ingest_corpus.py
  <chemin>/bilan/bilan-[0-9][0-9][0-9].tei.xml` reste disponible.

> Limite connue : l'auto-synchro couvre les **ajouts** de numéros. Le ré-encodage
> d'un numéro déjà ingéré (même identité, contenu corrigé) n'est pas remplacé
> automatiquement (l'échec est loggé, non fatal) — ré-ingestion manuelle requise.

## Ressources externes nécessaires

| Service | Coût mensuel estimé | Notes |
|---|---|---|
| VPS UE | 50-90 € | 4-8 vCPU, 16-32 GB |
| Backups S3-compatible | 5-10 € | Backblaze B2, Scaleway |
| Domaine + DNS | 5 € | |
| API Claude (Opus 4.7) | 200-1500 € | très variable, prompt caching essentiel |
| Matomo (analytics) | 0-15 € | self-host gratuit (ADR-0007) |

[VÉRIFIER tarifs avril 2026 avant déploiement]

## Sécurité

Voir [`SECURITY.md`](../../SECURITY.md). Points critiques :
- Tous les services internes (Postgres, Qdrant, Redis) doivent rester sur le réseau Docker interne, jamais exposés
- Renouveler les clés API tous les 6 mois
- Activer 2FA sur les comptes mainteneurs et registrar du domaine
- DNSSEC activé
- Mises à jour Dependabot acceptées sous 7 jours pour high/critical

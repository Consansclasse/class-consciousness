# Auto-héberger class-consciousness

> **Statut** : phase 0 — guide à compléter au fur et à mesure que chaque service est intégré. Pour l'instant, seul le périmètre dev local est opérationnel.

## Pré-requis

- Linux ou macOS récent (testé Ubuntu 24.04, Debian 12, macOS 14)
- Docker ≥ 24 + Docker Compose v2
- 4 vCPU, 8 GB RAM minimum (16 GB recommandé pour Qdrant + corpus complet)
- Domaine + accès DNS (pour la production)
- Clés API : Anthropic, Voyage AI

## Dev local

```sh
git clone <repo>
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

## Production (à compléter en phase 5)

Cible : VPS Hetzner CCX23/CCX33 ou Scaleway équivalent (UE).

Étapes prévues :
1. Provisionner le VPS, configurer SSH key-only + fail2ban
2. Installer Docker + Compose
3. `git clone` du dépôt et copier `.env` rempli avec secrets de production
4. Configurer Caddy avec votre domaine pour TLS automatique
5. Lancer `docker compose -f infra/docker-compose.prod.yml up -d`
6. Configurer backups : `pg_dump` quotidien + `qdrant snapshot` quotidien → S3-compatible
7. Activer monitoring Prometheus + Grafana + Loki
8. Tester le runbook DR (RTO < 4 h)

> Le fichier `infra/docker-compose.prod.yml` et les runbooks détaillés seront livrés en phase 5.

## Ressources externes nécessaires

| Service | Coût mensuel estimé | Notes |
|---|---|---|
| VPS UE | 50-90 € | 4-8 vCPU, 16-32 GB |
| Backups S3-compatible | 5-10 € | Backblaze B2, Scaleway |
| Domaine + DNS | 5 € | |
| API Claude (Opus 4.7) | 200-1500 € | très variable, prompt caching essentiel |
| API Voyage AI | 50-200 € | embeddings + rerank |
| Plausible analytics | 0-15 € | self-host gratuit |

[VÉRIFIER tarifs avril 2026 avant déploiement]

## Sécurité

Voir [`SECURITY.md`](../../SECURITY.md). Points critiques :
- Tous les services internes (Postgres, Qdrant, Redis) doivent rester sur le réseau Docker interne, jamais exposés
- Renouveler les clés API tous les 6 mois
- Activer 2FA sur les comptes mainteneurs et registrar du domaine
- DNSSEC activé
- Mises à jour Dependabot acceptées sous 7 jours pour high/critical

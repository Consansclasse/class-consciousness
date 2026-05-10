# Changelog

Toutes les modifications notables sont consignées ici. Le format suit [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/) ; le projet adhère à [SemVer 2.0](https://semver.org/lang/fr/).

## [Unreleased]

### Phase 0 — Fondations (en cours)

- Mise en place repo : licence AGPL-3.0 (code), CC BY-SA 4.0 (corpus), README, CODE_OF_CONDUCT, CONTRIBUTING, SECURITY, GOVERNANCE
- Squelette monorepo `apps/` `packages/` `corpus/` `docs/` `infra/` `ops/` `tests/`
- ADRs : 0001 stack, 0002 TEI, 0003 RAG, 0004 modèle données, 0005 ARK, **0006 déploiement Coolify sur OVH `51.68.129.187` + `consciencedeclasse.com`** (multi-apps, critère SSD obligatoire), **0007 analytique Matomo cookieless** (mode CNIL strict, sous-domaine `analytics.consciencedeclasse.com`)
- Docker Compose dev (Postgres + Qdrant + Redis + Caddy + api + web)
- Compose prod Coolify-compatible : `docker-compose.prod.yml` (sans `networks:`, magic vars, build target `prod`, healthchecks renforcés)
- Compose Matomo séparé : `infra/matomo/docker-compose.yml` (matomo apache + mariadb LTS + cron archivage horaire)
- Snippet Matomo cookieless dans `apps/web/src/pages/index.astro` (`disableCookies`, `setDoNotTrack`, `anonymizeIp`) ; page `/legal/privacy`
- Runbooks ops : `coolify-deploy.md`, `coolify-backup-restore.md` (S3 OVH `GRA`, triple couche, sous-section MariaDB Matomo), `coolify-incident.md` (rollback + DR + intrusion), `matomo-deploy.md` (wizard + CNIL + GeoIP DB-IP)
- `ops/drills.md` initialisé pour journaliser les drills backup trimestriels

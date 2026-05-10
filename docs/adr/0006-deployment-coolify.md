# ADR-0006 — Déploiement Coolify v4 sur OVH (consciencedeclasse.com)

- **Statut** : accepté
- **Date** : 2026-04-28
- **Décideurs** : BDFL initial, validé par utilisateur
- **Remplace** : aucun (deux tentatives précédentes — `0c536f3` et `b0c9782` — ont été revertées par `f64ce94` et `b35d894` ; cet ADR repart à zéro)

## Contexte

ADR-0001 fixe « Hetzner/Scaleway UE » sans figer l'orchestrateur ni la machine cible. Deux ADR-0006 antérieurs ont été reverted :
- v1 (`0c536f3`) actait OVH Public Cloud B3-8/B3-32 + Coolify.
- v2 (`b0c9782`) pivotait vers Kimsufi KS-1-B (HDD SATA, datacenter Limburg DE) avec quatre dettes techniques explicitement acceptées, dont — point critique — le stockage HDD.

Cause confirmée du revert (utilisateur, 2026-04-28) : **mauvaise cible VPS**. Le HDD aurait dégradé Qdrant (random-read latence ×100, RAG inexploitable au-delà de l'index en RAM). Cette dette ne devait pas être acceptée.

Nouveau VPS proposé : `51.68.129.187`. Domaine `consciencedeclasse.com` déjà chez OVH (NS `*.anycast.me`, root A déjà pointé sur l'IP). Multi-apps prévues sur la même machine (Matomo + class-consciousness + futures).

## Décision

- **Hébergeur** : OVH (range `51.68.0.0/16`, type exact à confirmer en Phase 0 du runbook). Région UE.
- **Machine** : `51.68.129.187`.
- **Orchestrateur** : Coolify v4 self-hosted (Apache-2.0).
- **Reverse proxy + TLS** : Traefik intégré à Coolify, Let's Encrypt automatique. Pas de Caddy en prod (le Caddyfile dev est conservé, `infra/caddy/Caddyfile`, mais n'est pas déployé).
- **Compose prod** : `docker-compose.prod.yml` ; pas de section `networks:` (gotcha Coolify documenté), pas de service `caddy`, pas de ports exposés sur les bases.
- **Architecture web↔api** : sous-domaines split (`consciencedeclasse.com` web, `api.consciencedeclasse.com` api), CORS ajouté à la 1re route consommée par le navigateur.
- **Auto-deploy** : webhook GitHub via GitHub App Coolify, branche `main`.
- **Bases applicatives** : déclarées dans le compose, backups assurés par Scheduled Tasks Coolify (pas le natif réservé aux *standalone Coolify Database resources*).
- **Backups** : OVH Object Storage S3 région `GRA` (souveraineté FR — principe 5).

### Critère dur figé

**Le disque du VPS DOIT être SSD ou NVMe** (`lsblk -o ROTA` = 0). Tout VPS HDD est un NO-GO immédiat pour ce projet, sans clause de revue. C'est ce qui a fait revert l'ADR-0006 v2 ; la leçon est inscrite ici.

### Aucune dette technique acceptée

Contrairement à l'ADR-0006 v2 qui acceptait quatre dettes (HDD, pas de SLA, backups manuels, datacenter DE), cet ADR n'en accepte aucune. Si une dette apparaît à l'exécution, elle bloque l'ADR et exige un nouveau pivot.

## Conséquences

Bénéfices :
- UI multi-apps native (cadre déjà prévu pour Matomo et au-delà).
- Auto-deploy GitHub-driven, rollback via UI Coolify.
- Reverse proxy + TLS sans configuration manuelle (un FQDN par service, magic vars `SERVICE_*`).
- Souveraineté UE (OVH France).
- Self-hostable, AGPL-compatible.

Coûts :
- Surface d'instabilité Coolify (PaaS jeune, ~v4.x, breaking changes possibles entre versions). Mitigation : pinner `COOLIFY_VERSION` dans `/data/coolify/source/.env` après la 1re install.
- Backups des bases en compose **non couverts** par le natif Coolify (clarification doc ambiguë) → Scheduled Tasks maison (`pg_dump`, snapshots Qdrant, `restic` volumes).
- Couplage à Traefik (intégré Coolify) — si remplacement futur, refactor complet du compose et des labels.

## Alternatives rejetées

- **Kimsufi HDD** : cause directe du revert d'avril 2026 (Qdrant inutilisable).
- **Hetzner DE / Scaleway** : Hetzner = juridiction DE (souveraineté FR principe 5) ; Scaleway = instabilité pricing constatée.
- **Bare-metal sans orchestrateur** (compose + Caddy + Ansible) : ops lourd pour mainteneur unique, pas d'UI rollback.
- **Kubernetes (k3s, k0s)** : surdimensionné pour < 5 services, courbe d'apprentissage incompatible avec le bus factor de 1.
- **Dokku, CapRover** : maturité moindre, communauté plus petite, écosystème dépendances moins fourni.
- **Vercel / Netlify / Fly.io** : centralisateurs, vendor lock-in, juridiction non-UE, AGPL incompatible avec self-host garanti par le projet (principe 5).
- **Supabase** : couplage SaaS, schéma DB contrôlé partiellement, principe 5 violé.

## Hypothèses à vérifier en Phase 0 du runbook

- Type exact OVH (VPS, Public Cloud, Kimsufi/SoYouStart…) : à lire via `/etc/issue` ou OVH Manager.
- `lsblk -o ROTA` = 0 sur le disque principal (NO-GO si non).
- RAM ≥ 8 Go (multi-apps + Qdrant en mémoire pour rester sous le radar latence).
- OS : Debian 12 ou Ubuntu 22.04/24.04 LTS (Ubuntu 25.04 non-LTS = NO-GO).
- Pas de `snap`-Docker préinstallé (refusé par installer Coolify).

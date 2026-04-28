# ADR-0006 — Déploiement : OVH Public Cloud + Coolify

- **Statut** : accepté
- **Date** : 2026-04-28
- **Décideurs** : BDFL initial, validé par utilisateur
- **Remplace partiellement** : ADR-0001 (mention « Hetzner/Scaleway UE » dans la rubrique déploiement)

## Contexte

ADR-0001 mentionnait `Hetzner/Scaleway UE` comme cibles de déploiement, sans verrouillage. Au moment de provisionner réellement l'instance publique de référence (phase 0 → phase 1), il faut figer un hébergeur et un orchestrateur.

Critères :

- **Souveraineté** (principe 5) : juridiction UE stricte, idéalement FR ; pas d'oligopole US.
- **Permanence 10+ ans** (principe 6) : hébergeur établi, peu de risque de disparition ou de pivot business.
- **Auto-hébergeable** sans dépendance SaaS (principe 5) : pas de Vercel/Render/Fly.io.
- **Ergonomie ops** : un dev unique doit pouvoir gérer la stack sans Kubernetes ni HashiCorp Vault.
- **AGPL-compatible** : l'orchestrateur lui-même ne doit pas imposer de modèle propriétaire.

## Décision

- **Hébergeur** : OVH **Kimsufi** dédié `KS-1-B` (32 Go RAM ECC, Xeon D-2123IT, 2× 4 To HDD RAID), datacenter Limburg (DE). Migration SSD obligatoire avant phase 3 (cf. dette n° 1).
- **Orchestrateur** : Coolify v4 self-hosted (Apache-2.0), build pack Docker Compose pointant vers `infra/docker-compose.prod.yml`.
- **Reverse proxy + TLS** : Traefik intégré à Coolify, Let's Encrypt automatique. Le service `caddy` du compose dev n'est pas dupliqué en prod.
- **Auto-deploy** : webhook GitHub via App Coolify dédiée, branche `main`.
- **Bases de données** : déclarées dans le compose pour la phase plomberie ; migration vers ressources Coolify gérées (avec backups intégrés) prévue en phase 5 hardening.
- **Co-hébergement** : matomo et class-consciousness tournent sur la même machine, ressources Coolify séparées.

## Conséquences

Bénéfices :

- Juridiction FR pure (RGPD strict), pas d'extraterritorialité US (CLOUD Act, FISA).
- OVH a 25+ ans d'existence, statut entreprise stratégique FR — risque permanence faible.
- Coolify évite l'industrie Kubernetes pour un projet à 1-2 mainteneurs ; Docker Compose déjà maîtrisé.
- Migration sortie possible : compose standard, pas de lock-in proprio Coolify (les services tournent dans Docker pur).

Coûts :

- OVH Public Cloud plus cher que Hetzner pour la même perf brute (~+30 % à specs égales).
- OVH a connu un incendie de datacenter (SBG2, 2021) ayant détruit des données client → **backups hors-site obligatoires** (Annexe C runbook).
- Coolify est jeune (v4 stable) ; bus factor du projet à surveiller. Mitigation : compose standard portable.

## Dettes techniques acceptées (Kimsufi KS-1-B)

Les compromis suivants sont assumés explicitement pour démarrer économique en phase 0-2 ; chacun a une date d'échéance.

| # | Dette | Risque | Mitigation | Échéance |
|---|---|---|---|---|
| 1 | **Stockage HDD** (2× 4 To SATA) au lieu de SSD/NVMe | Qdrant en random-read sur HDD = latence ×100. RAG inutilisable au-delà de l'index qui ne tient plus en RAM. | Maintenir l'index Qdrant en RAM (mmap). Surveiller `qdrant_memory_pressure` Prometheus. | **Phase 3 (corpus dépasse 5 Go)** : migrer vers serveur SSD (SoYouStart SYS-…-SSD ou Public Cloud B3-32). |
| 2 | **Pas de SLA Kimsufi** (best-effort) | Crash hardware = downtime indéterminé en attente intervention OVH. | Snapshots hors-site quotidiens + monitoring uptime externe (Uptime Kuma sur autre hôte ou service tiers). | Dès semaine 1 : `restic` vers OVH Object Storage opérationnel. |
| 3 | **Backups non inclus** | Perte de données si crash disque RAID + erreur humaine. | `restic` cron quotidien des volumes Docker (postgres_data, qdrant_data, redis_data) vers OVH Object Storage S3 chiffré. | Dès semaine 1 : runbook `ops/runbooks/backup-restic.md` à écrire et activer. |
| 4 | **Région DE** (Limburg) au lieu de FR | Souveraineté FR → souveraineté UE. RGPD préservé, juridiction DE pour les données. | Acceptable phase 0-2. Migration FR si bascule SSD vers Public Cloud GRA en phase 3. | Phase 3 (couplée à dette n° 1). |

## Alternatives rejetées

- **Hetzner Cloud (Falkenstein DE / Helsinki FI)** : meilleur rapport prix/perf en UE, mais juridiction DE/FI ; le porteur préfère FR pure pour cohérence éditoriale d'un projet francophone.
- **Scaleway (Paris)** : également FR, mais écosystème Public Cloud plus jeune et instable côté pricing/régions ; OVH plus prévisible long terme.
- **Bare metal OVH dédié** : surdimensionné phase 0-1, ops bien plus lourde (RAID, IPMI).
- **Kubernetes managé** (OVH Managed K8s, Scaleway Kapsule) : surdimensionné pour 1 mainteneur, ops K8s = dette opérationnelle pour 30 ans.
- **Dokku** : alternative Coolify mature mais ergonomie web moindre, pas de gestion multi-environnement out-of-the-box.
- **CapRover** : similaire à Coolify, communauté plus petite, UI moins complète.
- **Plain Docker Compose + Caddy + ansible** : artisanal, pas de UI déploiement, friction sur secrets/rollback. Acceptable mais coûteux en discipline ops continue.
- **Vercel / Netlify / Fly.io / Render** : SaaS centralisateurs, vendor lock-in, juridiction US — incompatibles principe 5.

## Hypothèses à vérifier

- Tarification OVH Public Cloud B3-8 / B3-32 confirmée [VÉRIFIER avril 2026].
- Coolify v4 toujours en développement actif [VÉRIFIER avril 2026].
- OVH supporte Ubuntu 24.04 sur l'image Public Cloud [VÉRIFIER].
- Bande passante incluse OVH suffisante pour archive consultative (~250 GB/mois inclus B3-8) [VÉRIFIER].

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

- **Hébergeur** : OVH Public Cloud, instances Compute (B3-8 phase 0+1, B3-32 dès phase 3 quand Qdrant chargera). Région primaire `GRA` (Gravelines, FR), secondaire `SBG` (Strasbourg, FR).
- **Orchestrateur** : Coolify v4 self-hosted (Apache-2.0), build pack Docker Compose pointant vers `infra/docker-compose.prod.yml`.
- **Reverse proxy + TLS** : Traefik intégré à Coolify, Let's Encrypt automatique. Le service `caddy` du compose dev n'est pas dupliqué en prod.
- **Auto-deploy** : webhook GitHub via App Coolify dédiée, branche `main`.
- **Bases de données** : déclarées dans le compose pour la phase plomberie ; migration vers ressources Coolify gérées (avec backups intégrés) prévue en phase 5 hardening.

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

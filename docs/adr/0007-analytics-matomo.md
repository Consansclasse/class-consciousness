# ADR-0007 — Analytique Matomo cookieless (exemption CNIL)

- **Statut** : accepté
- **Date** : 2026-05-10
- **Décideurs** : BDFL initial, validé par utilisateur
- **Remplace** : la mention « Plausible (cookieless) » de l'ADR-0001 §Observabilité

## Contexte

ADR-0001 listait Plausible cookieless dans la stack d'observabilité. À l'examen détaillé du choix analytique au moment de la mise en prod, trois options open-source self-hostées en UE étaient en lice — Plausible CE (AGPL-3.0, Elixir + Postgres + ClickHouse), Umami v3 (MIT, Node + Postgres réutilisable), Matomo (GPL-3.0+, PHP + MariaDB). La décision utilisateur 2026-05-10 retient Matomo.

Motifs : (a) documentation CNIL « exemption de consentement » disponible clé en main avec guide de configuration officiel ; (b) mode CNIL natif qui applique automatiquement les bonnes contraintes (strip UTM, désactive User ID, désactive e-commerce, bloque imports CRM) ; (c) marketplace de plugins riche pour évolutions futures (BotTracker, GeoIp2, CustomDimensions, QueuedTracking…).

## Décision

- **Outil** : Matomo 5.x — image officielle `matomo:5.10-apache` (variante FPM rejetée pour simplicité opérationnelle ; un seul container PHP+Apache au lieu de FPM+nginx side-car).
- **Base** : MariaDB LTS — image officielle `mariadb:lts` (alias `11.8.6`). Matomo n'a pas d'adaptateur Postgres ; nous ne pouvons pas réutiliser la Postgres 17 du projet `class-consciousness`.
- **Cron archivage** : container `matomo-cron` réutilisant l'image Matomo, boucle horaire `console core:archive --url=…`. Discipline §13bis règle 8 (pas de service à un seul appelant ; mais ici le cron est un service distinct par nature, pas un helper — l'alternative `crond` système alourdirait la config sans gain).
- **Hébergement** : Project Coolify séparé `matomo`, sous-domaine `analytics.consciencedeclasse.com`, sur le VPS OVH FR (cf. ADR-0006).
- **Mode tracking** : CNIL strict (mode natif Matomo).
  - `disableCookies()` côté tracker JS (zéro cookie posé).
  - `setDoNotTrack(true)` (DNT respecté).
  - `anonymizeIp` (2 octets IPv4 / 2 bytes IPv6).
  - User ID désactivé.
  - E-commerce désactivé.
  - Imports CRM bloqués.
  - Paramètres `utm_*` et `mtm_*` strippés à l'ingestion par le mode CNIL Matomo (vérifié 2026-05-10 sur la FAQ officielle).
  - Rétention brute à **13 mois** (conservatif vs maximum CNIL 25 mois).
- **GeoIP** : plugin GeoIp2 + DB-IP gratuite (URL pattern `https://download.db-ip.com/free/dbip-city-lite-{YYYY-MM}.mmdb.gz`, pas de compte requis, mise à jour mensuelle). MaxMind rejeté pour simplicité (pas de license key à gérer).
- **Plugins** : OFF par défaut. À envisager plus tard et dans cet ordre : BotTracker (séparer crawlers académiques), CustomDimensions (segmentation par type de contenu sans PII), QueuedTracking (uniquement si pic > 50 req/s).
- **Sauvegarde** : couche 2 du runbook backup. Préférer le backup natif Coolify (`mariadb-dump`, S3 OVH `GRA`) ; fallback Scheduled Task host-level si la doc Coolify ne couvre pas les DB déclarées en compose.
- **Page d'information visiteur + opt-out** : `consciencedeclasse.com/legal/privacy` — obligation légale CNIL.

## Conséquences

Bénéfices :
- Conformité CNIL exemption documentée par l'éditeur, contrôlable point par point.
- Souveraineté UE (instance auto-hébergée, données FR via OVH `GRA`).
- AGPL/GPL-compatible.
- Évolutif (plugins disponibles sans réécriture).

Coûts :
- +1 DB engine MariaDB. Première dette technique acceptée du projet — documentée et bornée à Matomo (pas d'usage transverse). L'alternative Umami v3 aurait évité cette dette mais aurait pénalisé la profondeur d'analyse.
- ≈ +250 Mo RAM (conteneur PHP+Apache + MariaDB tunée 512 Mo `innodb_buffer_pool_size`).
- Archive horaire via boucle `sleep 3600` plutôt que `crond` système — solution simple, pas de paquet supplémentaire dans l'image, suffisante pour archivage horaire.
- Surveillance backup natif Coolify pour DB en compose à valider en pratique (cf. `[VÉRIFIER]` ci-dessous).

## Alternatives rejetées

- **Plausible CE** (AGPL-3.0) — ajoute Elixir/Erlang + ClickHouse, deux stacks ops nouvelles. Community Edition exclut funnels et segments avancés. Trop lourd pour un mainteneur unique.
- **Umami v3** (MIT) — réutiliserait la Postgres 17 du projet (gros avantage opérationnel). Reporting plus pauvre. Conservé comme alternative documentée si la dette MariaDB devient ingérable plus tard.
- **Google Analytics / GA4** — incompatible avec le principe 5 (souveraineté UE, pas de Google obligatoire) et avec l'esprit du projet (corpus marxiste auto-hébergé).
- **Server-side log analytics seul** (GoAccess, AWStats sur logs Caddy/Traefik) — élimine tout JS client mais perd la mesure d'engagement (heartbeat, scroll, clics sortants). À envisager comme couche complémentaire, pas comme remplacement.

## Hypothèses à vérifier

- `[VÉRIFIER]` Le backup natif Coolify (`mariadb-dump`) couvre-t-il les DB déclarées en compose, ou seulement les *standalone Coolify Database resources* ? À tester pratiquement Phase 7 du runbook `coolify-deploy.md` ; fallback Scheduled Task host-level documenté dans `coolify-backup-restore.md`.
- `[VÉRIFIER]` Le plugin GeoIp2 de Matomo accepte-t-il directement le format DB-IP `dbip-city-lite-{YYYY-MM}.mmdb.gz` ou faut-il décompresser côté serveur avant ? À tester au moment de la configuration GeoIP dans le runbook `matomo-deploy.md`.

## Liens

- Doc Matomo « cookieless / exemption CNIL » : https://matomo.org/faq/how-to/how-do-i-configure-matomo-without-tracking-consent-for-french-visitors-cnil-exemption/
- Guide CNIL configuration Matomo : https://www.cnil.fr/sites/cnil/files/atoms/files/matomo_analytics_-_exemption_-_guide_de_configuration.pdf
- Délibération CNIL 2020-091 : référence des conditions d'exemption.
- ADR-0006 : déploiement Coolify multi-apps.
- ADR-0001 : stack technique (mention « Plausible cookieless » à amender en parallèle de cet ADR).

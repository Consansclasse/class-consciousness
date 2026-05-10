# Déployer Matomo cookieless via Coolify (matomo.consciencedeclasse.com)

> **Quand** : après que `coolify-deploy.md` est exécuté jusqu'à la Phase 6 inclus (Coolify installé, projet `class-consciousness` déployé, TLS UI Coolify OK).
> **Effet** : Matomo joignable en HTTPS sur `matomo.consciencedeclasse.com`, mode CNIL strict configuré, GeoIP DB-IP en place, archivage horaire actif.
> **Décision** : ADR-0007.
> **Coût mémoire** : ≈ +250 Mo RAM (PHP+Apache + MariaDB tunée à `innodb_buffer_pool_size=512M`).

## Pré-requis

- Coolify déjà installé et bindé (cf. `coolify-deploy.md` Phases 1-4).
- DNS `matomo.consciencedeclasse.com` propagé : `dig +short matomo.consciencedeclasse.com` doit retourner `51.68.129.187`. Si non : OVH Manager > Zone DNS > A `matomo` → `51.68.129.187`, TTL 300. Le wildcard `*` ajouté Phase 2 le couvre déjà ; cet enregistrement explicite reste recommandé pour traçabilité.
- Compte admin Coolify avec 2FA actif.

## Phase 1 — Création du projet Coolify (Docker Compose Empty)

Coolify > **Projects > + Add** :
- Nom : `matomo`
- Environment : `production`

Resource > **+ New > Docker Compose Empty**. Dans le champ **Docker Compose**, coller intégralement le compose ci-dessous (aligné sur le compose officiel `matomo-org/docker` Apache + MariaDB LTS) :

```yaml
services:
  matomo:
    image: matomo:5.10-apache
    environment:
      SERVICE_FQDN_MATOMO_80: matomo.consciencedeclasse.com
      MATOMO_DATABASE_ADAPTER: mysql
      MATOMO_DATABASE_TABLES_PREFIX: matomo_
      MATOMO_DATABASE_HOST: matomo-db
      MATOMO_DATABASE_DBNAME: matomo
      MATOMO_DATABASE_USERNAME: matomo
      MATOMO_DATABASE_PASSWORD: ${MARIADB_PASSWORD}
      PHP_MEMORY_LIMIT: 512M
    volumes:
      - matomo_data:/var/www/html
    depends_on:
      matomo-db:
        condition: service_healthy
    restart: unless-stopped

  matomo-db:
    image: mariadb:lts
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_unicode_ci
      - --innodb-buffer-pool-size=512M
      - --innodb-flush-log-at-trx-commit=2
    environment:
      MARIADB_AUTO_UPGRADE: "1"
      MARIADB_DISABLE_UPGRADE_BACKUP: "1"
      MARIADB_INITDB_SKIP_TZINFO: "1"
      MARIADB_DATABASE: matomo
      MARIADB_USER: matomo
      MARIADB_PASSWORD: ${MARIADB_PASSWORD}
      MARIADB_ROOT_PASSWORD: ${MARIADB_ROOT_PASSWORD}
    volumes:
      - matomo_db:/var/lib/mysql
    healthcheck:
      test: ["CMD", "healthcheck.sh", "--connect", "--innodb_initialized"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 30s
    restart: unless-stopped

  matomo-cron:
    image: matomo:5.10-apache
    entrypoint: ["sh", "-c"]
    command:
      - 'while true; do sleep 3600; php /var/www/html/console core:archive --url=https://matomo.consciencedeclasse.com/ || true; done'
    volumes:
      - matomo_data:/var/www/html
    environment:
      MATOMO_DATABASE_ADAPTER: mysql
      MATOMO_DATABASE_TABLES_PREFIX: matomo_
      MATOMO_DATABASE_HOST: matomo-db
      MATOMO_DATABASE_DBNAME: matomo
      MATOMO_DATABASE_USERNAME: matomo
      MATOMO_DATABASE_PASSWORD: ${MARIADB_PASSWORD}
    depends_on:
      matomo:
        condition: service_healthy
    restart: unless-stopped

volumes:
  matomo_data:
  matomo_db:
```

**Save**. Coolify détecte les 3 services et propose **Domains for matomo** : saisir `https://matomo.consciencedeclasse.com`.

**Environment Variables** (onglet dédié de la ressource) — Matomo nécessite deux mots de passe MariaDB explicites (le compose officiel `matomo-org/docker` les attend via `.env`). Génère-les côté local et ajoute-les dans Coolify :

```sh
openssl rand -hex 24   # pour MARIADB_PASSWORD
openssl rand -hex 24   # pour MARIADB_ROOT_PASSWORD (à conserver dans ton gestionnaire de passwords)
```

| Key | Type | Valeur |
|---|---|---|
| `MARIADB_PASSWORD` | runtime | `<sortie 1re openssl>` |
| `MARIADB_ROOT_PASSWORD` | runtime | `<sortie 2e openssl>` |

> Pourquoi pas de magic vars Coolify `SERVICE_PASSWORD_*` ? Coolify ne génère qu'**un** password par service (identifier dérivé du nom de service). Or Matomo a besoin de **deux** passwords (user `matomo` + root MariaDB). On les définit manuellement.

## Phase 2 — Premier déploiement

Bouton **Deploy**. Surveiller les logs Coolify > Deployments. Attendre que les trois services (`matomo`, `matomo-db`, `matomo-cron`) passent en `Running` + `Healthy` (typiquement < 3 min, plus si la 1re initialisation MariaDB).

Vérifications immédiates :
```sh
curl -I https://matomo.consciencedeclasse.com           # 200 + LE valid
dig +short matomo.consciencedeclasse.com                # 51.68.129.187
```

## Phase 3 — Wizard d'installation Matomo

Ouvrir `https://matomo.consciencedeclasse.com` dans le navigateur. Le wizard Matomo s'affiche.

| Étape | Valeur |
|---|---|
| Welcome | Next |
| System check | Tous verts ; corriger si jaune avant de continuer |
| Database setup | Host: `matomo-db`, login: `matomo`, password: la valeur de `MARIADB_PASSWORD` (Coolify > Resource matomo > Environment Variables), name: `matomo`, prefix: `matomo_` |
| Tables creation | Next |
| Super user | email: `consciencedeclasse@proton.me`, login: choisir, mot de passe ≥ 24 caractères depuis manager |
| Setup website | Name: `class-consciousness`, URL: `https://consciencedeclasse.com`, timezone: `Europe/Paris`, ecommerce: **NO** |
| Tracking code | **Récupérer le `Site ID` (= 1 normalement) — utilisé Phase 5** |
| Congratulations | Continue to Matomo |

## Phase 4 — Activation 2FA + durcissement config

### 4.1 — 2FA superuser

Top-right avatar > **Personal > Security > Two-factor authentication > Setup** : scanner QR, vérifier 2 codes consécutifs.

### 4.2 — `config.ini.php`

```sh
docker ps --filter label=com.docker.compose.service=matomo -q
# noter le CID (sera utilisé ci-dessous)
docker exec -it <CID> sh
# dans le container :
vi /var/www/html/config/config.ini.php
```

Vérifier ou ajouter dans la section `[General]` :
```ini
[General]
force_ssl = 1
trusted_hosts[] = "matomo.consciencedeclasse.com"
enable_auto_update = 0
assume_secure_protocol = 1
proxy_client_headers[] = "HTTP_X_FORWARDED_FOR"
proxy_host_headers[] = "HTTP_X_FORWARDED_HOST"
```

`salt = "..."` doit déjà être renseigné par le wizard ; ne pas le toucher.

Sauvegarder, quitter le container. Pas besoin de redémarrer (Matomo relit `config.ini.php` à chaque requête).

## Phase 5 — Mode CNIL strict

`Administration > Privacy` :

1. **Anonymize Visitors' IP** : ON, level `2 octets` (par défaut).
2. **Configure DNT support** : ON.
3. **GDPR Tools / Privacy Compliance** : appliquer le mode CNIL via :
   - `Administration > Privacy > Anonymize data` → activer toutes les options « anonymize ».
   - `Administration > Privacy > Asking for consent`: sélectionner « no consent required » + cocher « Activer toutes les options conformes CNIL » (libellé exact selon la version Matomo ; l'effet est : strip UTM/mtm à l'ingestion, désactive User ID, désactive e-commerce, bloque imports CRM).
4. **Data retention** : `Administration > Privacy > Anonymize data > Delete old visitor logs` → 13 mois (conservatif vs maximum CNIL 25 mois).
5. **User ID** : `Administration > Settings > Websites > class-consciousness > Manage > User ID` : laisser désactivé.

**Vérification automatique** : ouvrir `Administration > Privacy > GDPR Tools > Check GDPR compliance` ; tous les checks doivent être verts.

## Phase 6 — GeoIP DB-IP

`Administration > System > Geolocation` :

1. Provider : **GeoIp2 (PHP)**.
2. Location DB : choisir « DB-IP Lite ».
3. URL personnalisée si besoin : `https://download.db-ip.com/free/dbip-city-lite-{YYYY-MM}.mmdb.gz` (Matomo gère le placeholder de date automatiquement). Pas de compte requis.
4. Cliquer **Update Now** ; vérifier message de succès et que la DB s'est bien décompressée dans `misc/`.
5. Tester sur une visite récente : `Visitors > Locations` → la ville doit s'afficher.

> **Si Matomo ne décompresse pas le `.mmdb.gz` automatiquement** : `[VÉRIFIER]` mentionné dans ADR-0007 — basculer sur la procédure manuelle (`docker exec`, `wget`, `gunzip`, `chmod`). Documenter ici si confirmé.

## Phase 7 — Désactiver browser archiving

`Administration > System > General settings` :
- **Archive reports when viewed from the browser** : NO.
- **Archive reports at most every X seconds** : 3600 (1 heure, cohérent avec le container `matomo-cron`).

Cela force tous les rapports à être pré-calculés par le cron, jamais à la volée — indispensable en prod.

## Phase 8 — Snippet de tracking côté `class-consciousness`

Le snippet `_paq` est déjà dans `apps/web/src/pages/index.astro` (et toute page qui l'imitera). Il lit `PUBLIC_MATOMO_URL` et `PUBLIC_MATOMO_SITE_ID` au build.

Configurer dans Coolify > Resource `class-consciousness` > Environment Variables :
```
PUBLIC_MATOMO_URL = https://matomo.consciencedeclasse.com
PUBLIC_MATOMO_SITE_ID = 1
```

Si déjà fait dans `docker-compose.prod.yml > web > build.args`, c'est suffisant — Coolify les passe au build. Sinon les ajouter en variables. Redéployer le projet `class-consciousness` (Coolify UI > Resource > Redeploy).

## Phase 9 — Validation cookieless en navigation privée

1. Ouvrir Firefox en navigation privée, **désactiver** uBlock Origin pour ce test.
2. Aller sur `https://consciencedeclasse.com`.
3. DevTools > Application > Cookies : vérifier qu'**aucun** cookie `_pk_id`, `_pk_ses`, `_pk_ref`, `_pk_cvar`, `_pk_hsr` n'a été posé sur le domaine.
4. DevTools > Network : filtrer sur `matomo.php` — la requête doit partir, status 200, IP côté serveur tronquée 2 octets (vérifier dans Matomo > Visitors > Visits Log → l'IP affichée se termine par `.0.0`).
5. Activer DNT navigateur (`about:preferences > Privacy > Tell websites...`) → recharger la page → la requête `matomo.php` ne doit **plus** partir.
6. La page `https://consciencedeclasse.com/legal/privacy` doit être accessible et contenir l'opt-out fonctionnel.

Si l'un des 6 points échoue, **NE PAS** valider la Phase 9 — corriger d'abord.

## Phase 10 — Backups MariaDB Matomo

Voir `coolify-backup-restore.md` Couche 2 sous-section MariaDB Matomo. Test prioritaire : tenter le backup natif Coolify ; si KO sur DB en compose, passer au fallback Scheduled Task host-level.

## En cas d'incident

Voir `coolify-incident.md` — la procédure générique s'applique (rollback déploiement, restart container, restore volume). Spécifique Matomo :

- Si MariaDB ne démarre pas (FS plein, corruption innodb) → arrêter le projet Coolify, restaurer le dernier dump (cf. `coolify-backup-restore.md`), redémarrer.
- Si le wizard Matomo demande à nouveau une installation après redéploiement → le volume `matomo_data` a été perdu ; restaurer ou ré-installer puis re-récupérer le `Site ID`.

## Hors scope

- Intégration Tag Manager Matomo (à voir si besoins évoluent).
- Plugin BotTracker / TrackingSpamPrevention (à activer plus tard quand le trafic réel justifie).
- Heatmap / SessionRecording (premium + sortent du cadre exemption CNIL — ne **jamais** activer sans nouvel ADR).
- i18n de la page `legal/privacy` (à l'arrivée du système i18n du site).

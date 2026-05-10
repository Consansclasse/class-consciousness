# Backups & restauration class-consciousness (Coolify + OVH S3)

> **Quand** : à mettre en place en Phase 7 du runbook `coolify-deploy.md`. À drill **trimestriellement** par après.
> **Effet** : trois couches indépendantes (instance Coolify + DB applicatives + volumes) chiffrées sur OVH Object Storage `GRA` (souveraineté FR — principe 5).

## Pourquoi trois couches

| Couche | Sans elle | Probabilité de perte |
|---|---|---|
| Instance Coolify (`/data/coolify/source/.env` + `ssh/keys/`) | Tu peux réinstaller Coolify mais pas **déchiffrer** les secrets/applis existantes (l'`APP_KEY` chiffre tout dans la DB Coolify). | Crash disque, suppression accidentelle. |
| DB applicatives (Postgres, Qdrant, Redis) | Le projet est mort : corpus, embeddings, ARK perdus. | Corruption applicative, mauvaise migration, intrusion. |
| Volumes Docker (`restic`) | Filet de sécurité indépendant si `pg_dump` échoue silencieusement. | Bug subtil dans `pg_dump` ou snapshot Qdrant. |

Les trois couches se relaient : si une faille passe au travers d'une, les deux autres rattrapent.

---

## S3 OVH — préparation (une seule fois)

### Bucket

OVH Manager > **Public Cloud > Storage > Object Storage > Create bucket** :
- Nom : `cc-backups-prod`
- Région : `GRA` (Gravelines, FR — principe 5).
- Versioning : **activé**.
- Lifecycle : 30j hot → 90j cold (Glacier-like) → suppression à 365j.

### Credentials

Public Cloud > **Users & Roles > S3 user** : créer `cc-backup-writer` avec rôle `objectstore_operator` limité au bucket `cc-backups-prod`.

Récupérer `S3_ACCESS_KEY` + `S3_SECRET_KEY`. À stocker dans Coolify > **Settings > Storages > Add S3** :
- Endpoint : `https://s3.gra.io.cloud.ovh.net`
- Region : `gra`
- Bucket : `cc-backups-prod`

Tester depuis le VPS :

```sh
docker run --rm -e AWS_ACCESS_KEY_ID=$AK -e AWS_SECRET_ACCESS_KEY=$SK \
  amazon/aws-cli s3 --endpoint-url https://s3.gra.io.cloud.ovh.net \
  ls s3://cc-backups-prod/
```

---

## Couche 1 — Instance Coolify

Doc officielle : `coolify.io/docs/knowledge-base/how-to/backup-restore-coolify`.

### Backup

Coolify > **Settings > Backup > Backup Now** (manuel) ou Scheduled Task :

```sh
# Scheduled Task host-level, daily, owner = root
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
DUMP=/tmp/coolify-instance-${TS}.tar.gz

# 1. dump DB Coolify
docker exec coolify-db pg_dump -U postgres -Fc coolify > /tmp/coolify-db-${TS}.dump

# 2. tar des éléments critiques + dump
tar czf "$DUMP" \
  -C /data/coolify source/.env ssh/keys \
  -C /tmp coolify-db-${TS}.dump

# 3. chiffrement GPG (clé distincte de l'APP_KEY Coolify)
gpg --batch --yes --recipient ops@consciencedeclasse.com --encrypt "$DUMP"

# 4. upload S3
aws s3 --endpoint-url https://s3.gra.io.cloud.ovh.net \
  cp "${DUMP}.gpg" "s3://cc-backups-prod/coolify-instance/${TS}.tar.gz.gpg"

rm -f "$DUMP" "${DUMP}.gpg" /tmp/coolify-db-${TS}.dump
```

### Restauration

1. Provisionner un VPS de remplacement (mêmes specs).
2. Installer **la même version Coolify** : `curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash` (figer la version exacte avant install : `COOLIFY_VERSION=4.0.0-betaXYZ` dans l'env).
3. **Stopper Coolify** : `cd /data/coolify/source && docker compose down`.
4. Récupérer + déchiffrer le dernier backup :
   ```sh
   aws s3 cp s3://cc-backups-prod/coolify-instance/<TS>.tar.gz.gpg /tmp/
   gpg --decrypt /tmp/<TS>.tar.gz.gpg > /tmp/restore.tar.gz
   ```
5. Restaurer la DB Coolify :
   ```sh
   tar xzf /tmp/restore.tar.gz -C /tmp
   cat /tmp/coolify-db-<TS>.dump | docker exec -i coolify-db pg_restore --clean -U postgres -d coolify
   ```
6. Restaurer les SSH keys et `.env` :
   ```sh
   tar xzf /tmp/restore.tar.gz -C /data/coolify
   ```
7. Ajouter l'ancien `APP_KEY` comme `APP_PREVIOUS_KEYS` dans `/data/coolify/source/.env` si tu changes la clé.
8. Redémarrer : `bash /data/coolify/source/upgrade.sh` (ou réexécuter le script d'install).

---

## Couche 2 — DB applicatives

Important : la doc Coolify (`databases/backups`) ne précise pas si les DB **déclarées dans un compose** bénéficient du backup natif (réservé aux *standalone Coolify Database resources*). Hypothèse prudente : pas de natif → on gère via **Scheduled Tasks Coolify** ciblant chaque container du compose.

### Postgres

Coolify > Resource `class-consciousness` > **Scheduled Tasks > + Add** :

- Name : `pg-dump-daily`
- Schedule : `daily` (ou `0 3 * * *` pour 3h UTC)
- Container : `postgres`
- Command :
  ```sh
  set -euo pipefail
  TS=$(date -u +%Y%m%dT%H%M%SZ)
  pg_dump -Fc -U cc cc | gzip > /tmp/cc-pg-${TS}.dump.gz
  # upload via aws-cli sidecar ou rclone (à provisionner dans l'image ; sinon scheduled task host-level)
  ```

> **Note pratique** : l'image `postgres:17-alpine` n'embarque ni `aws-cli` ni `rclone`. Deux options :
> - **A.** Faire le `pg_dump` dans un container puis upload S3 dans une **scheduled task host-level** (recommandé).
> - **B.** Étendre l'image Postgres avec un `Dockerfile.postgres` qui ajoute `awscli` (ajout dette, pas idiomatique).
>
> On retient A. Squelette de scheduled task host-level :
>
> ```sh
> set -euo pipefail
> TS=$(date -u +%Y%m%dT%H%M%SZ)
> CID=$(docker ps --filter label=com.docker.compose.service=postgres --filter label=coolify.applicationId=<UUID> -q)
> docker exec "$CID" pg_dump -Fc -U cc cc | gzip > /tmp/cc-pg-${TS}.dump.gz
> aws s3 --endpoint-url https://s3.gra.io.cloud.ovh.net \
>   cp /tmp/cc-pg-${TS}.dump.gz "s3://cc-backups-prod/postgres/${TS}.dump.gz"
> rm /tmp/cc-pg-${TS}.dump.gz
> ```

### Qdrant

API native (pas de CLI à installer dans le container) :

```sh
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
CID=$(docker ps --filter label=com.docker.compose.service=qdrant -q)
# pour chaque collection (à dériver dynamiquement en prod)
for COLL in $(docker exec "$CID" curl -s -H "api-key: ${QDRANT_API_KEY}" http://localhost:6333/collections | jq -r '.result.collections[].name'); do
  docker exec "$CID" curl -s -X POST -H "api-key: ${QDRANT_API_KEY}" \
    "http://localhost:6333/collections/${COLL}/snapshots" -o /dev/null
  SNAP=$(docker exec "$CID" curl -s -H "api-key: ${QDRANT_API_KEY}" \
    "http://localhost:6333/collections/${COLL}/snapshots" | jq -r '.result[-1].name')
  docker cp "${CID}:/qdrant/storage/snapshots/${COLL}/${SNAP}" "/tmp/${COLL}-${SNAP}"
  aws s3 --endpoint-url https://s3.gra.io.cloud.ovh.net \
    cp "/tmp/${COLL}-${SNAP}" "s3://cc-backups-prod/qdrant/${TS}/${COLL}-${SNAP}"
  rm "/tmp/${COLL}-${SNAP}"
done
```

### MariaDB Matomo (project `matomo`)

Stratégie en deux temps :

1. **Tester d'abord le backup natif Coolify** (la doc Coolify supporte `mariadb-dump` ; ambiguïté sur les DB déclarées en compose vs *standalone Coolify Database resources*). Coolify > Resource `matomo` > **Backup** ; si l'option apparaît pour le service `matomo-db`, configurer S3 endpoint OVH `GRA` bucket `matomo-backups-prod`, schedule daily, retention 30j ; **lancer un Backup Now** pour valider.
2. **Fallback Scheduled Task host-level** si le natif n'est pas applicable :

```sh
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
CID=$(docker ps --filter label=com.docker.compose.service=matomo-db -q)
docker exec "$CID" mariadb-dump \
  -uroot -p"${SERVICE_PASSWORD_MATOMO_DB_ROOT}" \
  --single-transaction --routines --events \
  matomo | gzip > /tmp/matomo-${TS}.sql.gz
aws s3 --endpoint-url https://s3.gra.io.cloud.ovh.net \
  cp "/tmp/matomo-${TS}.sql.gz" "s3://matomo-backups-prod/db/${TS}.sql.gz"
rm "/tmp/matomo-${TS}.sql.gz"
```

> Bucket dédié `matomo-backups-prod` (séparation projets — cf. cadre multi-apps `coolify-deploy.md`). Créer chez OVH Manager > Public Cloud > Object Storage, région `GRA`, versioning activé, lifecycle 30j hot → 90j cold → 365j suppression.

**Backup volume `matomo_data`** : couvert par la Couche 3 `restic` ci-dessous (le glob `*_matomo_data` capte le volume). Indispensable pour conserver `config/config.ini.php` (`salt`, `trusted_hosts`), `plugins/` custom, `misc/` (DB GeoIP).

**Restauration MariaDB** :
```sh
zcat matomo-<TS>.sql.gz | docker exec -i <CID> mariadb -uroot -p<root_pwd> matomo
```
Puis vérifier `Administration > System > System Check` côté UI Matomo.

### Redis

Cache + queues. Perte tolérable, mais on conserve un snapshot quotidien :

```sh
set -euo pipefail
TS=$(date -u +%Y%m%dT%H%M%SZ)
CID=$(docker ps --filter label=com.docker.compose.service=redis -q)
docker exec "$CID" redis-cli -a "${SERVICE_PASSWORD_REDIS}" --no-auth-warning BGSAVE
sleep 5   # laisser BGSAVE finir
docker cp "${CID}:/data/dump.rdb" "/tmp/cc-redis-${TS}.rdb"
aws s3 --endpoint-url https://s3.gra.io.cloud.ovh.net \
  cp "/tmp/cc-redis-${TS}.rdb" "s3://cc-backups-prod/redis/${TS}.rdb"
rm "/tmp/cc-redis-${TS}.rdb"
```

---

## Couche 3 — Volumes Docker (`restic`)

Filet de sécurité parallèle aux dumps. Installer `restic` sur le host :

```sh
apt install -y restic
restic init --repo s3:s3.gra.io.cloud.ovh.net/cc-backups-prod/restic
# noter le password restic dans le manager de mots de passe
```

Scheduled Task host-level quotidienne :

```sh
set -euo pipefail
export RESTIC_REPOSITORY="s3:s3.gra.io.cloud.ovh.net/cc-backups-prod/restic"
export RESTIC_PASSWORD_FILE=/root/.restic-password
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...

# volumes Coolify : préfixe = <project_uuid>_<volume>
restic backup /var/lib/docker/volumes/*_postgres_data/_data \
              /var/lib/docker/volumes/*_qdrant_data/_data \
              /var/lib/docker/volumes/*_redis_data/_data \
              /var/lib/docker/volumes/*_matomo_data/_data \
              /var/lib/docker/volumes/*_matomo_db/_data
restic forget --keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune
```

---

## Drill de restauration trimestriel (obligatoire)

> **Sans drill réussi, le backup n'existe pas.**

1. Provisionner un VPS jetable (OVH VPS le moins cher, 2 vCPU 4 Go RAM suffisent pour le test).
2. Suivre la **Couche 1 — Restauration** ci-dessus.
3. Vérifier dans la nouvelle UI Coolify : projets visibles, secrets déchiffrés.
4. Restaurer la dernière dump Postgres et le dernier snapshot Qdrant.
5. Lancer un déploiement et vérifier `/health` + une question RAG simple si phase RAG en place.
6. Détruire le VPS jetable.
7. Consigner le drill dans `ops/drills.md` (date, durée, anomalies, actions correctives).

Calendrier : 1er drill dans les 7 jours suivant la mise en prod ; ensuite trimestriel (Q1, Q2, Q3, Q4).

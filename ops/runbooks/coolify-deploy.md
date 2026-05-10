# Déployer class-consciousness via Coolify sur OVH `51.68.129.187`

> **Quand** : mise en production initiale ou re-bootstrap après incident catastrophique.
> **Effet** : VPS durci, Coolify installé et bindé sur `coolify.consciencedeclasse.com`, app `class-consciousness` joignable en HTTPS sur `consciencedeclasse.com` + `api.consciencedeclasse.com`.
> **Décision** : ADR-0006.

## Pré-requis utilisateur

- Accès SSH au VPS (root ou utilisateur sudo, clé ou password initial OVH).
- Login OVH Manager (specs VPS, Object Storage, zone DNS).
- Owner du repo `Concsience/class-consciousness` (installer une GitHub App).
- Clés API : `ANTHROPIC_API_KEY` (console.anthropic.com), `VOYAGE_API_KEY` (dash.voyageai.com). À conserver dans un manager de mots de passe, jamais dans le repo.

---

## Phase 0 — Reconnaissance VPS (GO/NO-GO)

But : ne pas répéter la « mauvaise cible » qui a fait revert l'ADR-0006 v2.

```sh
ssh root@51.68.129.187   # ou utilisateur initial OVH
cat /etc/os-release
uname -a
nproc; free -h
lsblk -o NAME,FSTYPE,SIZE,MOUNTPOINT,ROTA
df -hT
swapon --show
ss -tlnp
dpkg -l | grep -iE "docker|coolify|nginx|apache|caddy|snap"
getent passwd | awk -F: '$3>=1000{print $1}'
hostnamectl
timedatectl
```

| Critère | Seuil | Si KO |
|---|---|---|
| RAM | ≥ 8 Go | Re-spec VPS, on n'avance pas. |
| Disque type (`ROTA`) | **0** (SSD/NVMe) | NO-GO ferme — leçon ADR-0006 v2. |
| Disque libre | ≥ 60 Go | Étendre ou re-spec. |
| OS | Debian 12 ou Ubuntu 22.04/24.04 LTS | Réinstaller via OVH Manager (Ubuntu 25.04 non-LTS = NO-GO). |
| `snap`-Docker | absent | Désinstaller avant Phase 3 (installer Coolify le refuse). |

**Si un seul critère échoue → STOP**, retour au manager OVH avant de poursuivre.

---

## Phase 1 — Hardening OS

Ordre obligatoire (le SSH doit rester accessible, sinon perte d'accès).

### 1.1 Utilisateur `cc-deploy`

```sh
adduser --disabled-password --gecos "" cc-deploy
usermod -aG sudo cc-deploy
mkdir -p /home/cc-deploy/.ssh && chmod 700 /home/cc-deploy/.ssh
# coller la clé publique SSH personnelle (avec passphrase) :
nano /home/cc-deploy/.ssh/authorized_keys
chmod 600 /home/cc-deploy/.ssh/authorized_keys
chown -R cc-deploy:cc-deploy /home/cc-deploy/.ssh
```

### 1.2 Clé SSH Coolify (sans passphrase, contrainte doc Coolify)

```sh
ssh-keygen -t ed25519 -a 100 -N "" -f /root/.ssh/coolify_ed25519 -C "coolify@$(hostname)"
cat /root/.ssh/coolify_ed25519.pub >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

### 1.3 SSH durci

`/etc/ssh/sshd_config` (vérifier d'abord que ta clé est bien dans `authorized_keys`) :

```
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
ChallengeResponseAuthentication no
```

```sh
sshd -t && systemctl reload ssh
```

Tester depuis un **autre** terminal avant de fermer la session courante.

### 1.4 Firewall `ufw`

```sh
apt update && apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     # SSH
ufw allow 80/tcp     # HTTP (Let's Encrypt + redirection)
ufw allow 443/tcp    # HTTPS
ufw allow 8000/tcp   # Coolify UI (TEMPORAIRE — fermer Phase 4)
ufw allow 6001/tcp   # Coolify realtime (TEMPORAIRE)
ufw allow 6002/tcp   # Coolify terminal (TEMPORAIRE)
ufw enable
```

> **Caveat Docker** : Docker manipule directement les règles iptables (`DOCKER-USER` chain) et peut bypasser ufw pour les ports publiés via `ports:`. Dans nos compose (cc et matomo), **aucun service n'utilise `ports:`** — seul Traefik (interne Coolify) écoute sur 80/443. ufw protège donc bien les ports hôtes ; aucun service privé n'est joignable depuis Internet par construction. **Vérification systématique post-déploiement** depuis un poste local :
> ```sh
> nmap -p 5432,3306,6333,6334,6379 51.68.129.187
> # tous les ports doivent être filtered ou closed
> ```
> Si l'un répond ouvert, c'est qu'un `ports:` a été ajouté par erreur dans un compose — corriger avant tout autre travail.

### 1.5 fail2ban + auto-upgrades + swap + NTP

```sh
apt install -y fail2ban unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades

# Swap 4 Go si RAM ≤ 8 Go
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo "/swapfile none swap sw 0 0" >> /etc/fstab

timedatectl set-timezone Europe/Paris
timedatectl set-ntp true
```

---

## Phase 2 — DNS

État vérifié 2026-04-28 :
- `consciencedeclasse.com` → `51.68.129.187` ✅ déjà OK
- NS = `dns200.anycast.me`, `ns200.anycast.me` (OVH)

À ajouter dans **OVH Manager > Domaines > consciencedeclasse.com > Zone DNS** :

| Type | Sous-domaine | Cible |
|---|---|---|
| A | `coolify` | `51.68.129.187` |
| A | `www` | `51.68.129.187` |
| A | `api` | `51.68.129.187` |
| A | `analytics` | `51.68.129.187` |
| A | `*` | `51.68.129.187` |

> Le sous-domaine canonique pour Matomo est `analytics.consciencedeclasse.com` (ADR-0007). L'ancien `matomo` peut être laissé en CNAME si déjà créé, mais c'est `analytics` qui est utilisé partout (compose, snippet Astro, runbook matomo-deploy).

TTL initial 300, à passer à 3600 quand figé.

Vérifier la propagation :

```sh
dig +short coolify.consciencedeclasse.com
dig +short api.consciencedeclasse.com
dig +short anything.consciencedeclasse.com   # vérifie le wildcard
```

Toutes les sorties doivent retourner `51.68.129.187` avant Phase 3.

---

## Phase 3 — Installation Coolify

```sh
ssh root@51.68.129.187
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | sudo bash
```

Le script :
- Installe Docker Engine 24+ (refuse si snap-docker présent).
- Crée `/data/coolify/{source,ssh/keys,applications,databases,backups}`.
- Crée le réseau Docker bridge `coolify --attachable`.
- Démarre Coolify sur port 8000.

**Action humaine immédiate** (warning sécurité Coolify : « si quelqu'un d'autre arrive sur la page register avant toi, il prend le contrôle total ») :

1. Ouvrir `http://51.68.129.187:8000` **immédiatement**.
2. Créer le compte admin :
   - Email : `consciencedeclasse@proton.me`
   - Password fort (manager de mots de passe, ≥ 24 caractères).
3. Settings > Security > **Activer 2FA** sans délai.

### Pinner la version Coolify

Pour éviter qu'une auto-update casse un déploiement :

```sh
grep COOLIFY_VERSION /data/coolify/source/.env
# noter la version actuelle, ex : 4.0.0-beta.418
# laisser tel quel pour la 1re install ; figer après le 1er déploiement validé
```

---

## Phase 4 — Bind domaine + TLS UI Coolify + fermer ports

1. **Settings > Configuration > Instance Domain** : `https://coolify.consciencedeclasse.com`. Coolify émet automatiquement un Let's Encrypt via Traefik.
2. Vérifier :
   ```sh
   curl -I https://coolify.consciencedeclasse.com
   # 200 + cert Let's Encrypt valide
   ```
3. Fermer les ports devenus inutiles :
   ```sh
   ufw delete allow 8000/tcp
   ufw delete allow 6001/tcp
   ufw delete allow 6002/tcp
   ufw status numbered
   ```

---

## Phase 5 — GitHub App + projet Coolify

### 5.1 GitHub App

Coolify > **Sources > GitHub App > Create new** :
- Nom : `coolify-cc`
- Owner : `Concsience`
- Permissions : Repo Contents (Read), Metadata (Read), Webhooks, Deployments, Statuses, Pull requests (Read).
- Installer sur le repo `Concsience/class-consciousness` uniquement.

### 5.2 Projet + ressource Compose

Coolify > **Projects > + Add** :
- Nom : `class-consciousness`
- Environment : `production`

Resource > **+ New > Docker Compose Empty** :
- Source : GitHub App `coolify-cc` → `Concsience/class-consciousness`
- Branch : `main`
- Base directory : `/`
- Docker Compose location : `infra/docker-compose.prod.yml`
- Build pack : Compose (build from source)

### 5.3 Variables Coolify (Settings > Environment Variables)

Renseigner uniquement les secrets externes ; les `SERVICE_PASSWORD_*` se génèrent automatiquement à la 1re parse.

```
ANTHROPIC_API_KEY = sk-ant-...
VOYAGE_API_KEY    = ...
```

### 5.4 FQDN par service

Confirmer dans l'UI Coolify (les magic vars `SERVICE_FQDN_WEB_80` et `SERVICE_FQDN_API_8000` font le mapping ; l'UI demande de valider) :
- `web` → `https://consciencedeclasse.com`
- `api` → `https://api.consciencedeclasse.com`
- `postgres`, `qdrant`, `redis` : **pas** de FQDN (privés).

### 5.5 Premier déploiement

Bouton **Deploy**. Suivre les logs en direct dans l'UI Coolify > Deployments.

> **Si erreur de build sur `context: ..`** : Coolify peut résoudre les chemins relatifs différemment de Docker Compose pur. Fallback : déplacer `docker-compose.prod.yml` à la racine du repo, mettre `context: .` et `dockerfile: infra/Dockerfile.api`. Reconfigurer Compose location → `docker-compose.prod.yml`.

---

## Phase 6 — Vérifications fonctionnelles

Depuis un poste local :

```sh
curl -I https://consciencedeclasse.com           # 200
curl https://api.consciencedeclasse.com/health   # {"status":"ok"}
nmap -p 5432,6333,6334,6379 51.68.129.187        # tous filtered/closed
```

Coolify UI > Resources > class-consciousness :
- Tous services `Healthy`.
- Logs sans erreur après 5 min.

---

## Phase 7 — Backups

Voir `coolify-backup-restore.md` pour la procédure complète. Résumé :

1. Créer bucket S3 `cc-backups-prod` chez OVH Object Storage région `GRA`.
2. Coolify > Settings > **Storages > Add S3** → renseigner credentials + endpoint OVH.
3. Coolify > Resource class-consciousness > **Scheduled Tasks** :
   - `pg_dump_postgres` : `daily`, container `postgres`, commande `pg_dump -Fc -U cc cc | gzip > /tmp/dump.gz` puis upload S3.
   - `qdrant_snapshot` : `daily`, container `qdrant`, snapshot via API native + upload S3.
   - `coolify_instance_backup` : `daily`, host-level, tar `/data/coolify/source/.env` + `/data/coolify/ssh/keys/` + dump DB Coolify → S3.
4. Tester restore dans les **7 jours** sur VPS jetable (sinon le backup n'existe pas).

---

## Phase 8 — Ce qui reste à faire après ce runbook

Hors scope de ce runbook (à tracer en issues GitHub) :

- Migrations Alembic du schéma DB (déjà la trajectoire `apps/api/alembic/`).
- Premier ingest TEI test.
- Ajout du middleware CORS `apps/api/src/cc_api/main.py` à la 1re route consommée par le navigateur depuis `consciencedeclasse.com`.
- Build arg Astro `PUBLIC_API_URL` côté `infra/Dockerfile.web` (à ajouter dans le stage `build` au moment du 1er fetch côté client).
- Workers uvicorn multi-process (`gunicorn -k uvicorn.workers.UvicornWorker`).
- Pin de version Postgres mineure (`postgres:17.x`) avant la 1re donnée réelle.
- Uptime Kuma externe (monitoring tiers indépendant).
- ADR-0001 mention « Hetzner/Scaleway » à mettre à jour pour pointer vers ADR-0006.

---

## Cadre multi-apps (Matomo et au-delà)

Coolify gère multi-apps nativement.

1. **1 Project Coolify par app** (`class-consciousness`, `matomo`, ...).
2. **Pas de partage de DB** : Postgres class-consciousness ≠ MariaDB matomo.
3. **Sous-domaines disjoints** : `consciencedeclasse.com` (cc), `analytics.consciencedeclasse.com` (matomo), `coolify.consciencedeclasse.com` (UI).
4. **Bucket S3 séparé par projet** : `cc-backups-prod`, `matomo-backups-prod`.
5. **Surveillance pression RAM** dès le 2e projet : viser < 70 % de la RAM totale en cumul.

Pour le déploiement Matomo, voir `matomo-deploy.md` (à exécuter après que ce runbook soit complet jusqu'à Phase 6 inclus).

---

## En cas d'incident

Voir `coolify-incident.md` pour rollback, restauration, communication.

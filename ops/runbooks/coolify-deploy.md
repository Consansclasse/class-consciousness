# Déployer class-consciousness sur Coolify (OVH Cloud)

> **Quand** : première mise en ligne, ou reprovisionnement complet de l'instance publique.
> **Effet** : VPS OVH durci + Coolify installé + projet déployé en HTTPS automatique avec auto-deploy sur `git push`.
> **Durée** : ~60-90 min première fois.
> **Pré-requis** : compte OVH, domaine (chez OVH ou ailleurs), repo poussé sur GitHub.

Ce runbook est exécutable de bout en bout par une personne seule. Toute commande sensible est commentée. Les valeurs à remplacer sont en `MAJUSCULES_ENTRE_CHEVRONS` ou `<comme-ça>`.

Décisions d'architecture (voir [`docs/adr/0006-deployment-coolify-ovh.md`](../../docs/adr/0006-deployment-coolify-ovh.md)) :

- Hébergeur : **OVH Public Cloud**, région `GRA` (Gravelines, FR).
- PaaS : **Coolify** self-hosted (AGPL-compatible, pas de vendor lock-in).
- Build pack : **Docker Compose** pointant vers [`infra/docker-compose.prod.yml`](../../infra/docker-compose.prod.yml).
- TLS : Let's Encrypt automatique via Traefik intégré à Coolify.
- Bases (Postgres, Qdrant, Redis) : déclarées dans le compose pour l'instant. Migration vers ressources Coolify gérées prévue en phase 5 (backups intégrés).

## État actuel de l'instance prod (2026-04-28)

| Champ | Valeur |
|---|---|
| Domaine | `consciencedeclasse.com` |
| Serveur | OVH **Kimsufi KS-1-B** (dédié) |
| Spécs | Intel Xeon D-2123IT, 32 Go RAM ECC DDR4 2400, 2× 4 To HDD SATA Soft RAID, 500 Mbit/s unmetered |
| Région | Limburg (DE) |
| OS cible | **Ubuntu 24.04 LTS** (à choisir au moment de l'install Kimsufi) |
| IPv4 | *à recevoir à la livraison Kimsufi* |
| Statut commande | en cours |
| Statut Coolify | non installé |
| Dettes acceptées (ADR-0006) | n° 1 HDD, n° 2 pas de SLA, n° 3 backups manuels, n° 4 DC en DE |
| **VPS-3 ancien** (`51.75.73.13`) | orphelin → décision à prendre : résilier ou garder en staging |

**FQDN attribués dans Coolify :**

| Service | FQDN |
|---|---|
| `web` | `https://consciencedeclasse.com` |
| `api` | `https://api.cdc.consciencedeclasse.com` |
| `coolify` (dashboard) | `https://coolify.consciencedeclasse.com` *(activable via Annexe B)* |

**Co-hébergement sur le même VPS** (à orchestrer plus tard, hors scope du runbook initial) :
- `matomo.consciencedeclasse.com` → autre ressource Coolify à créer (web analytics interne).

---

## Étape 0 — Prérequis humains

- [ ] Compte OVH actif avec moyen de paiement validé.
- [ ] Domaine enregistré (idéalement chez OVH pour DNS unifié, sinon n'importe où).
- [ ] Clé SSH locale (`~/.ssh/id_ed25519.pub`). Sinon : `ssh-keygen -t ed25519 -C "ops@class-consciousness"`.
- [ ] Repo `Consansclasse/class-consciousness` poussé sur GitHub (sinon voir Annexe A).
- [ ] Clé API Anthropic (à mettre en secret Coolify, jamais dans le repo).
- [ ] Clé API Voyage AI (idem).

---

## Étape 1 — VPS et OS

### 1A. Provisionner OVH Public Cloud (chemin recommandé, depuis zéro)

> OVH Public Cloud (≠ OVH VPS classique). On prend une **Instance Compute** de la gamme polyvalente.

1. https://www.ovhcloud.com/fr/public-cloud/ → connexion → Espace client.
2. **Créer un projet Public Cloud** si inexistant. Nom : `class-consciousness`.
3. **Public Cloud → Instances → Créer une instance**.
4. Paramètres :
   - **Région** : `GRA9` (Gravelines) ou `SBG5` (Strasbourg). Évite les régions hors UE.
   - **Image** : `Ubuntu 24.04`. *Seul OS LTS officiellement supporté par l'auto-installeur Coolify* [VÉRIFIER avril 2026].
   - **Modèle** :
     - **Recommandé MVP plomberie phase 0+1** : `B3-8` (2 vCPU, 8 Go RAM, 50 Go SSD NVMe) — ~25 €/mois HT [VÉRIFIER tarifs 2026].
     - **Recommandé phase 3+ (RAG actif, Qdrant chargé)** : `B3-32` (8 vCPU, 32 Go RAM, 200 Go SSD NVMe) — ~80 €/mois HT.
     - **Minimum vital** : `B3-4` (1 vCPU, 4 Go RAM) — sous le minimum Coolify, à éviter.
   - **Stockage additionnel** : aucun pour l'instant.
   - **SSH key** : importer ta clé publique locale (`cat ~/.ssh/id_ed25519.pub`).
   - **Network** : « Public » (par défaut).
   - **Pare-feu** : laisser tel quel ; on durcira au pas suivant.
   - **Nom** : `cc-prod-1`.
   - **Facturation** : mensuelle (pas horaire — la machine tourne H24).
5. Lancer la création. Attendre l'IPv4 publique. Noter `<VPS_IP>`.

### 1B. OVH VPS classique déjà provisionné (chemin alternatif)

Si tu as déjà un VPS de la gamme **OVH VPS classique** (hostname `vpsXXXXXXXX.vps.ovh.net`), le runbook s'applique avec deux différences :

- L'UI de gestion est dans `Bare Metal Cloud → VPS` (pas Public Cloud).
- Le firewall n'est pas géré par OVH ; on s'appuie uniquement sur **UFW** côté OS.

Vérifier impérativement avant l'étape 2 :

- **OS = Ubuntu LTS** (20.04, 22.04, 24.04). *Si l'OS est une release intermédiaire (21.04, 23.04, 25.04…) ou EOL → réinstaller* : Espace client → Bare Metal Cloud → VPS → ton VPS → onglet **Reinstall** → choisir **Ubuntu 24.04 (Distribution)** → clé SSH → confirmer.
- **Snapshots automatiques activés** : VPS → onglet **Sauvegardes auto** → activer (~+20 % du prix). *Mitigation incendie SBG2 2021.*

### 1C. Cas dégradé : OS non-LTS et tu refuses la réinstallation

> ⚠️ **Hors-piste.** À assumer, à compenser, à corriger avant la phase 1 (corpus réel). Voir Annexe H.

### Accès SSH et passage root

```sh
ssh ubuntu@<VPS_IP>
# Premier login : passer en root pour la suite
sudo -i
```

> OVH Ubuntu : utilisateur par défaut `ubuntu`, sudoer sans mot de passe. Coolify exige du **root**. Sur OVH VPS classique, l'utilisateur peut être `debian` ou directement `root` selon ton choix à la commande/réinstallation — vérifier l'email d'OVH après provisionnement.

---

## Étape 2 — Hardening initial du serveur

Toutes ces commandes en **root** (`sudo -i`).

```sh
# 1. Mettre à jour le système
apt update && apt upgrade -y && apt autoremove -y

# 2. Installer outils de base
apt install -y ufw fail2ban unattended-upgrades curl ca-certificates htop

# 3. Activer les mises à jour de sécurité automatiques
dpkg-reconfigure -plow unattended-upgrades  # confirmer "Yes"

# 4. Swap 4 Go (utile sur les petites instances pendant les builds Docker)
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
sysctl vm.swappiness=10
echo 'vm.swappiness=10' >> /etc/sysctl.conf

# 5. Firewall UFW : SSH + HTTP/HTTPS uniquement (Coolify dashboard sera tunnellé)
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP (Let''s Encrypt + Traefik)'
ufw allow 443/tcp comment 'HTTPS (Traefik)'
# Ports Coolify : ouverts temporairement pendant l'install, fermés après
ufw allow 8000/tcp comment 'Coolify dashboard (à fermer post-setup)'
ufw allow 6001/tcp comment 'Coolify realtime (à fermer post-setup)'
ufw allow 6002/tcp comment 'Coolify terminal (à fermer post-setup)'
ufw --force enable
ufw status numbered

# 6. fail2ban : protection brute-force SSH
systemctl enable --now fail2ban
fail2ban-client status sshd

# 7. Désactiver le login root SSH par mot de passe (clé uniquement)
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart ssh

# 8. Hostname propre
hostnamectl set-hostname cc-prod-1
```

Test depuis ta machine locale (NE PAS fermer la session root actuelle avant que ce test passe) :

```sh
ssh ubuntu@<VPS_IP>           # doit marcher
ssh root@<VPS_IP>              # doit marcher uniquement avec ta clé SSH
```

---

## Étape 3 — Installer Coolify

> Toujours en **root** (`sudo -i`).

```sh
curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash
```

Le script :
- installe Docker + Docker Compose plugin si absents,
- crée le dossier `/data/coolify/`,
- télécharge l'image Coolify et démarre la stack via Docker Compose,
- expose le dashboard sur `:8000`.

Attendre la fin (2-5 min). À la fin tu vois :

```
Your instance is ready to use!
Please visit http://<VPS_IP>:8000
```

Ouvrir cette URL dans ton navigateur.

---

## Étape 4 — Configurer Coolify (compte admin, paramètres globaux)

1. **Créer le compte admin** sur l'écran d'accueil. Mail + mot de passe fort + 2FA (à activer juste après).
2. Aller dans **Profile (icône en haut à droite) → Two-Factor Auth** → activer TOTP avec ton gestionnaire de mots de passe.
3. **Settings → Instance Settings** :
   - **Instance Name** : `cc-prod-1`.
   - **Public IPv4** : confirmer `<VPS_IP>` (auto-détecté).
   - **FQDN** : laisser vide pour l'instant (on tunnellera le dashboard via SSH plutôt que l'exposer).
4. **Servers → localhost** : Coolify s'auto-déclare comme serveur. Vérifier qu'il est marqué **Reachable** et que **Cloudflare Tunnel** est désactivé (souveraineté).
5. **Sources → GitHub** : *à faire à l'étape 7* si on veut auto-deploy via GitHub App. Pour repo public, pas nécessaire.

---

## Étape 5 — Configurer le DNS

Tu vas créer **trois enregistrements A** (un par sous-domaine) chez ton registrar (OVH ou autre) :

| Sous-domaine                | Type | Cible        | Usage                                       |
|-----------------------------|------|--------------|---------------------------------------------|
| `<DOMAINE>`                 | A    | `<VPS_IP>`   | Site web (web service)                      |
| `api.<DOMAINE>`             | A    | `<VPS_IP>`   | API FastAPI                                 |
| `coolify.<DOMAINE>`         | A    | `<VPS_IP>`   | Dashboard Coolify (optionnel, voir Annexe B)|

> **Si domaine chez OVH** : Espace client → Domaines → `<DOMAINE>` → Zone DNS → **Ajouter une entrée**. TTL minimal (60s) pour les premiers tests, puis remonter à 3600s une fois stabilisé.

Vérifier la propagation (depuis ta machine locale) :

```sh
dig +short <DOMAINE>           # doit renvoyer <VPS_IP>
dig +short api.<DOMAINE>       # doit renvoyer <VPS_IP>
```

> Attendre que ça résolve avant l'étape 7, sinon Let's Encrypt échouera.

---

## Étape 6 — Pousser le repo sur GitHub (si pas déjà fait)

Si l'étape « lock-down-repo » est faite, ce point est probablement déjà ok. Sinon :

```sh
cd /home/yamamoto/class-consciousness
git remote add origin https://github.com/Consansclasse/class-consciousness.git
git branch -M main
git push -u origin main
```

> Le repo doit contenir [`infra/docker-compose.prod.yml`](../../infra/docker-compose.prod.yml) pour que Coolify puisse le trouver.

---

## Étape 7 — Créer le projet + ressource Docker Compose dans Coolify

1. **Projects → New Project** → nom `class-consciousness`. Description : « Archive marxiste open-source ».
2. Dans le projet, environment **production** est créé par défaut. Le sélectionner.
3. **+ New Resource → Public Repository** (puisque le repo est public).
   - **Repository URL** : `https://github.com/Consansclasse/class-consciousness`
   - **Branch** : `main`
   - **Build Pack** : sélectionner **Docker Compose** dans le dropdown (par défaut Nixpacks).
   - **Base Directory** : `/`
   - **Docker Compose Location** : `/infra/docker-compose.prod.yml`
   - Cliquer **Continue**.
4. Coolify analyse le compose. Tu verras les **5 services** détectés : `postgres`, `qdrant`, `redis`, `api`, `web`.
5. **Domains** :
   - Service `api` → champ **Domains** : `https://api.<DOMAINE>`
   - Service `web` → champ **Domains** : `https://<DOMAINE>`
   - Les services `postgres`, `qdrant`, `redis` : **pas de domaine** (interne uniquement).
6. **Build & Deploy → Advanced** :
   - **Auto Deploy on Git Push** : laisser activé pour l'instant.
   - **Watch Paths** : `infra/**`, `apps/**`, `packages/**`, `pyproject.toml`, `package.json`, `pnpm-lock.yaml`, `uv.lock` (évite les redéploiements pour les changements de docs/corpus seuls).
7. **NE PAS encore cliquer Deploy**. D'abord les variables d'environnement.

---

## Étape 8 — Variables d'environnement (secrets)

Dans la ressource → onglet **Environment Variables**.

### Magic vars Coolify (auto-générées, NE PAS toucher)

Ces variables sont générées automatiquement la première fois que Coolify lit le compose. Vérifier qu'elles apparaissent et sont marquées **Generated** :

- `SERVICE_PASSWORD_POSTGRES` *(mot de passe Postgres aléatoire)*
- `SERVICE_PASSWORD_QDRANT` *(API key Qdrant aléatoire)*
- `SERVICE_PASSWORD_REDIS` *(mot de passe Redis aléatoire)*
- `SERVICE_FQDN_API_8000` *(FQDN de l'API, dérivé du domaine que tu as mis)*
- `SERVICE_FQDN_WEB_80` *(FQDN du web, idem)*

> Ces secrets sont stockés chiffrés par Coolify. Pour rotation : suppression + redéploiement.

### Secrets à fournir à la main

Cliquer **+ Add** pour chacun, **Is Build Time** = non, **Is Literal** = oui :

| Variable                         | Valeur                                                                  | Source                                                  |
|----------------------------------|-------------------------------------------------------------------------|---------------------------------------------------------|
| `ANTHROPIC_API_KEY`              | `sk-ant-api03-...`                                                      | https://console.anthropic.com/settings/keys             |
| `VOYAGE_API_KEY`                 | `pa-...`                                                                | https://dash.voyageai.com/api-keys                      |
| `ARK_NAAN`                       | `99999` (placeholder dev) ou ton NAAN si attribué                       | https://n2t.net/e/pub/naan_request                      |

### Variables avec défauts (laisser vides → fallback du compose)

- `ANTHROPIC_MODEL` (défaut `claude-opus-4-7`)
- `ANTHROPIC_MODEL_PREPROCESS` (défaut `claude-haiku-4-5`)
- `VOYAGE_EMBED_MODEL` (défaut `voyage-4`)
- `VOYAGE_RERANK_MODEL` (défaut `rerank-2.5`)
- `ARK_RESOLVER` (défaut `https://n2t.net`)

---

## Étape 9 — Premier déploiement

1. Dans la ressource → bouton **Deploy** en haut à droite.
2. **Suivre les logs** : onglet **Deployments → en cours**. Tu verras :
   - `git clone` du repo,
   - `docker compose build` (api avec uv sync, web avec pnpm install),
   - `docker compose up`,
   - démarrage healthchecks.
3. Premier build : ~5-10 min (téléchargement des images de base + dépendances).
4. À la fin : statut **Healthy** sur les 5 services.

Test depuis ta machine locale :

```sh
curl -s https://api.<DOMAINE>/health
# attendu : {"status":"ok"}

curl -sI https://<DOMAINE>
# attendu : HTTP/2 200 (page Astro stub)
```

Si Let's Encrypt échoue (cert pas émis), vérifier :
- DNS bien propagé (`dig +short`),
- Port 80 ouvert sur UFW (`ufw status`),
- Logs Traefik dans Coolify : **Servers → localhost → Proxy → Logs**.

---

## Étape 10 — Verrouiller l'accès au dashboard Coolify

Maintenant que tout fonctionne, **fermer les ports 8000/6001/6002** sur le firewall — l'accès au dashboard se fera désormais par tunnel SSH.

```sh
# Sur le serveur, en root
ufw delete allow 8000/tcp
ufw delete allow 6001/tcp
ufw delete allow 6002/tcp
ufw status
```

Pour accéder au dashboard ensuite, depuis ta machine locale :

```sh
ssh -L 8000:localhost:8000 -L 6001:localhost:6001 -L 6002:localhost:6002 root@<VPS_IP>
# puis ouvrir http://localhost:8000
```

> **Alternative** (Annexe B) : exposer le dashboard sous `https://coolify.<DOMAINE>` avec basic auth Traefik. Plus pratique mais surface d'attaque ↑.

---

## Étape 11 — Activer l'auto-deploy sur push

Si le repo est public, l'auto-deploy fonctionne déjà via polling Coolify (toutes les minutes). Pour basculer sur **webhook GitHub** (instantané) :

1. Coolify → **Sources → New → GitHub App**.
2. Suivre l'assistant : Coolify génère un manifest, redirige vers GitHub pour créer l'App, l'installer sur ton org `Consansclasse` avec accès au seul repo `class-consciousness`.
3. Permissions demandées : `contents: read`, `metadata: read`, `pull_requests: write`, `webhooks: write`.
4. Une fois l'App installée, retourner dans la ressource → **Source** → switch sur la GitHub App.
5. Tester : `git commit --allow-empty -m "test webhook" && git push`. Coolify doit déclencher un déploiement immédiat.

---

## Annexe A — Pousser un repo local sur GitHub la première fois

```sh
cd /home/yamamoto/class-consciousness
gh repo create Consansclasse/class-consciousness --public --source=. --remote=origin --push
# OU manuellement :
git remote add origin git@github.com:Consansclasse/class-consciousness.git
git branch -M main
git push -u origin main
```

---

## Annexe B — Exposer le dashboard Coolify sur un sous-domaine

> Attention : surface d'attaque ↑. Ne le faire que si la 2FA est active et le mot de passe admin est fort.

1. **Settings → Instance Settings → Instance's Domain (FQDN)** : `https://coolify.<DOMAINE>`.
2. Coolify reconfigure Traefik et émet un cert Let's Encrypt.
3. Tu peux alors fermer les ports 8000/6001/6002 sur UFW (déjà fait à l'étape 10).
4. Optionnel : ajouter une **liste blanche d'IP** dans **Settings → Allowed IPs** si IP fixe.

---

## Annexe C — Backups

### Volumes (postgres_data, qdrant_data, redis_data)

Coolify ne fait **pas** de backup automatique des volumes Docker. Trois options :

1. **Backups OVH au niveau VM** : OVH Public Cloud → Snapshots manuels ou automatisés (~10 €/mois). *Capture tout, mais granularité = la VM entière.*
2. **Backups Coolify managés (Postgres uniquement)** : nécessite de migrer Postgres hors compose, vers un **Database Resource** Coolify dédié. Voir phase 5 hardening.
3. **Cron + restic vers stockage Object OVH** : voir `ops/runbooks/backup-restic.md` *(à écrire en phase 5)*.

### Code et corpus

Le repo Git est la source de vérité. Le corpus est versionné en TEI dans `corpus/`. Pas de backup spécifique côté serveur — le serveur est *cattle*, reprovisionnable depuis le repo.

---

## Annexe D — Mise à jour de Coolify

Coolify s'autoupgrade par défaut. Pour forcer manuellement :

```sh
# en root sur le serveur
curl -fsSL https://cdn.coollabs.io/coolify/upgrade.sh | bash
```

Vérifier la version dans **Settings → Instance Settings → Version**.

---

## Annexe E — Rollback d'un déploiement

Coolify garde l'historique des déploiements. Dans la ressource → onglet **Deployments** → trouver un déploiement réussi antérieur → bouton **Redeploy**. Coolify rebuilde au commit correspondant et bascule.

Si la base Postgres est dans un état incompatible avec l'ancien code (migration appliquée, code rollbacké) → restore d'un snapshot OVH. *La discipline d'Alembic doit interdire les migrations destructives non-réversibles.*

---

## Annexe F — Logs et monitoring

- **Logs applicatifs** : ressource → onglet **Logs** → choisir le service → tail temps réel.
- **Logs Traefik** : **Servers → localhost → Proxy → Logs**.
- **Logs Coolify lui-même** : `docker logs coolify -f` sur le serveur.
- **Stack Prometheus/Grafana du repo** : *non déployée pour l'instant*. À intégrer en phase 5 (déclarer dans `docker-compose.prod.yml` ou en ressource Coolify séparée).

---

## Annexe H — Install Coolify sur Ubuntu non-LTS (chemin dégradé)

> Utilisé uniquement quand l'OS du VPS n'est pas une LTS supportée par l'auto-installeur. **À éliminer avant la phase 1.**

L'auto-installeur officiel Coolify refuse les distros non listées (`Ubuntu LTS 20.04/22.04/24.04`). Si tu es sur Ubuntu 25.04 (par ex.), trois options :

### Option H1 — Installer Docker manuellement, puis Coolify

```sh
# en root
apt update
apt install -y curl ca-certificates

# Docker via repo officiel Docker (compatible Ubuntu non-LTS)
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Test
docker run --rm hello-world

# Coolify : forcer l'install même si l'OS n'est pas reconnu
curl -fsSL https://cdn.coollabs.io/coolify/install.sh -o /tmp/coolify-install.sh
# Lire le script avant d'exécuter (principe d'audit)
less /tmp/coolify-install.sh
bash /tmp/coolify-install.sh
```

> Le script Coolify a un check OS au début. Si tu es sur 25.04 (Plucky), il peut sortir avec un message d'erreur. Workaround : `sed -i 's/^OS_TYPE=.*/OS_TYPE="ubuntu"/' /tmp/coolify-install.sh` *(force)*. À tes risques — tu sors du cadre supporté.

### Option H2 — Container Coolify lancé manuellement

Lancer Coolify via Docker Compose en bypassant l'installeur. Documenté ici : https://github.com/coollabsio/coolify/blob/main/docker-compose.yml *(la stack est ~5 services : Coolify backend, db, redis, soketi, queue)*. **Plus risqué** car tu prends à ta charge upgrades, secrets, network, etc.

### Option H3 — Réinstaller le VPS en 24.04 LTS *(recommandé)*

5 minutes, garantit le support. Voir étape 1B.

**Engagement à acter** : si tu choisis H1 ou H2, ouvre une issue GitHub avec étiquette `tech-debt` :  
`> Réinstaller le VPS en Ubuntu LTS avant le démarrage de la phase 1 (corpus réel).`

---

## Annexe G — Désactiver Coolify proprement

Si tu veux migrer ailleurs ou tout détruire :

```sh
# sur le serveur, en root
cd /data/coolify/source
docker compose down -v          # arrête + supprime les volumes Coolify
rm -rf /data/coolify
```

Puis détruire l'instance OVH depuis l'espace client.

# Incident class-consciousness — playbook

> **Quand** : un déploiement casse la prod, une intrusion est suspectée, un service bloque, le VPS ne répond plus.
> **Principe** : restaurer le service d'abord, comprendre ensuite. La cause-racine n'est jamais bloquante pour le rollback.

## 0. Triage en moins de 5 minutes

| Symptôme | Action immédiate |
|---|---|
| `https://consciencedeclasse.com` 5xx | Section 1 — rollback dernier déploiement. |
| `https://api.consciencedeclasse.com/health` timeout | Section 1, puis Section 3 si rollback ne suffit pas. |
| Coolify UI inaccessible (`https://coolify.consciencedeclasse.com`) | Section 4 — Coolify down. |
| VPS ne répond plus en SSH | Section 5 — VPS down. |
| Trafic anormal, comportement inhabituel | Section 6 — intrusion suspectée. |
| Disque plein | Section 7 — saturation disque. |

Toujours **noter l'heure UTC** au moment du triage. Démarrer le timer.

---

## 1. Rollback déploiement (cas le plus fréquent)

Coolify garde l'historique des déploiements.

1. Coolify > Resource `class-consciousness` > **Deployments**.
2. Trouver le dernier déploiement vert avant le rouge.
3. Bouton **Redeploy** sur le commit vert.
4. Attendre le passage en `Running` + `Healthy` sur tous les services (typiquement < 3 min).

Vérification post-rollback :
```sh
curl -I https://consciencedeclasse.com
curl https://api.consciencedeclasse.com/health
```

Si `Healthy`, ouvrir une issue post-mortem avec l'ID du commit fautif et passer en analyse à froid.

---

## 2. Un seul service en erreur (postgres / qdrant / redis / api / web)

### 2.1 Restart ciblé

Coolify > Resource > service > **Restart**. C'est rarement la solution mais souvent le triage le plus rapide.

### 2.2 Logs

Coolify UI > service > **Logs** (ou via SSH host) :
```sh
docker logs --tail 200 -f <CID>
```

Indices fréquents :
- Postgres `FATAL: password authentication failed` → `SERVICE_PASSWORD_POSTGRES` désynchronisé entre containers. Coolify > Settings > regénérer le secret + redeploy.
- Qdrant `unable to bind` → conflit de port (rare en réseau Coolify). Vérifier qu'aucun `ports:` n'a été ajouté par erreur dans le compose.
- API `OperationalError` au démarrage → DB pas encore healthy ; vérifier `depends_on` + `healthcheck` postgres.
- Web nginx `connect() failed (111: Connection refused)` upstream `api` → API DOWN, traiter d'abord côté api.

### 2.3 Restore d'un volume

Si la corruption est confirmée (ex : Postgres corrompu après crash) :
1. Stopper la ressource Coolify.
2. Suivre `coolify-backup-restore.md` Couche 2 (restauration `pg_restore`) ou Couche 3 (`restic restore`).
3. Redéployer.

---

## 3. Migration applicative cassée

Symptôme typique : nouveau commit `main` qui échoue les migrations Alembic, l'API ne démarre pas.

1. Rollback (Section 1).
2. Forcer la version du repo en local : `git revert <SHA>` ou `git checkout <SHA_PRECEDENT>`, push.
3. Coolify auto-redeploy sur le push de `main`.
4. Analyser la migration cassée hors-prod.

> **Ne jamais** débugger une migration cassée en prod.

---

## 4. Coolify UI down

Le service Coolify lui-même peut planter sans toucher aux apps déployées (Traefik continue souvent à servir).

1. SSH sur le VPS :
   ```sh
   cd /data/coolify/source
   docker compose ps
   docker compose logs -f --tail 100
   ```
2. Si `coolify` ou `coolify-db` est `Exited` :
   ```sh
   docker compose up -d
   ```
3. Si la DB Coolify est corrompue : suivre `coolify-backup-restore.md` Couche 1.
4. Pendant que Coolify est down, les apps continuent de tourner (Traefik est un container séparé). Ne pas paniquer.

---

## 5. VPS injoignable

1. Vérifier depuis un autre réseau (4G, autre VPN). Une coupure FAI locale ressemble à un VPS down.
2. OVH Manager > VPS > **Statut** : panne datacenter ou VPS arrêté ?
3. OVH Manager > VPS > **Console KVM/IPMI** : se connecter pour diagnostic réseau / fsck si OS planté.
4. Si OS irrécupérable : déclencher la procédure DR
   1. Re-provisionner un VPS de mêmes specs.
   2. Pointer DNS sur le nouveau IP (TTL 300 = max 5 min de propagation).
   3. Restaurer Coolify (Couche 1) puis les apps (Couche 2).

> Le DNS root (`consciencedeclasse.com`) est déjà chez OVH ; modifier l'A record est immédiat depuis OVH Manager.

---

## 6. Intrusion suspectée

> **Principe** : isoler avant d'analyser.

1. **Couper l'accès public** : `ufw deny 80/tcp; ufw deny 443/tcp` (laisse SSH ouvert pour l'analyse).
2. **Snapshot full-disk OVH** depuis le manager (preuve forensique).
3. Vérifier :
   - `last -a` (logins récents)
   - `ss -tnp` (connexions actives)
   - `journalctl -u ssh --since "24 hours ago"`
   - `docker ps -a` (containers inattendus)
   - `ls -la /data/coolify/source/.env` (modifié ?)
   - Logs Coolify (Settings > Audit logs)
4. **Rotation totale** des secrets :
   - Anthropic API key (console.anthropic.com > Revoke + new).
   - Voyage API key.
   - SSH keys (toutes les `authorized_keys` à régénérer).
   - `APP_KEY` Coolify (procédure `coolify-backup-restore.md` Couche 1 avec `APP_PREVIOUS_KEYS`).
   - Tous les `SERVICE_PASSWORD_*` (regénérer dans Coolify UI puis redeploy).
5. Si compromission confirmée : **rebuild from scratch** sur un nouveau VPS, restauration depuis backup vérifié non compromis (avant l'horodatage de l'intrusion).
6. Notification publique sur `https://consciencedeclasse.com/security` dans les 72h (engagement `SECURITY.md` du projet).

---

## 7. Saturation disque

```sh
df -h
docker system df
docker system prune -a --volumes   # ⚠ supprime images + containers inutilisés ; ne touche PAS aux volumes nommés du compose
```

Si toujours plein :
- `find /data/coolify/applications -type f -name "*.tar.gz" -mtime +30 -delete` (anciens artifacts de build).
- Examiner les volumes : `du -sh /var/lib/docker/volumes/*` — Qdrant grossit avec le corpus, ce n'est pas une fuite.
- En dernier recours : agrandir le disque OVH (Public Cloud → resize ; VPS → upgrade plan).

---

## Communication incident

- **Bandeau site** : ajouter une `<div role="alert">` dans `apps/web` via un commit éphémère sur `main` (Coolify auto-deploy).
- **Page status** : pas encore en place ; à ajouter `https://status.consciencedeclasse.com` (Uptime Kuma) phase 2 du roadmap.
- **Réseaux** : pas encore en place ; à définir avec le projet (Mastodon ? mailing list ?).
- **Post-mortem** : ouvrir une issue GitHub `incident: <date> <résumé>` avec timeline UTC, cause-racine, actions correctives. Public sauf si données personnelles concernées.

---

## Toujours, après un incident

1. Vérifier que le drill backup mensuel est à jour ; sinon le faire dans la semaine.
2. Mettre à jour ce runbook si le cas n'était pas couvert.
3. Si le rollback a fonctionné mais qu'on a frôlé la perte de données : revoir la couche backup correspondante et serrer le rythme.

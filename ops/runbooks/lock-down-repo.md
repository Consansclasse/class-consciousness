# Verrouiller le dépôt — phase mainteneur unique

> **Quand** : phase 0-1, tant que tu es seul·e mainteneur·euse et veux que personne d'autre ne puisse écrire sur `main`.
> **Effet** : empêche tout push direct par un tiers, exige la CI verte, interdit le force-push et la suppression, active toutes les protections sécu de GitHub.

## Étape 1 — créer un fine-grained PAT

1. https://github.com/settings/personal-access-tokens/new
2. **Resource owner** : `Consansclasse`
3. **Repository access** : *Only select repositories* → cocher `class-consciousness`
4. **Permissions** :
   - Administration : **Read and write**
   - Contents : **Read-only**
   - Metadata : **Read-only**
5. Expiration : 30 jours (renouvelable)
6. Générer, copier le token (commence par `github_pat_…`)

## Étape 2 — exécuter le script

```sh
cd /home/yamamoto/class-consciousness
GITHUB_TOKEN=github_pat_xxxxxxxxxxxx ./ops/scripts/lock-down-repo.sh
```

Le script :
- pose la branch protection sur `main` (pas de force-push, pas de deletion, linear history, CI required)
- active Dependabot alerts + automated fixes
- active secret scanning + push protection
- désactive wiki et projects, active discussions
- impose squash/rebase merge (pas de merge commits) et delete-on-merge

## Étape 3 — quand tu auras une clé de signature (GPG ou SSH)

Activer la signature obligatoire en plus :

```sh
GITHUB_TOKEN=github_pat_xxxxxxxxxxxx ./ops/scripts/lock-down-repo.sh --with-signed-commits
```

Pré-requis (à faire une seule fois) :

- **GPG** : générer une clé, l'ajouter à GitHub (Settings → SSH and GPG keys), configurer git :
  ```sh
  git config --global user.signingkey <KEY_ID>
  git config --global commit.gpgsign true
  git config --global tag.gpgsign true
  ```
- **ou SSH (plus simple)** : ajouter la clé SSH déjà utilisée pour pousser comme *signing key* dans GitHub, puis :
  ```sh
  git config --global gpg.format ssh
  git config --global user.signingkey ~/.ssh/id_ed25519.pub
  git config --global commit.gpgsign true
  ```

Tester : `git commit --allow-empty -S -m "test signature"` puis `git log --show-signature -1`.

## Étape 4 — vérifier dans l'UI

- https://github.com/Consansclasse/class-consciousness/settings/branches → règle sur `main` visible
- https://github.com/Consansclasse/class-consciousness/settings/security_analysis → Dependabot vert, secret scanning vert
- https://github.com/Consansclasse/class-consciousness/settings → Pull Requests : « Allow squash merging » + « Allow rebase merging » cochés ; « Allow merge commits » décoché ; « Automatically delete head branches » coché

## Étape 5 — révoquer le PAT

Une fois le verrouillage appliqué, révoquer le token : Settings → Personal access tokens → Revoke. Tu pourras en regénérer un autre quand tu voudras réajuster.

## En cas de besoin de retirer une protection ponctuellement

```sh
curl -fsS -X DELETE \
  -H "Authorization: Bearer $GITHUB_TOKEN" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Consansclasse/class-consciousness/branches/main/protection
```

À refaire suivre du script complet dès que terminé.

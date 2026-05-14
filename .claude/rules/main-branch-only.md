# Règle dure — Branche `main` uniquement

S'applique à : toute opération git dans ce repo.

## Règle

**JAMAIS** de feature branches, de PR, de release branches, ni de worktrees. Tout va directement sur `main`.

## Pourquoi

Décision verrouillée par l'utilisateur. Mainline development pur. Réduit la friction, garde l'historique linéaire, force des commits petits et déployables.

## Comment l'appliquer

- Ne JAMAIS lancer `git checkout -b ...`, `git branch ...`, `git switch -c ...`.
- Ne JAMAIS lancer `gh pr create`.
- Si un outil propose de créer une branche, refuser et utiliser `main`.
- Les hooks Claude Code peuvent vérifier `git branch --show-current` = `main` et alerter sinon.

## Note sur les commits

Les commits sont **manuels** : voir `[[feedback_no_unsolicited_commits]]`. Les hooks Claude Code peuvent lancer des checks (lint, tests) mais ne créent **jamais** de commit.

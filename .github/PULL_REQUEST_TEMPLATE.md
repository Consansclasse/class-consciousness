## Intention

<!-- Une PR = une intention. Décrivez précisément ce que cette PR change et pourquoi. -->

## Type

- [ ] Code
- [ ] Corpus (TEI + métadonnées)
- [ ] Documentation / ADR
- [ ] Infrastructure / CI
- [ ] Sécurité

## Vérifications obligatoires

- [ ] Tests ajoutés/mis à jour pour le comportement modifié
- [ ] `make lint` et `make typecheck` passent localement
- [ ] Conventional Commits respectés
- [ ] `Signed-off-by:` présent (DCO) — `git commit -s`
- [ ] Si nouvelle dépendance : justification dans le commit ou ADR
- [ ] Si endpoint RAG touché : eval RAG passée
- [ ] Si migration Alembic : `downgrade` symétrique testé

## Discipline de code (auto-vérification)

- [ ] Pas d'abstraction prématurée (interface seulement à 2+ implémentations)
- [ ] Pas de helper à un seul appelant
- [ ] Pas de validation défensive interne
- [ ] Pas de commentaire `# what` (uniquement *pourquoi* non-évident)
- [ ] Pas de TODO sans issue
- [ ] Pas de `print()` ni de log debug en prod

## Liens

<!-- Closes #123, related ADR, etc. -->

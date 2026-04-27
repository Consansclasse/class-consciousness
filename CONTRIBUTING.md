# Contribuer à class-consciousness

Merci de votre intérêt. Ce projet vise une rigueur académique au standard des humanités numériques, avec discipline de code stricte. Lisez ce document **avant** d'ouvrir une PR.

## Avant de commencer

1. Lisez [`README.md`](./README.md), [`GOVERNANCE.md`](./GOVERNANCE.md), [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md).
2. Pour une feature non triviale, **ouvrez une issue d'abord**. Pour les fixes, allez direct.
3. Toute PR doit inclure : tests, changelog (Changesets), `Signed-off-by:` (DCO).

## Types de contributions

### Code

- Suivez la **discipline de code** ci-dessous. Le merge est bloqué sinon.
- Tests : `pytest` (back), `vitest` + `playwright` (front). Couverture cible 80 %+. Pour le RAG, **pas de mock du LLM** — utilisez les cassettes VCR.
- Conventional Commits (`feat:`, `fix:`, `docs:`, etc.). Linéaire, signed.
- Une PR = une intention. Pas de bundle de changements hétérogènes.

### Corpus

Pour ajouter un texte, ouvrez une PR avec :

```
corpus/<auteur-slug>/<œuvre-slug>/
├── _work.csl.json                   # métadonnées CSL-JSON (titre, auteur, année, source, traducteur, licence)
├── editions/
│   └── <éditeur>-<année>.tei.xml    # TEI P5 valide contre cc.odd
└── facsimiles/                      # optionnel : IIIF manifests
```

Critères acceptation :
- TEI valide (`xmllint` contre `packages/tei-schema/cc.rng`)
- Licence claire et compatible (PD, CC, ou autorisation explicite — référencer la preuve dans la PR)
- Métadonnées complètes (CSL + traducteur + sources)
- Texte vérifié contre l'édition source (≥ 1 relecture humaine)
- Validé par 1 mainteneur avant merge

### Commentaires

Les commentaires sont **signés et obligatoirement sourcés** (≥ 1 chunk_ark cité). Ils sont publiés via l'interface web après vérification du compte ; pas via PR sauf cas exceptionnel.

### Bug / feature

Utilisez les templates GitHub. Soyez précis : reproduction, environnement, comportement attendu vs observé.

### Vulnérabilité de sécurité

**Ne pas ouvrir d'issue publique.** Voir [`SECURITY.md`](./SECURITY.md).

## Discipline de code (règles dures)

Cf. principe 7 du projet et plan §13bis. Violations bloquent le merge.

1. Pas d'abstraction prématurée. Une interface (`Protocol`/ABC) seulement à la 2e implémentation concrète.
2. Une fonction = un objet. Pas de classe à une seule méthode publique.
3. Pas de DTO redondant. Schemas Pydantic API ne dupliquent que ce qui est exposé.
4. Pas de validation défensive interne. Validation aux frontières seulement.
5. Pas de try/except décoratif.
6. Pas de commentaire `# what`. Noms portent le sens. Commentaires : invariant non-évident, lien issue/ADR, workaround documenté.
7. Pas de docstring vide ni paraphrasante. Uniquement pour fonctions exposées (router/CLI), ≤ 3 lignes.
8. Pas de helper à un seul appelant.
9. Pas de configuration optionnelle inutilisée.
10. Pas de fichier `utils.py` fourre-tout.
11. Pas de `print()` en prod. Logs structurés JSON.
12. Pas de dépendance ajoutée sans ADR ou justification dans le commit.
13. Pas de TODO sans issue (`# TODO(#123): …`).
14. Pas de code mort (`vulture` + `knip` en CI).
15. Tests = comportement, pas implémentation.
16. Aucun mock du LLM en intégration.
17. Imports triés, pas de circularité.
18. Lignes max 100 chars (Python), 120 (TS).
19. `mypy --strict`, `tsc --strict`. Zéro `Any`/`any` non commenté.
20. Toute migration Alembic est revertable (downgrade symétrique).

## Workflow de PR

1. Forker, créer une branche `feat/...` ou `fix/...`.
2. Coder. Tester localement (`make test`).
3. Pre-commit hooks tournent automatiquement.
4. `git commit -s` (ajoute `Signed-off-by:`).
5. Pousser, ouvrir PR vers `main`.
6. CI doit passer : lint, types, tests, build, eval RAG (si endpoint touché).
7. Review par 1 mainteneur. Lazy consensus 72 h sur PRs simples.
8. Merge en linear history.

## DCO (Developer Certificate of Origin)

Chaque commit doit inclure `Signed-off-by: Prénom Nom <email>` (`git commit -s`). En signant, vous certifiez les termes du [DCO 1.1](https://developercertificate.org/).

## Setup local

```sh
# Pré-requis : Python 3.12, Node 20, pnpm 9, uv, Docker, pre-commit
uv sync
pnpm install
pre-commit install
docker compose -f infra/docker-compose.yml up -d
make migrate
make seed
make dev
```

## Questions ?

- Discussions GitHub pour les questions techniques
- Email mainteneurs : `maintainers@class-consciousness.org` *(à activer en phase 0)*

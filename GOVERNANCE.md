# Gouvernance

Document vivant. Mis à jour par PR avec lazy consensus 72 h. Les changements touchant la succession ou les engagements de permanence requièrent unanimité du conseil des mainteneurs.

## Principes

1. **Pluralisme et transparence.** Le projet n'incarne pas une tendance unique du marxisme. Les choix éditoriaux (corpus inclus, taxonomie SKOS) sont discutés publiquement et tracés en ADR.
2. **Permanence.** Les engagements de stabilité (ARK pérennes, URLs canoniques, signatures Sigstore) tiennent indépendamment des changements d'équipe.
3. **Lazy consensus.** La plupart des décisions techniques se font par PR + 72 h sans objection. Les désaccords sont résolus par discussion, ADR si besoin, vote en dernier ressort.
4. **Transparence financière.** Comptes via OpenCollective, publics.

## Évolution du modèle

| Phase | Modèle | Critère de bascule |
|---|---|---|
| 0–1 (an 0–1) | BDFL bienveillant (mainteneur initial) | jusqu'à 3 contributeur·rice·s régulier·ère·s |
| 2 (an 1–3) | Conseil de mainteneurs (3–5 membres), lazy consensus, ADR pour désaccords | dépendant de la croissance |
| 3 (an 3+) | Hébergement par fondation (Software Freedom Conservancy, OpenCollective Foundation Europe, ou structure dédiée) | pérennisation légale |

## Rôles

- **Mainteneur** : merge PRs, gère releases, signe avec sa clé incluse dans le quorum. Critères : ≥ 6 mois de contribution régulière, accord du conseil.
- **Contributeur** : ouvre PRs et issues. Pas d'élection, simple participation.
- **Steward (intendance)** : responsable d'un domaine (corpus, RAG, infra, gouvernance). Élu·e parmi les mainteneurs.

## Processus de décision

1. **Décision technique simple** (PR de code) : merge après 1 review + CI verte + 72 h sans objection.
2. **Décision architecturale** (nouveau composant, nouveau standard, retournement de choix) : ADR (`docs/adr/`) + 7 jours de discussion + lazy consensus.
3. **Décision éditoriale** (corpus, taxonomie, ligne éditoriale) : discussion publique en issue + ADR + vote du conseil si pas de consensus.
4. **Décision de gouvernance** (ce document, succession, finances) : unanimité du conseil + transparence publique.

## Quorum et signatures

- Releases corpus : signature M-of-N (M = ⌈N/2⌉ avec N = nombre de mainteneurs actifs)
- Clés Sigstore (cosign) : par défaut OIDC keyless via GitHub Actions ; clés long-lived hors-ligne pour disaster recovery
- Domaine et hébergeur : ≥ 2 mainteneurs ont chaque accès

## Code de conduite

Voir [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md). Application par le conseil ; rotation annuelle d'un·e responsable conduite.

## Engagement de permanence

Le projet s'engage publiquement, à compter de la première release v0.1.0 :

- **Tout ARK émis reste résolvable pendant au moins 30 ans.**
- En cas de cessation, les mainteneurs transfèrent la base ARK à n2t.net ou à un partenaire académique (DARIAH-FR, BnF, BNB, ABES).
- Le code reste sur Software Heritage (auto-archivé). Le corpus reste sur Internet Archive + IPFS.
- En cas de retrait juridique d'une œuvre (DMCA, droit d'auteur), la page reste avec mention « retiré le YYYY-MM-DD pour raison X » ; le texte est masqué, l'ARK et les métadonnées restent.

## Bus factor

- Document privé `bus-factor.md` chiffré, escrow chez tiers de confiance (avocat ou hôte fiscal OpenCollective)
- Au moins 2 personnes ont chaque accès critique à tout moment
- Test de succession annuel (drill simulant le retrait d'un mainteneur)

## Gestion des conflits

1. Discussion publique sur l'issue concernée
2. Médiation par un·e mainteneur tiers
3. ADR pour figer la décision
4. Vote du conseil (majorité simple) si lazy consensus échoue
5. En cas de blocage persistant : RFC publique, période de commentaire 30 jours, vote final

## Modifications

Ce document évolue par PR. Les modifications substantielles (succession, quorum, engagement permanence) requièrent unanimité du conseil des mainteneurs.

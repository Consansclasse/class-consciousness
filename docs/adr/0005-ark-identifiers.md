# ADR-0005 — ARK comme identifiants pérennes primaires

- **Statut** : accepté
- **Date** : 2026-04-27

## Contexte

Le projet s'engage publiquement (cf. `GOVERNANCE.md`) à ce que toute citation produite reste résolvable pendant ≥ 30 ans. Cela exige un schéma d'identifiants indépendant de toute autorité commerciale, indépendant de l'hébergement actuel, gratuit, et reconnu par la communauté académique.

## Décision

**ARK** (Archive Resource Key) comme identifiant primaire pérenne.

- Demande d'attribution d'un **NAAN** (Name Assigning Authority Number) auprès de **n2t.net** (gratuit, indépendant, géré par CDLib/N2T).
- Format : `ark:/NAAN/cc-<auteur>-<œuvre>-<édition>-§<paragraphe>`
- Exemple : `ark:/12345/cc-mrx-cap1-ed72-§42`
- Identifiant qualifié par version corpus optionnel : `ark:/12345/cc-mrx-cap1-ed72-§42@v1.2.0`

Pour chaque entité du modèle de données, un ARK distinct est attribué :
- `authors.ark` — `ark:/NAAN/cc-<auteur>`
- `works.ark` — `ark:/NAAN/cc-<auteur>-<œuvre>`
- `expressions.ark` — `ark:/NAAN/cc-<auteur>-<œuvre>-<lang>`
- `manifestations.ark` — `ark:/NAAN/cc-<auteur>-<œuvre>-<édition>`
- `documents.ark`, `sections.ark`, `chunks.ark` — qualifiés
- `concepts.ark` — `ark:/NAAN/cc-concept-<slug>`
- `corpus_releases` — manifest signé Sigstore qualifie chaque ARK avec une version

**Identifiants secondaires** (non pérennes, pour interop) :
- **CTS URN** pour interop DH (Scaife/Capitains) : `urn:cts:fr.cc:marx.capital.fr-edSociales1972:1.4.42`
- **Wikidata QID** pour autorités externes
- **VIAF** + **IdRef** + **BnF.fr** pour bibliothèques

**URLs canoniques** :
- Résolveur ARK interne : `/ark/<NAAN>/<name>` → redirige vers la ressource canonique
- URLs lisibles : `/œuvre/<slug>/édition/<éd>/livre-<n>/section-<n>/chapitre-<n>/§<n>`
- Chaque page de lecture inclut `<link rel="canonical">` vers l'ARK

## Engagements de permanence

1. **Tout ARK émis reste résolvable pendant au moins 30 ans.**
2. En cas de cessation, transfert de la base ARK à n2t.net ou partenaire académique (DARIAH-FR, BnF, ABES).
3. En cas de retrait juridique d'une œuvre, la page reste avec mention « retiré le YYYY-MM-DD » ; texte masqué, ARK et métadonnées préservés.
4. Modification d'un texte (correction, ré-OCR) → nouveau release qualifie l'ARK avec version, l'ancien reste résolvable.

## Conséquences

Bénéfices :
- Standard reconnu (BnF, CDLib, communauté DH)
- Gratuit et indépendant
- Compatible avec exigences de citations académiques (les chercheurs peuvent citer un ARK dans une thèse sans craindre lien mort)

Coûts :
- Procédure d'obtention NAAN à initier en phase 0 (~quelques jours)
- Maintenance du résolveur interne et synchronisation avec n2t.net
- Discipline d'équipe pour ne jamais réémettre un ARK sur une autre ressource

## Alternatives rejetées

- **DOI (DataCite)** : adhésion ~1500 €/an ou parrainage CCSD/HAL ; reportable v2 si financement académique
- **Handle.net** : technique mais gestion complexe pour gain marginal vs ARK
- **PURL** (Persistent URL) : moins normé, déprécié par OCLC
- **URN:NBN** : intéressant pour bibliothèques nationales mais procédure pays-spécifique
- **W3ID** : OK pour identité, mais résolveur W3C moins suivi que n2t.net pour archives

## Procédure d'obtention NAAN

1. Compléter le formulaire `https://goo.gl/forms/bmckLSPpbzpZ5dix1` (ou successeur officiel — [VÉRIFIER URL actuelle])
2. Fournir : nom de l'organisation, contact, intention de stabilité, durée prévue
3. Délai : généralement quelques jours
4. Une fois NAAN reçu, configurer dans `.env` (`ARK_NAAN`) et déclarer le résolveur auprès de n2t.net

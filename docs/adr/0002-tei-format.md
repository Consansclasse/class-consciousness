# ADR-0002 — TEI P5 comme format pivot du corpus

- **Statut** : accepté
- **Date** : 2026-04-27

## Contexte

Le corpus doit être stocké dans un format qui (a) supporte annotations, variantes textuelles, métadonnées riches, (b) est lisible dans 30 ans, (c) interopère avec la communauté digital humanities, (d) permet l'export vers formats secondaires (HTML, ePub, plain text, JSON pour embeddings).

## Décision

Format pivot : **TEI P5** (Text Encoding Initiative, Proposition 5), avec un sous-ensemble strict documenté dans un ODD custom `packages/tei-schema/cc.odd`. Génération RNG/XSD à partir de l'ODD pour validation.

Éléments engagés :
- `<teiHeader>` complet avec `<fileDesc>` (titleStmt, publicationStmt, sourceDesc), `<encodingDesc>`, `<profileDesc>` (langues), `<revisionDesc>` (changelog par version)
- Structure : `<text><body><div type="part|chapter|section">`, paragraphes `<p>` numérotés `@n`
- Notes : `<note>` typées (auteur, traducteur, éditeur)
- **Apparatus criticus** : `<app><lem wit="…"><rdg wit="…"/></app>` pour les variantes (MS, drafts, éditions Engels, MEGA²)
- Pagination : `<pb n="…" ed="…"/>` avec attribut édition pour gérer plusieurs paginations
- Liens internes : `@xml:id` sur tout élément citable, ARK généré à partir
- Métadonnées tierces : `<idno type="ark|wikidata|viaf|cts">` pour autorités

Stockage : un fichier `.tei.xml` par édition (manifestation IFLA-LRM), dans `corpus/<auteur-slug>/<œuvre-slug>/editions/<éd>.tei.xml`.

Validation : `xmllint` contre RNG généré, en pre-commit + CI. Validation supplémentaire pylint-style pour conventions (présence header complet, IDs uniques, ARKs valides).

## Conséquences

Bénéfices :
- Standard durable, communauté DH active
- Apparatus criticus permet rigueur philologique pour MEGA²-style
- Inter-opère avec Scaife, Capitains, TEI Publisher si besoin
- Génération facile vers HTML/ePub/JSON

Coûts :
- Courbe d'apprentissage TEI pour contributeurs ; mitigé par doc et exemples
- XML verbeux ; compensé par Git LFS pour les gros fichiers

## Alternatives rejetées

- Markdown : insuffisant pour notes structurées et apparatus
- DocBook : moins adopté en humanités
- TEI Lite : trop pauvre pour apparatus criticus
- JSON-LD pur : pas adapté au texte structuré
- HTML5 + microdata : insuffisamment philologique
- TEI Publisher comme stack complète : XQuery/XSLT niche (cf. ADR-0001)

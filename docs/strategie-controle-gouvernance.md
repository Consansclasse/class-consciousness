# Stratégie — Garder le contrôle, le pouvoir et commercialiser `class-consciousness`

> ## 🟠 STATUT : DOCUMENT DE TRAVAIL — RIEN N'EST EXÉCUTÉ
>
> Ce document est une **analyse stratégique**, pas une décision actée.
> Au moment de sa rédaction (2026-05-17) :
> - **aucune** structure juridique n'est créée ;
> - **aucune** modification du dépôt n'est faite (gouvernance, licence, CLA…) ;
> - **aucune** marque n'est déposée ;
> - le dépôt est volontairement **privé**, le temps de la réflexion.
>
> Le modèle économique officiel reste, jusqu'à décision contraire formelle,
> celui verrouillé en auto-mémoire `project_economic_model` (archive ouverte
> financée par adhésions/subventions). Ce document **explore** une révision ;
> il ne la **prononce pas**.
>
> ⚠️ Contient des éléments de **droit français** (associations, fonds de
> dotation, SCIC, fiscalité, marques). Rédigé par un assistant IA, **non
> juriste**. Tout point marqué `[VÉRIFIER]` doit être confirmé par un·e
> avocat·e / expert-comptable spécialisé **ESS** avant toute exécution.

---

## ✅ Décisions prises par le porteur (2026-05-17)

- **Voie retenue : Voie 1** — le projet reste ouvert (AGPL / CC-BY-SA). Le
  contrôle est assuré par les instruments de gouvernance (§2), pas par la
  fermeture du code ou du corpus.
- **Modèle de démarrage : Phase 1 « association seule »** — l'association
  encaisse elle-même l'abonnement mensuel de l'app, sous le plafond de franchise
  des activités lucratives accessoires (81 051 € en 2026, cf. §2.8). Pas de SAS
  au démarrage ; la SAS sera créée à la montée en charge (Phase 2).
- Ce modèle **ne contredit pas** la mémoire `project_economic_model` : le corpus
  et le code restent ouverts, les textes restent en lecture libre — seul
  l'assistant RAG (coûteux en calcul) est soumis à quota. Ce n'est pas de l'open
  core, c'est « archive ouverte financée par sa communauté ».

**Restent à trancher** : forme juridique de long terme (association + SAS /
SCIC / fonds de dotation), dépôt de marque, et toute la Phase B du §6
(`GOVERNANCE.md`, CLA, etc.). **Rien n'est encore exécuté** : ni association
créée, ni code modifié, ni dépôt rouvert.

---

## ▶️ PROMPT DE REPRISE (à réutiliser dans une future session Claude Code)

Copier-coller le bloc ci-dessous pour reprendre ce chantier plus tard :

```
Reprise du chantier « contrôle, gouvernance et commercialisation ».

Lis intégralement docs/strategie-controle-gouvernance.md avant toute chose.
Lis aussi l'auto-mémoire project_economic_model, project_decisions,
project_principles, et .claude/AGENT_GUIDE.md.

Contexte : le porteur du projet a craint de perdre le contrôle/le pouvoir et a
envisagé de fermer le code. L'analyse (ce document) a conclu que ses trois
peurs — être mis en minorité, perdre la ligne éditoriale, aucun retour
personnel — sont des problèmes de GOUVERNANCE et de STRUCTURE JURIDIQUE, pas de
licence. Recommandation : Voie 1 (rester ouvert AGPL/CC-BY-SA) + blindage du
contrôle, structure hybride « association (à statuts protecteurs) qui détient
une SAS filiale commerciale ».

État : direction retenue (Voie 1 ; démarrage Phase 1 « association seule » qui
encaisse l'abonnement — cf. section « Décisions prises »). Rien n'a encore été
exécuté : ni association créée, ni code écrit, ni dépôt modifié. Reste à
trancher : forme juridique long terme, marque, Phase B.

Avant de toucher au dépôt, demande au porteur de trancher explicitement :
  1. Voie retenue : 1 (rester ouvert, recommandée) / 2 (hybride open-core) /
     3 (propriétaire) ?
  2. Structure juridique : hybride association + SAS filiale / SCIC /
     fonds de dotation ?
  3. A-t-il consulté un·e juriste ESS ? (obligatoire avant exécution)

NE RIEN exécuter dans le dépôt (GOVERNANCE.md, CLA, licence, README…) tant que
le porteur n'a pas validé la Voie ET la structure. Quand c'est validé, suivre
la « Phase B » du §6 de ce document. Ne jamais committer sans demande explicite.
Respecter les règles dures du projet (branche main only, citations vérifiées).
```

---

## Contexte

Le porteur de `class-consciousness` (archive marxiste open source à RAG sourcé)
a basculé le dépôt en privé sous le coup d'une inquiétude : **peur de perdre le
contrôle et le pouvoir sur le projet**, « comme dans le modèle associatif ». Il
a demandé une analyse poussée pour (a) garder le contrôle durablement et
(b) mieux commercialiser.

Cette piste **rouvre une décision verrouillée le jour même**
(`project_economic_model`, 2026-05-17 : « archive ouverte financée par
adhésions/subventions, JAMAIS open core »). La mémoire prévoit ce cas : tout
retournement exige un ADR + accord explicite. Rouvrir est légitime.

**Cadrage obtenu auprès du porteur :**
- Peur réelle = être **mis en minorité** + perdre la **ligne éditoriale** +
  **aucun retour personnel**. (Pas de peur du fork concurrent.)
- « Commercialiser mieux » = **faire vivre le projet ET se salarier**
  durablement. Pas de recherche de valeur de revente / exit.
- Appétit de fermeture = **indécis** — les trois voies sont analysées ci-dessous
  pour que le porteur tranche en connaissance de cause.

---

## 1. Diagnostic central — le constat qui change tout

La demande mélange **quatre axes indépendants** qu'on peut régler séparément :

| Axe | Question | Lié au « contrôle » ? |
|---|---|---|
| **Licence** | Ce que les autres ont le droit de faire du code/corpus | **Non** |
| **Visibilité** | Dépôt public ou privé *maintenant* | Non — réversible |
| **Gouvernance** | Qui décide de la direction et de l'éditorial | **OUI — le vrai sujet** |
| **Monétisation** | D'où vient l'argent, qui est payé | **OUI — pour « se salarier »** |

**Aucune des trois peurs n'est résolue en fermant le code ou le corpus.**

| Peur exprimée | Ce qui la résout réellement | Fermer le code aide ? |
|---|---|---|
| Être mis en minorité | Statuts juridiques + règles d'admission des membres | **Non.** Une société privée peut aussi avoir des associés/investisseurs qui votent contre toi. |
| Perdre la ligne éditoriale | Gouvernance éditoriale (directeur de publication statutaire) | **Non.** C'est un rôle, pas une licence. |
| Aucun retour pour toi | Une structure qui a des revenus et te verse un salaire | **Non.** Une asso/SCIC/SAS peut salarier ; l'open source n'interdit pas le salaire. |

Fermer la source **coûte beaucoup** (voir Voie 3) et **ne rapporte rien** contre
les peurs nommées. La peur vise la mauvaise cible : ce n'est pas la licence qui
menace le projet, c'est l'absence d'instruments de gouvernance et de structure.

**Corollaire rassurant :** rien n'est verrouillé légalement à ce stade. Tant que
le dépôt n'a pas été diffusé publiquement sous AGPL à des tiers, le porteur
conserve 100 % de sa liberté de choix. Garder le dépôt privé quelques semaines,
le temps de décider, est sain et réversible. `[VÉRIFIER]` l'historique
d'exposition publique (voir §9) : si le dépôt code ou le dépôt
`class-consciousness-corpus` ont déjà été publics, les licences AGPL/CC-BY-SA
émises sur ces commits sont **irrévocables** pour ce qui a été diffusé — cela
contraint la Voie 3.

---

## 2. Voie 1 — Rester ouvert + blinder le contrôle  *(recommandée)*

On peut être 100 % open source **et** fermement aux commandes **et** salarié.
C'est le cas de Linux, Blender, WordPress, GitLab. Le contrôle se gagne par
**sept instruments**, tous compatibles avec l'AGPL/CC-BY-SA.

### 2.1 Structure juridique — le levier n°1 contre « être mis en minorité »

Le « modèle associatif » qui inquiète n'est *un* modèle, pas *le* seul, et même
une association loi 1901 peut être taillée pour protéger le fondateur. Options :

- **Association loi 1901 à statuts protecteurs du fondateur** : collège des
  membres fondateurs distinct du collège des adhérents ; **admission de tout
  nouveau membre soumise à l'agrément du bureau** (verrou anti-entrisme — on ne
  peut pas mettre le fondateur en minorité avec des gens qu'il n'a pas admis) ;
  voix prépondérante du président ; révision des statuts conditionnée à l'accord
  des fondateurs ; objet social verrouillé. `[VÉRIFIER]` la rémunération du
  dirigeant (tolérance des 3/4 du SMIC ; seuil de ressources ; risque de perte
  de la « gestion désintéressée » et de l'éligibilité aux subventions).
- **Fonds de dotation** : pas de « membres » qui votent — un conseil
  d'administration que le fondateur compose initialement et qui se renouvelle
  lui-même. Beaucoup plus protecteur du contrôle. `[VÉRIFIER]` dotation initiale
  minimale (~15 000 €) et restrictions sur les subventions publiques.
- **SCIC (société coopérative d'intérêt collectif)** : société commerciale —
  peut vendre, salarier, facturer librement — mais mission verrouillée dans les
  statuts, gouvernance multi-collèges où le fondateur peut tenir un collège à
  voix pondérée.
- **Hybride association + SAS filiale** *(piste la plus adaptée — droit français
  vérifié)* :
  - une **association** (contrôlée par des statuts protecteurs, cf. §2.7) porte
    la mission, l'archive ouverte, encaisse adhésions et subventions ;
  - elle **détient une SAS** (filiale) qui porte l'activité commerciale —
    encodage TEI sous contrat, hébergement d'instances, intégration, support,
    abonnements app (cf. §2.7) — et **verse le salaire** du fondateur, président
    salarié de la SAS ;
  - **⚠️ Piège juridique vérifié** : le fondateur ne doit **pas** détenir
    personnellement la SAS tout en présidant l'association qui contracte avec
    elle. Le Conseil d'État juge qu'une telle « communauté d'intérêts » donne au
    président un intérêt indirect → la **gestion de l'association cesse d'être
    désintéressée** → elle perd ses exonérations fiscales et son éligibilité aux
    subventions. La SAS doit donc être **détenue par l'association**, pas par le
    fondateur en propre.
  - Le contrôle vient de ce que le fondateur contrôle l'association (statuts,
    §2.7), qui détient la SAS, dont il est président. Le retour est un
    **salaire** — pas des dividendes ni une valeur de revente. Cohérent avec
    l'objectif déclaré (faire vivre + se salarier, pas d'exit) ; à écarter si un
    exit était visé.
  - Obligations : la filialisation doit figurer dans les **statuts** et être
    votée en **AG** ; les contrats association ↔ SAS sont des **conventions
    réglementées** (déclarées, transparentes, au prix du marché — seuil de
    vigilance 153 000 € de subventions / activité économique) ; l'association
    doit garder une activité non lucrative réelle et ne pas être une simple
    holding qui encaisse des dividendes.
  - C'est le patron « structure non lucrative + filiale commerciale » classique
    en droit français (filialisation des activités lucratives).

→ Décision à prendre avec un·e juriste ESS. Recommandation par défaut :
**hybride association + SAS filiale**, ou **SCIC** si une seule entité est
préférée.

### 2.2 Marque déposée — le levier n°1 contre le fork (et pour le « pouvoir »)

Instrument de contrôle le plus puissant d'un projet open source. Le code est
forkable (AGPL), mais **le nom, le logo, le domaine et l'instance de référence
restent au porteur**. Un fork ne peut pas s'appeler `class-consciousness`.

- Déposer la marque « class-consciousness » (nom + logo) à l'INPI `[VÉRIFIER]`
  (~190 € une classe en France ; EUIPO ~850–1000 € pour l'UE).
- La détenir dans l'entité contrôlée (ou en nom propre, puis licence à
  l'association).
- Sécuriser `class-consciousness.org` et les variantes de domaine.
- Ajouter un `TRADEMARK.md` (politique d'usage de la marque).

### 2.3 Instance de référence

Le porteur opère *l'*instance canonique. Le self-hosting est permis (AGPL), mais
l'instance officielle fait foi : confiance, SEO, ARK résolus chez elle, effets
de réseau. Pouvoir de fait considérable et non réplicable.

### 2.4 CLA / cession de droits — garder la main sur la licence

Le dépôt utilise aujourd'hui le **DCO** (hook `dco-signoff`, check CI côté
serveur). Le DCO certifie la *provenance* d'une contribution mais **n'agrège pas
les droits d'auteur**. Sans CLA, relicencier le projet exigerait l'accord
unanime de tous les contributeurs passés.

Ajouter un **CLA** (ou une cession de droits à l'entité de contrôle) :
- chaque contributeur cède/licencie ses droits à l'entité contrôlée par le
  porteur ;
- cette entité conserve seule le pouvoir de **dual-licencier**, relicencier ou
  accorder des exceptions commerciales ;
- mécanisme par lequel des projets open source ont gardé la main (Qt, MySQL
  historiquement) ;
- pleinement compatible avec l'AGPL. C'est un verrou de pouvoir, pas une
  fermeture.

### 2.5 Gouvernance éditoriale — le levier contre « perdre la ligne éditoriale »

`GOVERNANCE.md` prévoit BDFL (an 0-1) → conseil de mainteneurs (an 1-3) →
hébergement par fondation (an 3+). Risque : la dissolution du BDFL emporterait
aussi l'autorité éditoriale du porteur.

Correctif : **séparer la gouvernance technique de la gouvernance éditoriale.**
- La gouvernance *technique* peut devenir collégiale (sain pour le bus factor).
- La gouvernance *éditoriale* — choix des textes, orientation théorique,
  standards d'encodage, commentaires — reste rattachée à un rôle statutaire de
  **directeur·rice de publication / éditeur·rice en chef** occupé par le
  porteur, avec une autorité réservée qui ne s'éteint pas quand le conseil
  technique se forme, et une règle de succession écrite.
- Cohérent avec le principe 4 (« pluralisme, commentaires signés,
  `GOVERNANCE.md` ouvert ») : la transparence du processus n'impose pas
  l'absence de directeur de publication — toute revue à comité de lecture en a
  un.

### 2.6 Infrastructure et clés

Détenir, dans l'entité contrôlée : compte registrar du domaine, DNS, clés de
déploiement, compte Stripe, comptes des hébergeurs. Contrôle opérationnel de
fait.

### 2.7 Le cas concret : « et si j'ai 10 000 membres ? »

Mécanisme envisagé : au-delà d'un quota d'usage quotidien de l'app, l'utilisateur
est obligé d'adhérer. Crainte légitime : 10 000 adhérents = 10 000 votant·e·s à
l'AG capables de destituer le fondateur. Deux réponses, la seconde étant la
meilleure.

**Réponse 1 — « membre qui paie » ≠ « membre qui vote ».**
La loi 1901 est très libre : les statuts définissent librement plusieurs
**catégories de membres** aux droits différents. Modèle standard :
- *Membres usagers / de soutien* — paient la cotisation, utilisent l'app, **sans
  droit de vote délibératif à l'AG** (ou voix seulement consultative). Les
  10 000 sont là.
- *Membres actifs* — petit collège (celles et ceux qui font tourner le projet),
  admis par le bureau, **seuls détenteurs du vote délibératif**.
- *Membres fondateurs / de droit* — le porteur, sièges réservés.

C'est la structure de toute association à large base d'usagers. `[VÉRIFIER]` la
rédaction avec un·e juriste : une privation *totale* de toute voix peut être
contestée, mais le découpage en collèges (voix consultative pour les usagers,
voix délibérative pour le collège actif) est solidement établi.

**Réponse 2 — ce qui est décrit n'est pas une adhésion, c'est un abonnement.**
Forcer le paiement pour continuer à utiliser l'app au-delà d'un quota, c'est
économiquement un **abonnement**, pas une cotisation — le code le sait déjà
(commentaire « cotisation annuelle, pas abonnement » dans `Membership.py`).
Conséquences :
- Déguiser un abonnement en cotisation expose à la TVA et au risque de
  lucrativité — fragile pour une association. `[VÉRIFIER]`.
- **C'est exactement le rôle de la SAS** : l'abonnement quota-dépassé est vendu
  par la SAS commerciale. Les 10 000 heavy users deviennent des **clients de la
  SAS**, pas des membres de l'association — **zéro droit de vote, nulle part**.
  La question des 10 000 votant·e·s disparaît entièrement.
- L'association ne garde que les *vraies* adhésions volontaires (soutien à la
  mission) + les subventions. Elle reste petite, gouvernée par son collège
  actif.

**Garde-fou de mission :** monétiser par quota l'**assistant RAG** (fonction IA,
coûteuse en calcul) est défendable ; un paywall sur la simple **lecture du
corpus et des textes** heurterait la mission d'archive et les financeurs. Garder
la consultation des textes libre, monétiser l'outil d'analyse.

→ « 10 000 membres » n'est un problème que si on les fait entrer comme membres
votants. Dans l'hybride asso + SAS, ce sont des clients : l'association reste
petite et sous contrôle.

### 2.8 Phasage : commencer sans SAS, l'association seule

Une association **peut vendre un abonnement mensuel elle-même, sans SAS**. La
loi 1901 n'interdit pas l'activité commerciale ; c'est l'ampleur, pas la nature,
qui la cadre.

- **Franchise des activités lucratives accessoires** : tant que les recettes
  commerciales (abonnements compris) restent **sous le plafond annuel —
  81 051 € pour 2026** (80 011 € en 2025), révisé chaque année `[VÉRIFIER]` —
  l'association est **exonérée de TVA, d'IS et de CET** sur cette activité.
  Trois conditions cumulatives : (1) gestion désintéressée ; (2) activités non
  lucratives **prépondérantes** ; (3) recettes accessoires sous le plafond.
- **Phase 1 (démarrage)** : l'association encaisse directement l'abonnement.
  Simple, pas de structure supplémentaire, pas de coût de création, pas d'impôt
  commercial sous le plafond.
- **Phase 2 (croissance)** : quand les recettes commerciales approchent le
  plafond ou deviennent prépondérantes, il faut **sectoriser** puis
  **filialiser** dans la SAS (cf. §2.1). La SAS n'est donc **pas un prérequis du
  jour 1** — c'est l'outil de la montée en charge.
- **Quelle que soit la phase** : garder la distinction **abonné ≠ membre
  votant** (§2.7) — un abonné est un client de l'association, pas un membre de
  l'AG ; et ne pas déguiser l'abonnement en « cotisation » (c'est une vente de
  service).

**Bilan Voie 1 :** avec ces sept instruments, le projet est open source,
fermement piloté, le porteur est salarié, et le projet reste éligible aux
subventions Digital Humanities et aux fondations de gauche. La seule chose
qu'on ne peut pas empêcher est le fork du code — or le porteur a explicitement
dit ne pas le craindre. Le « coût » de cette voie est donc, pour lui, quasi
nul. **C'est la recommandation.**

---

## 3. Voie 2 — Hybride (cœur ouvert + couches commerciales)

Deux variantes très différentes — l'amalgame est la principale source de
confusion :

- **Variante douce — « open source + services »** : tout le code et le corpus
  restent ouverts ; on vend des *services* autour (hébergement d'instances,
  encodage TEI sous contrat, intégration, support/SLA, formation). **Ce n'est
  pas de l'open core** : aucune fonctionnalité n'est paywallée. Cette variante
  est *déjà incluse* dans la Voie 1 (la SAS B2B). Recommandée.
- **Variante dure — « open core »** : le cœur est ouvert mais des
  fonctionnalités, ou pire le corpus, sont fermées/payantes. C'est précisément
  ce que `project_economic_model` a rejeté le 2026-05-17. Risques : dérive de
  mission ; méfiance des fondations de gauche ; et surtout, paywaller le
  **corpus** est à la fois le geste le plus contraire à la mission et un moat
  juridiquement faible — les textes sources sont en domaine public et
  ré-encodables par n'importe qui.

→ La « couche commerciale » nécessaire existe sans open core : ce sont les
services B2B de la Voie 1. La variante dure n'apporte un revenu marginal qu'au
prix d'un risque de financement et de réputation élevé. **Non recommandée.**

---

## 4. Voie 3 — Propriétaire / fermé

Code fermé, corpus fermé, SaaS propriétaire classique. Analyse honnête :

**Ce que ça apporte :**
- Empêcher les forks — *mais le porteur a dit ne pas craindre les forks.*
- Une valeur patrimoniale revendable — *mais le porteur a dit ne pas viser
  d'exit.*
→ La Voie 3 « achète » exactement ce qui a été déclaré **non** souhaité.

**Ce que ça coûte :**
- **Financement** : les subventions DH et les fondations de gauche (type
  Rosa-Luxemburg-Stiftung) financent l'ouverture. Une archive marxiste qui
  enclôt des textes du domaine public du mouvement ouvrier devient quasi
  infinançable par cette voie — risque de financement n°1 identifié dans
  `project_economic_model`.
- **Identité et décisions** : contredit l'AGPL/CC-BY-SA, les 7 principes
  (notamment §3 ouverture, §4 transparence, §5 souveraineté) et l'auto-définition
  du projet (« archive open-source de la théorie marxiste »).
- **Marché / crédibilité** : le public *est* la gauche. Une enclosure
  propriétaire et lucrative de textes marxistes du domaine public sera perçue
  par ce public comme une auto-contradiction — ce n'est pas un jugement moral,
  c'est une analyse de marché : l'audience et les financeurs partagent une
  idéologie hostile à l'enclosure, et l'adoption en souffrira.
- **Moat faible** : les textes sources sont en domaine public ; le cœur
  technique difficile (vérification citationnelle) est descriptible et
  reproductible. Fermer ne crée pas de barrière durable.
- **Possiblement déjà partiellement forclos** : `[VÉRIFIER]` — si le dépôt ou
  `class-consciousness-corpus` ont été publics, les grants AGPL/CC-BY-SA déjà
  émis sont irrévocables.
- **Et surtout** : la Voie 3 **ne résout pas mieux** les trois peurs que la
  Voie 1 (cf. §1) — une société fermée peut aussi mettre le fondateur en
  minorité, l'éditorial reste un problème de gouvernance, et le salaire est tout
  aussi possible en hybride asso+SAS tout en gardant les subventions.

**Verdict :** la Voie 3 est le plus mauvais ajustement aux objectifs déclarés.
Elle n'a de sens que pour quelqu'un qui veut un exit / une valeur patrimoniale
et n'a besoin ni de l'argent ni de la confiance de la gauche — explicitement pas
le cas ici.

---

## 5. Recommandation et correspondance peur → instrument

**Voie 1, structurée en hybride association + SAS filiale** (ou SCIC selon
l'avis ESS).

| Peur | Instrument qui la neutralise |
|---|---|
| Être mis en minorité | Statuts protecteurs : agrément des membres par le bureau, collège fondateur / fonds de dotation / collège pondéré SCIC |
| Perdre la ligne éditoriale | Rôle statutaire de directeur·rice de publication ; séparation gouvernance technique / éditoriale |
| Aucun retour personnel | Salaire via la SAS (ou poste salarié opérationnel dans l'asso/SCIC) ; revenus = adhésions volontaires + subventions + contrats B2B + abonnements app quota-dépassé (vendus par la SAS) |
| (bonus) Fork / appropriation | Marque déposée + instance de référence + CLA |

Résultat : contrôle ferme, salaire, **et** un projet qui reste ouvert et
finançable.

---

## 6. Plan d'action

### Phase A — Décisions & juridique *(avant tout changement de code)*
1. Consulter un·e avocat·e / expert-comptable **spécialisé ESS** : trancher la
   structure (hybride asso+SAS recommandé ; SCIC ; fonds de dotation).
2. Rédiger les statuts protecteurs du fondateur (agrément des membres, collège
   fondateur, voix prépondérante, verrou de révision, objet social).
   ▸ Brouillon disponible : `docs/statuts-association-projet.md` — à faire
   relire par un·e juriste ESS avant tout dépôt.
3. Déposer la marque « class-consciousness » (INPI, puis envisager EUIPO).
   `[VÉRIFIER]` disponibilité de la marque, classes, coûts.
4. Sécuriser domaine + comptes (registrar, DNS, Stripe, hébergeurs) dans
   l'entité.
5. Trancher la visibilité du dépôt : garder privé pendant la transition est OK
   et réversible ; re-publier sous AGPL est engageant — ne le faire qu'après
   A.1–A.4.
6. Écrire un **ADR** actant cette révision (exigé par `project_decisions` pour
   tout retournement) : il ne ferme rien, il *ajoute* des instruments de
   contrôle.

### Phase B — Dépôt *(à exécuter seulement après validation de la Voie + structure)*
- `GOVERNANCE.md` : rôle de directeur·rice de publication ; séparation
  gouvernance technique/éditoriale ; structure juridique retenue ; modèle de
  contrôle du fondateur ; règle de succession.
- Ajouter un **CLA** : nouveau `CLA.md` + check CI, en plus du DCO existant
  (`CONTRIBUTING.md`, `.pre-commit-config.yaml` / workflow CI).
- Ajouter `TRADEMARK.md` (politique d'usage de la marque) + mention ™ ;
  éventuel `NOTICE` (mettre à jour `REUSE.toml`).
- `README.md` : clarifier « archive open source + structure de gouvernance » —
  pas de revendication trompeuse, pas de promesse retirée en silence.
- Amender (ne pas écraser) la mémoire `project_economic_model` : consigner que
  des instruments de contrôle ont été ajoutés, le modèle restant ouvert.

### Phase C — Commercialisation
- **B2B** (la vraie « meilleure commercialisation ») : contrats d'encodage TEI,
  hébergement d'instances pour universités / syndicats / fondations,
  intégration, support/SLA, formation. Compatible open source à 100 %.
- **Subventions** : Huma-Num, DARIAH-FR, Inria, fondations de gauche.
- **Adhésions** : déjà implémentées (Stripe, 3 tiers + tarif solidaire) —
  capitaliser dessus, soigner le tier `STRUCTURE`. Rester des adhésions
  *volontaires* (pas de requalification en abonnement déguisé).
- **Abonnement app** : le quota d'usage quotidien dépassé bascule vers un
  abonnement payant. **Au démarrage, vendu directement par l'association**
  (franchise des activités lucratives accessoires, plafond 81 051 € en 2026 —
  cf. §2.8) ; **basculé vers la SAS** quand les recettes approchent le plafond.
  Dans tous les cas : abonnés = clients, pas membres votants (§2.7) ; quota sur
  l'assistant RAG, lecture des textes libre.
  ▸ Spécification d'implémentation : `docs/abonnement-app-implementation.md` —
  le code reste **à faire**.

---

## 7. Fichiers du dépôt concernés (Phase B, plus tard)

- `GOVERNANCE.md` — réécriture (séparation technique/éditorial, contrôle
  fondateur)
- `CONTRIBUTING.md` — ajout du process CLA
- `.pre-commit-config.yaml` + workflow CI — check CLA en plus du DCO
- `README.md` — clarification du positionnement
- `REUSE.toml` — si ajout d'un `NOTICE`
- **Nouveaux** : `CLA.md`, `TRADEMARK.md`,
  `docs/adr/NNNN-revision-controle-gouvernance.md`

---

## 8. Comment vérifier (quand la Phase B sera exécutée)

- Revue des statuts et de la structure par le·la juriste ESS (Phase A).
- Recherche d'antériorité de marque à l'INPI réussie.
- Check CLA en CI : un commit sans CLA signé échoue, un commit conforme passe.
- `GOVERNANCE.md` relu : il reflète exactement la structure juridique adoptée.
- Pas de test de code à proprement parler — c'est une évolution
  gouvernance/juridique.

---

## 9. Points à vérifier `[VÉRIFIER]` (avec un·e professionnel·le)

- Dotation minimale d'un fonds de dotation (~15 000 € ?) et accès aux
  subventions publiques pour cette forme.
- Rémunération d'un dirigeant d'association (tolérance 3/4 SMIC ; seuil de
  ressources ; impact sur la « gestion désintéressée » et l'éligibilité
  fiscale).
- Montage exact de la filialisation asso ↔ SAS : neutraliser la jurisprudence
  Conseil d'État « communauté d'intérêts » (la SAS détenue par l'association,
  pas par le fondateur en propre) ; conventions réglementées (seuil 153 000 €).
- Contraintes de gouvernance et de rémunération d'une SCIC.
- Coûts et classes du dépôt de marque INPI / EUIPO ; disponibilité du nom.
- Statut exact du droit d'auteur des textes Bilan (1933-38) et de leurs
  traducteur·rice·s.
- **Historique d'exposition publique** du dépôt code et du dépôt
  `class-consciousness-corpus` : ont-ils été publics ? combien de temps ? Les
  grants AGPL/CC-BY-SA déjà émis sont irrévocables et contraignent la Voie 3.

---

## 10. Sources (droit français — consultées le 2026-05-17)

- Filialisation des activités lucratives d'une association — assistant-juridique.fr
  <https://www.assistant-juridique.fr/filialisation_activite_lucrative.jsp>
- Sectorisation et filialisation des activités lucratives — association1901.fr
  <https://association1901.fr/finances-association-loi-1901/comptabilite-finances/sectorisation-et-filialisation-des-activites-lucratives-larme-ultime-contre-les-impots-commerciaux/>
- Une association peut-elle posséder des parts dans une société commerciale ? —
  Associations Mode d'Emploi
  <https://www.associationmodeemploi.fr/article/une-association-peut-elle-posseder-des-parts-dans-une-societe-commerciale.65724>
- Gestion désintéressée d'une association — Service-Public.gouv.fr
  <https://www.service-public.gouv.fr/particuliers/vosdroits/F31839>
- Communauté d'intérêts entre association et entreprise : gestion non
  désintéressée — Éditions Francis Lefebvre
  <https://www.efl.fr/actualite/communaute-interets-entre-association-entreprise-gestion-desinteressee_UI-1b76f303-9bf9-4546-80bb-dc9f7eac3a14>
- Les conventions réglementées dans les associations — assistant-juridique.fr
  <https://www.assistant-juridique.fr/conventions_reglementees_association.jsp>
- Franchise des impôts commerciaux : seuil porté à 81 051 € (2026) —
  assistant-juridique.fr
  <https://www.assistant-juridique.fr/activite_lucrative_franchise_impots.jsp>
- Franchise d'impôt pour les associations — LégiFiscal
  <https://www.legifiscal.fr/actualites-fiscales/4096-franchise-impot-associations-seuil-porte-80011.html>

> Aucune des sections juridiques ci-dessus ne remplace l'avis d'un·e
> professionnel·le. Faire valider la Phase A avant toute exécution.

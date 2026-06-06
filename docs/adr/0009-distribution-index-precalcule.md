# ADR-0009 — Distribution de l'index précalculé, mise à jour automatique

- **Statut** : proposé
- **Date** : 2026-05-31
- **Décideurs** : utilisateur (porteur du projet)
- **Complète** : [ADR-0008](0008-architecture-embedding-vps-cpu.md) (embedding des
  *requêtes* en direct) et [ADR-0003](0003-rag-architecture.md) (pipeline RAG).

## Contexte

Le corpus va grossir **très fréquemment** (nouveaux textes ajoutés en continu).
C'est un projet **open source** : des utilisateurs souvent **peu à l'aise
techniquement** clonent et auto-hébergent le dépôt. Aujourd'hui, rien n'amène le
corpus dans une instalation fraîche : `git clone` + `docker compose up` donne une
archive **vide** (cf. trou dans `docs/deploy/self-host.md`), et la seule voie
documentée — l'ingestion locale — impose à **chaque** utilisateur de faire
tourner l'embedding de **tout** le corpus sur **son** CPU.

Or les vecteurs du corpus sont **déterministes** : même modèle
(`Qwen3-Embedding-0.6B`, dim 1024) + même texte ⇒ même vecteur. Faire recalculer
le corpus complet par N utilisateurs, c'est exécuter N fois un calcul identique :
install de plusieurs heures, machines modestes en échec, et re-travail à chaque
mise à jour du corpus. Inacceptable pour le public visé.

Distinction clé (héritée d'[ADR-0008](0008-architecture-embedding-vps-cpu.md)) :

| | Embedding du **corpus** (masse) | Embedding des **requêtes** (live) |
|---|---|---|
| Volume | des milliers de chunks, croissant | 1 texte court par question |
| Quand | une fois | runtime, par user, par requête |
| Recalcul par user justifié ? | **non — déterministe** | oui (trivial) |

ADR-0008 a rejeté « précalculer puis pousser » **comme substitut à la
vectorisation des requêtes**. Le présent ADR précalcule **uniquement le corpus**
pour le distribuer ; `cc-embed` reste requis dans le stack utilisateur pour
embedder les questions en direct. Les deux ADR sont donc complémentaires.

## Décision

**On livre l'index, pas l'indexeur.** L'utilisateur ne fait **jamais** d'ingestion :
il télécharge un index déjà calculé, et il se met à jour **automatiquement**.

1. **Source de vérité vs index dérivé.** Le dépôt corpus
   (`class-consciousness-corpus`) reste la source de vérité (TEI P5). L'embedding
   du corpus devient une affaire de **mainteneur / CI**, jamais d'utilisateur.

2. **Publication centralisée (CI).** À chaque ajout au corpus, la CI ingère le
   **delta** (idempotent par SHA256), puis publie un index **versionné et signé** :
   - un **snapshot complet** (`pg_dump -Fc` + snapshot Qdrant, compressé zstd)
     pour le bootstrap d'une install neuve ;
   - des **« vector packs » incrémentaux** par unité (numéro/article) pour les
     mises à jour fréquentes.
   Chaque artefact est taggé par version de corpus **et** identité du modèle
   d'embedding (`…+qwen3-0.6b-d1024`), avec checksum + signature.

3. **Mise à jour automatique côté utilisateur (régime retenu).** Un service
   sidecar `corpus-sync` dans le compose :
   - **au boot** : si la base est vide, restaure le dernier snapshot complet ;
   - **en continu** : toutes les `CORPUS_SYNC_INTERVAL` (défaut quelques heures),
     lit un manifeste distant, télécharge les **packs manquants** et les
     **upsert** dans Postgres + Qdrant. Upsert **additif** ⇒ **aucune coupure**,
     aucun redémarrage requis. Idempotent ⇒ rejouable sans risque.
   Réglé par un toggle unique `CORPUS_AUTO_UPDATE=true` (défaut auto-héberg.),
   canal `CORPUS_CHANNEL=stable`. Hors-ligne ⇒ on garde l'index courant, pas de
   crash.

4. **Échappatoire reproductible.** L'ingestion depuis les TEI reste disponible
   (`make corpus-rebuild`) : qui ne fait pas confiance au binaire peut tout
   recalculer lui-même. Le binaire est une **commodité**, pas la source de vérité.

## Conséquences

Bénéfices :
- **UX cible atteinte** : « installe une fois, toujours à jour, zéro geste » pour
  des utilisateurs non techniques. Pas de recalcul, transfert de **données prêtes**
  (delta seulement), live, sans downtime.
- Fin du recalcul dupliqué d'un index identique chez chaque utilisateur.
- La croissance fréquente du corpus est **absorbée au centre** ; côté bord, elle
  se réduit à un téléchargement incrémental.
- Index **reproductible et pinné** : tout le monde fait tourner le même.

Coûts assumés :
- **L'effort se déplace sur le mainteneur** : la CI doit embedder le delta,
  publier, signer, versionner à chaque ajout. Si le pipeline tombe ou si le modèle
  change sans republication, les instances divergent. La simplicité du bord est
  **payée par la discipline du centre**.
- **Coût fixe une fois** côté utilisateur : `cc-embed` télécharge quand même le
  modèle (~1,2 Go) — indispensable pour les requêtes (ADR-0008), indépendant de
  la taille du corpus.
- **Confiance** : l'utilisateur applique un index binaire produit par le
  mainteneur → checksum + signature **obligatoires**, canal `stable` discipliné.
- **Couplage modèle ↔ vecteurs** : les packs sont liés à `Qwen3-0.6B` / dim 1024.
  Le `cc-embed` du user doit correspondre (déjà garanti par `_ensure_collection`,
  qui refuse un mismatch de dimension). Un changement de modèle = **bump majeur** :
  le client ne franchit pas une frontière majeure en silence, il re-bootstrappe un
  snapshot complet.
- Bande passante / disque consommés en tâche de fond → deltas modestes, à
  documenter.

## Alternatives rejetées

- **Ingestion locale par chaque utilisateur** (état actuel) : recalcul identique
  N fois, install de plusieurs heures, échecs sur machines modestes, re-travail à
  chaque mise à jour. Contraire à l'objectif open source grand public.
- **Mise à jour manuelle (`git pull` + `make corpus-sync`)** : suppose que
  l'utilisateur comprend un pull. Rejetée pour le public visé ; conservée comme
  capacité sous-jacente, mais pas comme régime par défaut.
- **Vecteurs commités en git brut** : binaires lourds qui gonflent l'historique →
  release assets / git-lfs / S3, jamais git brut.
- **Embedding des requêtes délégué à un endpoint hébergé** (pour retirer
  `cc-embed` du stack user) : casse l'auto-hébergement autonome et hors-ligne,
  contraire à l'éthos du projet (cf. ADR-0008).

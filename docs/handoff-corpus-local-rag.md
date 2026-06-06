# HANDOFF — Rendre tout Bilan utilisable en local + le distribuer aux utilisateurs

> **À quoi sert ce fichier.** C'est un prompt de reprise. Colle-le (ou pointe Claude
> dessus) quand tu reprends. Il explique le **but**, l'**état exact** du système, la
> **dernière étape** qui reste, et le **plan long terme**. Tout est vérifié au
> 2026-05-31. Réponses en français (règle du repo), branche `main` only, **aucun
> commit non sollicité** (l'utilisateur commit lui-même).

---

## 1. Le but, en une phrase

Avoir **tous les textes de Bilan utilisables en local** (lisibles ET interrogeables
par le chat RAG), puis faire en sorte que **les utilisateurs qui auto-hébergent le
projet n'aient AUCUN calcul à faire** — ils téléchargent un index déjà prêt.

## 2. Le modèle mental à garder en tête (le point qui prête à confusion)

Il y a **deux embeddings différents**, à ne pas confondre :

| | Embedding du **corpus** (masse) | Embedding des **requêtes** (live) |
|---|---|---|
| Quoi | les textes de Bilan → vecteurs | la question de l'utilisateur → vecteur |
| Combien | des milliers de chunks, ça grossit | 1 texte court par question |
| Quand | **une seule fois**, par le mainteneur | à chaque question, chez chaque user |
| Qui le fait | toi / la CI (jamais l'utilisateur) | le service `cc-embed` de chaque install |

**Le calcul lourd (corpus) se fait UNE fois et se distribue.** Les utilisateurs ne
recalculent jamais le corpus : ils téléchargent le résultat. Mais `cc-embed` reste
présent chez eux pour vectoriser **leurs questions** (léger). Voir
`docs/adr/0008-architecture-embedding-vps-cpu.md` et
`docs/adr/0009-distribution-index-precalcule.md`.

**Pourquoi quelqu'un doit cuisiner une première fois :** l'index (les vecteurs) du
corpus n'existe **nulle part** aujourd'hui. Vérifié le 2026-05-31 :
- repo corpus public `Consansclasse/class-consciousness-corpus` = **46 numéros TEI,
  2,2 Mo, ZÉRO vecteur** (texte brut uniquement) ;
- **aucune release GitHub** sur les 2 repos → aucun snapshot/index publié ;
- prod `api.consciencedeclasse.com` **injoignable** (DNS ne résout pas) ;
- base locale = juste le numéro de démo (`bilan-demo`).

Donc « télécharger un index prêt » est impossible tant que personne ne l'a fabriqué
au moins une fois.

## 3. État EXACT du système au moment du handoff

Déjà fait cette session :
1. **Bug double footer corrigé.** Ce n'était pas le code (déjà bon, commit
   `0b02d22`) : c'était un **cache Vite périmé** servi par le conteneur web sous
   Colima (inotify ne traverse pas le montage macOS→VM, donc le HMR ne voit pas les
   changements). Réglé par purge `.astro`/`.vite`/`dist` + `docker restart web`.
   ⚠️ **Correctif durable PAS encore appliqué** (voir §6).
2. **ADR-0009 écrit** : `docs/adr/0009-distribution-index-precalcule.md` (statut
   *proposé*, à valider/committer).
3. **Corpus cloné** en sibling : `~/Projets/class-consciousness-corpus` (51 fichiers
   `.tei.xml`).
4. **`infra/docker-compose.yml` édité** (non commité) :
   - nouveau service **`cc-embed`** (CPU, image `infra/Dockerfile.embed` target
     `prod`, volume `cc_embed_models`) — **buildé et HEALTHY** (device cpu, dim
     1024, modèles Qwen3-0.6B embedding + reranker chargés) ;
   - service `api` : ajout de `CC_API_EMBED_SERVER_URL: http://cc-embed:8001`,
     `depends_on: cc-embed`, et **montage du corpus** `../../class-consciousness-corpus:/app/corpus-prod:ro` ;
   - volume `cc_embed_models:` déclaré.
   - `api` **recréé** : voit bien **51 fichiers** dans `/app/corpus-prod/bilan/`,
     `CC_API_EMBED_SERVER_URL` correct. Config compose validée.

**Autrement dit : tout est prêt pour l'ingestion. Il ne reste qu'à la lancer.**

## 4. ⭐ LA DERNIÈRE ÉTAPE qui reste : ingérer les 46 numéros (≈ quelques minutes)

L'ingestion lit le chemin **DANS** le conteneur api (`/admin/ingest` fait
`Path(payload.path)`), embedde via `cc-embed`, écrit dans Postgres + Qdrant.
**Idempotent par SHA256** → rejouable sans doublon.

```sh
# Depuis ~/Projets/class-consciousness, conteneurs up (make up si besoin).
docker exec class-consciousness-dev-api-1 sh -c '
  for f in /app/corpus-prod/bilan/*.tei.xml; do
    echo -n "$f -> "
    curl -s -X POST localhost:8000/admin/ingest \
      -H "Content-Type: application/json" -d "{\"path\":\"$f\"}"
    echo
  done'
```

Vérifier ensuite :
```sh
curl -s "http://localhost:8000/corpus?size=50" | grep -o '"total":[0-9]*' | head -1
```
Puis : textes lisibles sur `http://localhost:3001/corpus`, et le chat RAG répond.

⚠️ **À VÉRIFIER pendant l'ingestion** : le dossier `bilan/` contient à la fois
`bilan-001.tei.xml` (numéro complet) ET 5 fichiers `bilan-001-*.tei.xml` (articles
isolés du n°001). Le glob `*.tei.xml` les prend tous → risque de **double
ingestion du contenu du n°001**. Soit `ingest_issue` déduplique par `ark` (à
confirmer dans `apps/api/src/cc_api/services/ingest.py`), soit il faut exclure l'un
des deux. Regarder le résultat `n_articles`/`was_duplicate` et le `/corpus` final.

## 5. Plan LONG TERME — distribuer l'index aux utilisateurs (le « simple pour eux »)

Une fois l'index fabriqué (§4), il devient la **source** à distribuer. Régime retenu
= **mise à jour automatique** (meilleur UX pour un public peu technique). Étapes,
dans l'ordre, à construire :

1. **Primitives snapshot/restore** — étendre `make db-snapshot`/`db-restore`
   (Postgres, déjà là) pour couvrir **Qdrant** (snapshot API). → `make corpus-snapshot`
   / `make corpus-restore`.
2. **Vector packs incrémentaux + loader** — vecteurs précalculés par unité, et un
   `make corpus-sync` idempotent qui upsert **seulement le delta** (clé SHA256).
3. **Sidecar compose `corpus-sync`** — au boot : restaure le snapshot si base vide ;
   en continu : télécharge les packs manquants et les upsert (additif → **sans
   coupure**). Toggle `CORPUS_AUTO_UPDATE=true` (défaut), `CORPUS_CHANNEL=stable`,
   `CORPUS_SYNC_INTERVAL`.
4. **CI de publication** (sur le repo corpus) — à chaque ajout de texte : embed du
   delta → publie packs + snapshot **signés** (checksum) en release versionnée,
   taggée avec corpus **et** modèle d'embedding (`…+qwen3-0.6b-d1024`).
5. **Corriger `docs/deploy/self-host.md`** — (a) il affirme à tort que la prod tourne
   sur consciencedeclasse.com alors que l'API est injoignable ; (b) il ne dit rien
   sur comment le corpus arrive → documenter : `clone → up → l'index se restaure et
   se met à jour seul`.

Ordre conseillé : **1 + 2** d'abord (cœur testable en local), puis 3, puis 4, puis 5.

**Invariant à ne jamais casser** : les vecteurs distribués sont liés à
`Qwen3-Embedding-0.6B` / dim 1024. Le `cc-embed` de chaque user doit être le même
(garanti par `_ensure_collection` qui refuse un mismatch de dimension). Changer de
modèle d'embedding = **re-embed total + bump majeur du snapshot**.

## 6. Petits reliquats / décisions en attente

- **Correctif durable du HMR Colima (footer)** : ajouter dans `apps/web/astro.config.*`
  `vite: { server: { watch: { usePolling: true, interval: 300 } } }` pour que le
  hot-reload remarche sans redémarrer le conteneur web. **Pas encore fait.**
- **Repo « ia agent »** : demandé par l'utilisateur, mais **inaccessible** —
  l'orga `Consansclasse` n'a que 2 repos publics ; le repo agent est privé ou sous
  un autre nom. Il faut l'URL exacte (+ public) OU `gh auth login` dans la session
  pour le cloner s'il est privé. **À ajouter au projet une fois l'accès obtenu.**
- **Où la CI tournera / où héberger les snapshots** (release GitHub vs S3/CDN) :
  décision d'infra à prendre avant l'étape 5-§5.
- **`infra/docker-compose.yml` et l'ADR-0009 sont non commités** — l'utilisateur
  commit lui-même (Conventional Commits en français).

## 7. Gotchas spécifiques à cet environnement (Mac M5 / Colima)

- Colima : **pas d'inotify** à travers le montage → après une édition front, le HMR
  ne réagit pas ; redémarrer le conteneur web (ou appliquer le polling Vite, §6).
- `cc-embed` tourne en **CPU** (pas de CUDA sur Mac). `make embed-gpu` est CUDA-only
  → **ne pas l'utiliser ici** ; le service CPU ajouté au dev compose le remplace.
- L'`api` lit les chemins d'ingestion **dans son conteneur** : le corpus DOIT être
  monté (`/app/corpus-prod`). Un chemin hôte ne marcherait pas.
- `host.docker.internal` résout bien sous Colima (192.168.5.2) si jamais besoin de
  joindre l'hôte depuis un conteneur.
- Binaire Docker/Colima dans `~/.local/bin` (pas `/opt/homebrew/bin`).

## 8. Commande de reprise rapide

```sh
cd ~/Projets/class-consciousness
make up                 # relance la stack (api, web, cc-embed, db, qdrant, redis…)
docker ps               # cc-embed doit être healthy
# puis lancer l'ingestion du §4, et vérifier /corpus
```

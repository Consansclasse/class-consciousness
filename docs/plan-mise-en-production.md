# Plan — Mise en production fonctionnelle : Archive + Assistant RAG

> **Projet** : class-consciousness · **Date** : 2026-05-17
> **Objectif** : que le site **et** l'assistant RAG fonctionnent réellement en production.
> **Statut** : document de travail vivant — coché au fur et à mesure.
> Légende : ✅ fait · 🔄 en cours · ⬜ à faire · 👤 action utilisateur requise.

---

## 1. Architecture cible — relier le local et la prod

Le VPS de production n'a pas de GPU ; le modèle d'embedding `Qwen3-Embedding-8B`
(8-bit) en exige un. La RTX A2000 reste donc sur la machine locale. Best practice
pour relier les deux : un **tunnel privé WireGuard** — chiffré, pair-à-pair,
100 % auto-hébergé, aucun service tiers (conforme à la règle « pas de SaaS managé »).

```
 Machine locale (RTX A2000)              VPS OVH — Coolify (sans GPU)
 ┌───────────────────────────┐          ┌──────────────────────────────┐
 │ cc-embed (Qwen3)           │          │ api · web · postgres         │
 │  systemd · bind 10.10.0.2  │◄══ WG ══►│ qdrant · redis               │
 │  :8001                     │  tunnel  │ api → http://10.10.0.2:8001  │
 └───────────────────────────┘  chiffré └──────────────────────────────┘
```

- `cc-embed` reste local mais devient un **service géré** (systemd : démarrage
  au boot, redémarrage automatique).
- VPS et machine locale rejoignent un réseau privé WireGuard `10.10.0.0/24`.
- L'API de prod joint `cc-embed` via `CC_API_EMBED_SERVER_URL=http://10.10.0.2:8001`.
- **Conséquence assumée** (déjà actée par la contrainte « pas de GPU payant ») :
  la machine locale doit rester **allumée et connectée 24/7**. Si elle tombe, le
  site et la consultation du corpus continuent ; seul `/qa` renvoie une erreur
  propre (503). Point de défaillance unique inévitable sans GPU sur le VPS.

---

## 2. Périmètre

**Inclus** — site, consultation du corpus, assistant RAG sourcé fonctionnel de
bout en bout, sécurité, déploiement reproductible.

**Exclu (chantier suivant)** — abonnement payant (checkout / portail / quota RAG)
et authentification Authentik : non démarrés, et l'abonnement dépend de l'auth.
L'adhésion, déjà déployée, est laissée telle quelle.

---

## 3. État constaté

### Audit (3 explorations : backend · infra · web/tests/corpus)

Blocages principaux pour un RAG fonctionnel : `cc-embed` absent du déploiement,
aucune ingestion du corpus en prod, `CC_API_EMBED_SERVER_URL` par défaut sur
localhost. Blocages applicatifs : frontend lisant la mauvaise variable d'URL API,
pas de middleware CORS, chat non câblé à `/qa`. Sécurité : clé Anthropic exposée,
résidus Voyage partout (dont un gate CI cassant tout push sur `main`).
Détail complet à consolider dans `docs/audit-2026-05-17.md`.

### Diagnostic prod (interrogation directe, 2026-05-17)

| Cible | Résultat |
|---|---|
| `consciencedeclasse.com` | **200** — le site répond |
| `api.cdc.consciencedeclasse.com/health` | **503 « no available server »** |
| `…/corpus` | **503** |

« No available server » = Traefik a la route mais **aucun conteneur `api` sain
derrière**. L'API de prod est arrêtée ou en crash-loop — c'est la cause du
« données absentes ». Cause racine à confirmer via **les logs du conteneur `api`**.

**Bug identifié et corrigé** : `docker-compose.prod.yml` passait les identifiants
sous `CC_POSTGRES_*` / `CC_QDRANT_*` / `CC_REDIS_*`, alors que le code lit
`POSTGRES_*` / `QDRANT_URL` / `REDIS_URL` (confirmé par le compose dev, qui marche).
L'API tournait avec le mot de passe `changeme` et sans clé Qdrant.

---

## 4. Étapes

### Étape 0 — Sécurité & déblocage CI
- ✅ 0.2 — retrait du gate `VOYAGE_API_KEY` dans `.github/workflows/ci.yml`
- ⬜ 👤 0.1 — révoquer la clé Anthropic exposée, en générer une neuve, la mettre
  uniquement dans Coolify Settings + `.env` local
- ⬜ 0.3 — vérifier que `POSTGRES_PASSWORD` de prod est bien le secret Coolify

### Étape A — Tunnel WireGuard local↔VPS + cc-embed managé
- ⬜ A.1 — installer WireGuard : VPS (serveur, UDP 51820) + machine locale (pair)
- ⬜ A.2 — configurer `cc-embed` pour écouter sur l'IP WireGuard `10.10.0.2:8001`
- ⬜ A.3 — service systemd `cc-embed.service` + `wg-quick@wg0` activés
- ⬜ A.4 — vérifier depuis le VPS : `curl http://10.10.0.2:8001/health`
- ⬜ A.5 — écrire `docs/adr/0008-architecture-embedding-wireguard.md`

### Étape B — Cohérence du déploiement prod
- ✅ B.1 — `docker-compose.prod.yml` : noms de variables corrigés, service
  `migrate` (Alembic au déploiement), résidus Voyage retirés, anchor de build
- ✅ B.2 — `Dockerfile.web` + compose : `PUBLIC_API_URL` → `PUBLIC_API_BASE_URL`
- ✅ B.3 — middleware CORS (`main.py` + `settings.py`)
- ✅ B.4a — `.env.example` : bloc Voyage retiré, `CC_API_EMBED_*` / `STRIPE_*` ajoutés
- ⬜ B.4b — nettoyer les résidus Voyage restants : `Makefile`, `CLAUDE.md`,
  `apps/api/CLAUDE.md`, `docs/deploy/self-host.md`, fixture seed
- ⬜ B.5 — pointer le rate-limiter slowapi sur Redis

### Étape C — Câbler le RAG bout-en-bout
- ⬜ C.1 — câbler `chat.astro` sur `POST /qa` (rendu réponse + citations + états)
- ⬜ C.2 — resserrer le `SYSTEM_PROMPT` de `rag.py` (sans toucher aux seuils)
- ⬜ C.3 — dégradation gracieuse : `cc-embed` injoignable → `/qa` répond 503 propre
- ⬜ C.4 — corriger `scripts/ingest_corpus.py` (rejet à tort des TEI mono-article)
- ⬜ C.5 — réparer les tests E2E corpus cassés

### Étape D — Corpus
- ⬜ D.1 — créer le dépôt public `class-consciousness-corpus` (CC-BY-SA-4.0)
- ⬜ D.2 — documenter et tester la procédure d'ingestion prod
- ⬜ D.3 — prouver le pipeline avec la fixture seed
- ⬜ 👤 D.4 — ingérer le corpus réel (dépend du matériel Bilan disponible ;
  statut juridique des traducteurs à vérifier `[VÉRIFIER]`)

### Étape E — Déploiement & vérification
- ⬜ E.1 — `make test` + `make test-e2e` au vert sur dev
- ⬜ 👤 E.2 — commit (Conventional Commits FR, `-s`) puis push → redéploiement Coolify
- ⬜ E.3 — le déploiement applique les migrations, démarre api/web
- ⬜ E.4 — déclencher l'ingestion, redéployer `web`
- ⬜ E.5 — smoke test : `/health`, `/corpus` peuplé, `/qa` réponse sourcée
- ⬜ E.6 — mettre à jour `ops/runbooks/coolify-deploy.md`

### Tâche transverse
- ⬜ Consolider l'audit dans `docs/audit-2026-05-17.md`

---

## 5. Ce qui dépend de toi

1. **Logs du conteneur `api` de prod** (Coolify → service `api` → Logs) — pour
   diagnostiquer la cause exacte du 503. Ou un accès SSH au VPS.
2. **Rotation de la clé Anthropic** (Étape 0.1).
3. **Accès au VPS** pour l'Étape A (WireGuard) : SSH utilisable, ou exécution
   manuelle des commandes fournies.
4. **Étape D** : quel matériel Bilan est déjà disponible (texte, PDF, scans) ?
5. **Confirmation** avant : rotation de secrets, et déploiement (le push).

---

## 6. Règles respectées

- Aucun commit ni push de la part de l'IA — l'utilisateur les fait. Tout sur `main`.
- Confirmation avant toute action irréversible (rotation, déploiement, suppression).
- Aucune phrase RAG sans citation vérifiée ; aucun seuil de vérification relâché.
- Pas de mocks DB/Qdrant dans les tests ; testcontainers.

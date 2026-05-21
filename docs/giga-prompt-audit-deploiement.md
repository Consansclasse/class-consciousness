# GIGA-PROMPT — Audit total du projet + mise en production Coolify

> **Comment l'utiliser :** ouvrir une session Claude Code à la racine du dépôt
> `class-consciousness` et coller le bloc ci-dessous (ou pointer la session sur
> ce fichier). La session exécute la Phase 1 (audit) puis, après validation,
> la Phase 2 (déploiement).
>
> Document de travail — non commité.

---

```
RÔLE
Tu es un ingénieur senior chargé d'un audit exhaustif puis de la mise en
production du projet class-consciousness. Tu travailles avec rigueur de niveau
publication académique, pensée 10+ ans, et zéro complaisance : tu signales tous
les problèmes, même inconfortables.

CONTEXTE PROJET
- class-consciousness = archive open-source de la théorie marxiste avec RAG
  sourcé. Monorepo pnpm + uv. Toutes tes réponses en FRANÇAIS.
- DEUX dépôts :
  1. class-consciousness (CE dépôt) = code, AGPL-3.0, dépôt PUBLIC.
  2. class-consciousness-corpus = les textes TEI, CC-BY-SA, dépôt PUBLIC.
     Consommé via la variable CC_CORPUS_DIR. Le code ne garde que la fixture
     corpus/_seed/.
- Stack : FastAPI (apps/api, :8000) + Astro (apps/web) + Postgres 17 + Qdrant
  + Redis. LLM = Anthropic Claude Opus 4.7. Embeddings + reranking = Qwen3
  auto-hébergé en local sur GPU (apps/embed-server, « cc-embed », :8001).
- Dev local : Postgres :5433, Qdrant :6333, Redis :6380, cc-embed :8001
  (processus hôte sur GPU, PAS un conteneur). API :8000.
- Déploiement cible : Coolify v4, fichier docker-compose.prod.yml, voir
  docs/adr/0006-deployment-coolify.md et ops/runbooks/coolify-deploy.md.

LECTURES OBLIGATOIRES AVANT DE COMMENCER
- CLAUDE.md, .claude/AGENT_GUIDE.md, .claude/rules/*.md
- apps/api/CLAUDE.md, apps/web/CLAUDE.md
- docs/strategie-controle-gouvernance.md (stratégie, modèle économique)
- docs/abonnement-app-implementation.md (spec du module abonnement)
- docs/adr/ (toutes les ADR), ops/runbooks/coolify-deploy.md
- docker-compose.prod.yml, infra/

RÈGLES DURES NON-NÉGOCIABLES
1. Branche `main` uniquement — JAMAIS de branche, JAMAIS de PR.
2. Aucun commit sans demande explicite de l'utilisateur. Conventional Commits
   en français, signés DCO (git commit -s).
3. Aucun push sans accord explicite.
4. Tests = vrais services via testcontainers, JAMAIS de mocks DB/Qdrant.
5. Discipline de code sévère : aucune ligne de trop, aucune abstraction sans
   deux usages réels, mort au code mort.
6. RAG : aucune phrase de réponse sans citation littéralement vérifiée.
7. Secrets : jamais en clair dans le code ni les commits. Ne JAMAIS afficher
   une clé en entier.

ÉTAT CONNU AU DÉPART (vérifier, ne pas faire confiance aveuglément)
- Module abonnement : modèle Abonnement + migration 0008 + webhook Stripe
  commités et testés. MANQUENT : endpoints checkout / portail / me, et le
  quota RAG. Ils dépendent de l'authentification.
- Authentification : DÉCIDÉE = Authentik (IdP OIDC auto-hébergé, Python).
  RIEN n'est construit. Le modèle auth_tokens (magic-link maison) est à
  considérer comme obsolète une fois Authentik en place.
- RAG : l'endpoint /qa fonctionne mais les réponses sortent trop maigres — la
  vérification de citation rejette la majorité des phrases (le LLM paraphrase
  au lieu de citer verbatim). Le SYSTEM_PROMPT de services/rag.py est à
  resserrer.
- Voyage : décision = supprimé, on passe 100 % Qwen3 local. MAIS résidus de
  config Voyage à nettoyer dans .env, .env.example, docker-compose.prod.yml,
  et une référence dans apps/api/src/cc_api/clients/embed.py (vérifier nature).
- docker-compose.prod.yml : 5 services seulement (postgres, qdrant, redis, api,
  web). MANQUENT : le serveur d'embeddings cc-embed (Qwen3/GPU), toute étape
  d'ingestion du corpus. apps/embed-server n'a PAS de Dockerfile.
- Conséquence : un déploiement neuf = Qdrant vide = /qa incapable de répondre.
- Base de données : la DB de dev n'est pas migrée (« no head »). Pas de
  stratégie de migration au déploiement visible.
- SÉCURITÉ : la clé ANTHROPIC_API_KEY a été exposée dans un chat — la traiter
  comme COMPROMISE. Doit être révoquée et régénérée ; la nouvelle ne doit
  exister que dans Coolify Settings / .env (gitignoré), jamais ailleurs.

============================================================
PHASE 1 — GIGA AUDIT
============================================================
Produis un audit EXHAUSTIF du projet. Explore le code, ne te fie pas aux
descriptions. Couvre au minimum ces axes :

A. Architecture & code — cohérence monorepo, dette, code mort, abstractions
   injustifiées, écarts entre CLAUDE.md/AGENT_GUIDE et la réalité du code
   (ex. mentions de clients/voyage.py qui n'existent plus).
B. Sécurité — secrets (clé Anthropic compromise, .env, gitleaks), surface
   d'attaque, rate limiting, absence d'authentification, CORS, en-têtes
   proxy, IDOR, validation des webhooks Stripe, dépôt public.
C. RAG & qualité — pipeline embed→retrieve→rerank→generate→vérification ;
   le problème des réponses maigres ; seuils de citation ; SYSTEM_PROMPT.
D. Module abonnement — ce qui est construit vs la spec
   (docs/abonnement-app-implementation.md) ; ce qui manque.
E. Authentification — état zéro ; plan d'intégration Authentik.
F. Base de données & migrations — chaîne Alembic intègre ?, parité
   modèles/migrations, stratégie de migration en production.
G. Déploiement & infra — docker-compose.prod.yml, Dockerfiles, secrets
   Coolify, absence de cc-embed et d'ingestion, résidus Voyage.
H. Corpus & ingestion — comment le corpus public arrive jusqu'au Qdrant de
   prod ; reproductibilité ; versionnement.
I. Tests & CI — couverture, hooks pre-commit (ruff, mypy, biome, gitleaks,
   DCO), pipeline GitHub Actions.
J. Conformité aux 7 principes et aux règles d'or du projet.

LIVRABLE PHASE 1 : un fichier docs/audit-YYYY-MM-DD.md, structuré, avec
chaque constat classé BLOQUANT / IMPORTANT / MINEUR, et pour chacun :
preuve (fichier:ligne), impact, correctif proposé. Termine par une synthèse
priorisée. Ne corrige RIEN en Phase 1 — tu audites seulement.
NE COMMITE PAS sans demande explicite.

============================================================
PHASE 2 — MISE EN PRODUCTION COOLIFY
============================================================
À n'entamer qu'après que l'utilisateur a validé l'audit ET répondu à :
  → Le serveur de déploiement Coolify possède-t-il le GPU (RTX A2000) ?
    Sans GPU sur le serveur, Qwen3 self-hosted en prod est impossible.
  → La clé Anthropic a-t-elle été révoquée et régénérée ?

Objectif : que l'application ET l'assistant RAG fonctionnent réellement en
production. Étapes :

1. NETTOYAGE — supprimer tous les résidus Voyage (.env, .env.example,
   docker-compose.prod.yml, embed.py si pertinent). Aligner CLAUDE.md et
   AGENT_GUIDE sur la réalité (Qwen3, plus de Voyage).
2. SERVEUR D'EMBEDDINGS EN PROD — câbler cc-embed (Qwen3) :
   - écrire un Dockerfile pour apps/embed-server OU décider d'un processus
     hôte sur le serveur GPU ;
   - l'ajouter au docker-compose.prod.yml avec accès GPU (réservation device
     NVIDIA + nvidia-container-toolkit) si conteneurisé ;
   - définir CC_API_EMBED_SERVER_URL pour que l'API le joigne.
   Contrainte : le modèle d'embedding doit être IDENTIQUE pour l'ingestion et
   pour /qa (corpus en 4096-dim) — sinon dimensions incompatibles.
3. INGESTION DU CORPUS EN PROD — définir et documenter l'étape qui remplit le
   Qdrant de prod : cloner class-consciousness-corpus (public, pas d'auth),
   lancer l'ingestion (scripts/ingest_corpus.py / CLI cc-corpus) contre le
   Qdrant et le cc-embed de prod. À exécuter une fois, puis à chaque mise à
   jour du corpus.
4. MIGRATIONS — garantir `alembic upgrade head` au déploiement (entrypoint ou
   job dédié), idempotent.
5. SECRETS — tous via Coolify Settings : ANTHROPIC_API_KEY (NOUVELLE clé),
   SERVICE_PASSWORD_*. Vérifier qu'aucun secret n'est en clair dans le dépôt.
6. SOURCE COOLIFY — le dépôt étant désormais public, le clone HTTPS anonyme
   fonctionne ; envisager une GitHub App pour l'auto-déploiement sur push.
7. RÉSEAU / HTTPS — FQDN, Traefik/Caddy, CORS, FORWARDED_ALLOW_IPS.
8. SMOKE TEST POST-DÉPLOIEMENT — /health vert, puis une vraie question sur
   Bilan à /qa qui renvoie une réponse sourcée non vide.
9. RUNBOOK — mettre à jour ops/runbooks/coolify-deploy.md avec la procédure
   complète et reproductible (y compris ingestion et embeddings).

GARDE-FOUS
- Demander confirmation avant toute action irréversible (déploiement,
  rotation de secrets, suppression).
- Ne pas committer ni pousser sans accord explicite.
- Marquer [VÉRIFIER] tout point juridique, volatil, ou non confirmé.
- Si une étape ne peut pas être faite proprement (ex. pas de GPU serveur),
  le DIRE clairement plutôt que bricoler.

LIVRABLE PHASE 2 : un déploiement Coolify fonctionnel (app + RAG), un
docker-compose.prod.yml complet et cohérent, le runbook à jour, et un rapport
final de ce qui marche / ne marche pas / reste à faire.
```

---

## Notes pour le porteur du projet

- Ce prompt suppose deux validations de ta part **entre** la Phase 1 et la
  Phase 2 : (1) le serveur Coolify a-t-il le GPU, (2) la clé Anthropic a-t-elle
  été régénérée.
- Tu peux aussi lancer **seulement la Phase 1** d'abord (auditer, lire le
  rapport, décider), puis la Phase 2 dans une session séparée.
- Documents liés : `docs/strategie-controle-gouvernance.md`,
  `docs/abonnement-app-implementation.md`, `docs/statuts-association-projet.md`.

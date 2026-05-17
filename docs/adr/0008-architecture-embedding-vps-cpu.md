# ADR-0008 — Embeddings : Qwen3-0.6B sur CPU, co-localisé avec le VPS

- **Statut** : accepté
- **Date** : 2026-05-17
- **Décideurs** : utilisateur (porteur du projet)
- **Remplace** : la décision « embeddings Qwen3-Embedding-8B 8-bit sur GPU local
  (RTX A2000) » de `.claude/AGENT_GUIDE.md`

## Contexte

Le pipeline RAG a besoin d'un modèle d'embedding qui tourne **en production** :
chaque question de `/qa` est vectorisée en direct pour interroger Qdrant —
pré-calculer des embeddings ne couvre que le corpus, jamais les requêtes.

La décision verrouillée initiale (`AGENT_GUIDE.md`) faisait tourner
`Qwen3-Embedding-8B` en 8-bit sur un GPU local (RTX A2000 12 Go). Or la prod est
un VPS OVH (VPS-2 : ~6 vCœurs / 12 Gio RAM, **sans GPU**). Le modèle 8B réclame
~9 à 16 Go rien que pour se charger : il ne tient pas sur le VPS-2.

Options écartées par l'utilisateur : louer une instance GPU (~7 900 €/an,
contraire à la règle budget « pas de GPU payant »), relier la machine GPU locale
au VPS (la prod doit rester autonome), agrandir le VPS.

## Décision

Le service `cc-embed` (`apps/embed-server`) fait tourner **`Qwen3-Embedding-0.6B`**
(embeddings, dimension 1024) et **`Qwen3-Reranker-0.6B`** (reranking) **sur CPU**.
Il est conteneurisé comme service de `docker-compose.prod.yml`, sur le VPS, joint
par l'API via le réseau Docker interne (`http://cc-embed:8001`).

Aucun GPU en production. Corpus et requêtes sont vectorisés par le même modèle
0.6B, sur le VPS. La machine locale ne fait plus partie de la production.

## Conséquences

Bénéfices :
- Prod **100 % autonome sur le VPS**, sans coût supplémentaire ni GPU.
- Aucun lien externe, aucune dépendance à une machine tierce.
- Image conteneur CPU légère (torch CPU, pas de CUDA ni bitsandbytes).

Coûts assumés :
- Qualité d'embedding sous celle du 8B — compensée par le reranker 0.6B et la
  vérification littérale des citations (la rigueur du RAG ne dépend pas du
  modèle d'embedding).
- Latence `/qa` plus élevée que sur GPU — acceptable pour une archive de recherche.
- Empreinte RAM de `cc-embed` (~4-7 Gio) à surveiller sur le VPS-2 (12 Gio) ;
  levier disponible si tension : quantification int8/bf16 des modèles.

## Alternatives rejetées

- **Qwen3-8B sur GPU loué** (OVH AI Deploy, ~7 900 €/an) : contraire à la règle
  budget « pas de GPU payant/loué ».
- **Qwen3-8B via lien VPS→machine locale** (tunnel WireGuard) : la prod ne
  serait plus autonome (dépendance à une machine allumée 24/7).
- **Qwen3-8B sur le CPU du VPS-2** : ~16 Go requis, 12 Go disponibles → crash
  mémoire, risque d'emporter Postgres/Qdrant.
- **Agrandir le VPS (≥32 Gio) pour le 8B sur CPU** : coût mensuel supplémentaire
  et `/qa` très lent.
- **Pré-calcul des embeddings en local puis push en prod** : ne couvre que le
  corpus, pas la vectorisation des requêtes en direct.

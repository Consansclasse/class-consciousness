# Spécification — Abonnement de l'app + quota d'usage (Phase 1)

> ## ✅ IMPLÉMENTÉ — 2026-05-19
>
> Ce document était la spécification du chantier. **Le code a été écrit** :
> modèle `Abonnement` + migration `0008`, webhook Stripe, endpoints
> `checkout` / `portal` / `me`, quota RAG (compteur Redis à fenêtre glissante +
> dépendance `enforce_rag_quota` sur `/qa`), page web `/abonnement`, tests
> d'intégration. Le détail ci-dessous reste la **référence de conception** —
> mais les marqueurs `(à faire)` et le « PROMPT DE REPRISE » sont **caducs**.
>
> Décision actée : l'abonnement est encaissé **par l'association** (Phase 1, sans
> SAS — cf. `docs/strategie-controle-gouvernance.md` §2.8). **Prérequis de mise
> en production** (hors-code, non faits) : l'association doit exister, avec un
> compte Stripe à son nom et un *Price* récurrent mensuel renseigné dans
> `STRIPE_PRICE_ABONNEMENT_MENSUEL`.

---

## ▶️ PROMPT DE REPRISE

```
Reprise du chantier « abonnement app + quota RAG ».
Lis docs/abonnement-app-implementation.md en entier, puis docs/strategie-controle-gouvernance.md.
Le modèle est décidé ; il reste à ÉCRIRE LE CODE (tout est marqué « (à faire) »).
Avant de coder, demande au porteur de trancher les « Questions ouvertes » (§14).
Respecter les règles du projet : branche main only, pas de commit non sollicité,
tests sans mocks (testcontainers + stripe-mock), discipline de code stricte.
Ne PAS toucher au flux adhésions/cotisation existant : l'abonnement est un
module distinct et parallèle.
```

---

## 1. Décision et modèle

- **Quoi** : un **abonnement mensuel récurrent** à l'application, vendu par
  l'association, qui débloque l'usage de l'**assistant RAG** au-delà d'un quota
  quotidien gratuit.
- **Ce qui reste gratuit** : la **lecture du corpus et des textes** — toujours,
  sans quota. Le quota ne porte **que** sur l'assistant RAG (fonction IA,
  coûteuse en calcul).
- **Statut juridique** : l'abonnement est une **prestation de service** (vente),
  juridiquement **distincte de la cotisation** d'adhésion. Un abonné est un
  **client**, pas un membre votant (cf. §12).
- **Cadre fiscal** : recettes logées dans la franchise des activités lucratives
  accessoires de l'association, plafond **81 051 € en 2026** (cf. stratégie
  §2.8). Au-delà → sectorisation puis filialisation (SAS, Phase 2).

## 2. Périmètre — existant vs nouveau

### Existant (à NE PAS modifier)
Flux d'**adhésion / cotisation annuelle** — paiement Stripe **unique**
(`mode=payment`) :
- `apps/api/src/cc_api/routers/adhesions.py` — `/adhesions/checkout`,
  `/adhesions/webhook/stripe`, `/adhesions/intent/{id}`
- `apps/api/src/cc_api/services/adhesion.py`
- `apps/api/src/cc_api/models/membership.py`, `models/adhesion_intent.py`
- `apps/api/src/cc_api/schemas/adhesion.py`
- `apps/api/src/cc_api/clients/stripe.py` — wrapper Stripe (réutilisable)

### Nouveau (objet de cette spec — tout `(à faire)`)
Flux d'**abonnement récurrent** — Stripe Billing (`mode=subscription`) + **quota
RAG**. Module **parallèle et distinct** du flux adhésions.

## 3. Modèle de données `(à faire)`

### 3.1 Nouveau modèle `Abonnement` — `models/abonnement.py` `(à faire)`
Table `abonnements`. Champs proposés :

| Champ | Type | Note |
|---|---|---|
| `id` | UUID PK | |
| `user_id` | FK `users.id` | un abonnement rattaché à un compte |
| `stripe_customer_id` | str | client Stripe |
| `stripe_subscription_id` | str, **unique** | abonnement Stripe |
| `stripe_price_id` | str | tarif souscrit |
| `status` | enum | `ACTIVE`, `TRIALING`, `PAST_DUE`, `CANCELED`, `INCOMPLETE`, `UNPAID` — miroir du statut Stripe |
| `current_period_end` | timestamptz | fin de période payée |
| `cancel_at_period_end` | bool | résiliation programmée |
| `created_at` / `updated_at` / `canceled_at` | timestamptz | |

` ▸ Délibérément séparé de Membership : aucun lien vers le vote ni l'adhésion.`

### 3.2 Quota d'usage — Redis `(à faire)`
Compteur à **fenêtre glissante de 24 h** dans Redis (`clients/redis.py` déjà
présent) — **pas** un reset calendaire :
- clé `rag:quota:{user_id}` (ou `:{ip_hash}` pour anonyme) ;
- à la **première** requête RAG : créer la clé à `1` avec **TTL = 24 h** ;
- requêtes suivantes : incrément **sans toucher au TTL** (`INCR`) ;
- **2 requêtes max** par fenêtre ; à la 3ᵉ → refus `402`. L'utilisateur doit
  **attendre la fin des 24 h** (expiration de la clé) avant de réinterroger ;
- le TTL résiduel de la clé donne le délai de reset exposé dans la réponse 402.
- Pas de table SQL pour le compteur courant. Une persistance d'agrégats pour la
  compta peut être ajoutée plus tard si besoin `(à faire — optionnel)`.

## 4. Migration Alembic `(à faire)`

- Nouveau fichier `apps/api/alembic/versions/202606NN_0008_abonnements.py`
  (respecter la convention `YYYYMMDD_NNNN_description.py` ; dernier en place :
  `20260517_0007_adhesion_intent_public_token.py`).
- Crée la table `abonnements` + le type enum de statut.
- `(à faire)` : `make migrate` / vérifier `alembic upgrade head`.

## 5. Intégration Stripe Billing `(à faire)`

- **Prérequis (hors code)** : créer dans le compte Stripe **de l'association**
  un *Product* « Abonnement [DÉNOMINATION] » et un *Price* **récurrent mensuel** →
  identifiant `price_...` à mettre en config.
- `services/abonnement.py` `(à faire)` : orchestration — création/récupération
  du *Customer* Stripe, ouverture d'une *Checkout Session* `mode=subscription`,
  lecture de l'état d'un abonnement.
- Étendre `clients/stripe.py` `(à faire)` : appels Subscriptions / Customer /
  Billing Portal.
- **Self-service** : utiliser le **Stripe Billing Customer Portal** pour la
  résiliation et la mise à jour du moyen de paiement (évite de coder un tunnel
  de gestion).

## 6. Webhooks Stripe `(à faire)`

Traiter les événements d'abonnement (endpoint dédié `/abonnements/webhook/stripe`
ou extension du webhook existant — cf. §14) :
- `checkout.session.completed` (mode `subscription`) → crée la ligne
  `Abonnement` ;
- `customer.subscription.created` / `.updated` / `.deleted` → met à jour
  `status`, `current_period_end`, `cancel_at_period_end` ;
- `invoice.paid` → prolonge la période ;
- `invoice.payment_failed` → passe en `PAST_DUE`.

Vérification **obligatoire** de la signature Stripe (comme le webhook adhésions
existant). Idempotence sur l'`event.id`.

## 7. Quota d'usage du RAG `(à faire)`

Dépendance FastAPI `enforce_rag_quota` `(à faire)`, posée sur les routes de
`routers/qa.py` (et **seulement** celles-ci — jamais sur `routers/corpus.py`).

Logique :
1. Identifier l'utilisateur (session / `auth_token` — modèle `auth_token.py`
   présent) ou le marquer anonyme.
2. Si l'utilisateur a un `Abonnement` au statut `ACTIVE`/`TRIALING` → accès
   accordé (cap anti-abus éventuel, cf. §14).
3. Sinon : lire le compteur Redis de la fenêtre glissante 24 h. Sous le seuil
   gratuit (**2**) → incrémenter, accès accordé. À partir de la 3ᵉ → **refus**
   `HTTP 402 Payment Required`, corps JSON structuré indiquant le quota, le
   délai d'attente restant (TTL) et l'URL d'abonnement.
4. Anonyme : quota plus bas (ou nul) — décision §14.

## 8. Endpoints API `(à faire)`

Nouveau routeur `routers/abonnements.py` `(à faire)` :
- `POST /abonnements/checkout` → ouvre une Checkout Session `subscription`,
  renvoie l'URL de redirection.
- `POST /abonnements/webhook/stripe` → événements d'abonnement (§6).
- `GET /abonnements/me` → statut d'abonnement de l'utilisateur courant + quota
  consommé / restant.
- `POST /abonnements/portal` → URL de session du Customer Portal Stripe.

Schémas Pydantic `schemas/abonnement.py` `(à faire)`.

## 9. Frontend `(à faire)`

Dans `apps/web/` (Astro 5 + îlots React) :
- page **`/abonnement`** : présentation de l'offre, bouton de souscription ;
- pages de retour **succès / annulation** Stripe ;
- affichage du **quota restant** dans l'UI de l'assistant + invitation à
  s'abonner quand le quota gratuit est atteint (réponse 402) ;
- état de l'abonnement + accès au Customer Portal dans l'espace compte.

## 10. Configuration / variables d'environnement `(à faire)`

À ajouter dans `.env.example` et la config `(à faire)` :
- `STRIPE_PRICE_ABONNEMENT_MENSUEL` — identifiant du Price récurrent ;
- `RAG_FREE_QUOTA_PER_WINDOW` — quota gratuit par fenêtre de 24 h (utilisateur
  authentifié non abonné) — **défaut : 2** ;
- `RAG_QUOTA_WINDOW_HOURS` — durée de la fenêtre glissante — **défaut : 24** ;
- `RAG_QUOTA_ANON_PER_WINDOW` — quota anonyme par fenêtre de 24 h —
  **défaut : 2** ;
- `RAG_SUBSCRIBER_CAP_PER_DAY` — plafond anti-abus de l'abonné actif —
  **défaut : 6** (cf. §14 q3) ;
- `STRIPE_PORTAL_RETURN_URL`, URLs de succès/annulation du checkout.

## 11. Tests `(à faire)`

Conformes à la règle projet — **pas de mocks**, vrais services via
testcontainers + `stripe-mock` (déjà utilisé par `test_adhesion_routes.py`) :
- souscription : Checkout `subscription` → webhook → ligne `Abonnement` créée ;
- cycle de vie : `invoice.payment_failed` → `PAST_DUE` ; `subscription.deleted`
  → `CANCELED` ;
- quota : sous le seuil = accès ; au-delà = `402` ; abonné actif = bypass ;
- **non-régression** : `routers/corpus.py` (lecture des textes) jamais bloqué ;
- non-régression du flux adhésions/cotisation existant.

## 12. Garde-fous (vrais dès la Phase 1)

- **Abonné ≠ membre votant** : `Abonnement` n'a aucun lien avec `Membership` ni
  avec un quelconque droit de vote. Un abonné est un client de l'association.
- **Lecture des textes libre** : le quota ne s'applique qu'à `routers/qa.py`,
  jamais à la consultation du corpus.
- **Terminologie** : « abonnement », jamais « cotisation » — distinction
  juridique (vente de service vs adhésion) à préserver dans le code, l'UI et la
  facturation.
- **Plafond fiscal** : prévoir une visibilité sur le cumul annuel des recettes
  d'abonnement vs le plafond de franchise (81 051 € — 2026). Un export/rapport
  d'agrégats `(à faire — peut venir plus tard)`.
- **RGPD** : le consentement est déjà porté par le modèle `User`
  (`consent_data_at`) ; l'abonnement ajoute des données de facturation.

## 13. Checklist globale `(à faire)`

- [ ] (à faire) Modèle `Abonnement` — `models/abonnement.py`
- [ ] (à faire) Migration Alembic `202606NN_0008_abonnements.py`
- [ ] (à faire) Schémas `schemas/abonnement.py`
- [ ] (à faire) Service `services/abonnement.py`
- [ ] (à faire) Extension `clients/stripe.py` (Subscriptions / Portal)
- [ ] (à faire) Routeur `routers/abonnements.py` (4 endpoints)
- [ ] (à faire) Webhooks abonnement (§6)
- [ ] (à faire) Dépendance `enforce_rag_quota` + pose sur `routers/qa.py`
- [ ] (à faire) Compteur quota Redis
- [ ] (à faire) Frontend : page `/abonnement`, retours, affichage quota, compte
- [ ] (à faire) Variables d'environnement + `.env.example`
- [ ] (à faire) Tests d'intégration (testcontainers + stripe-mock)
- [ ] (à faire) Product + Price récurrent créés dans le Stripe de l'association
- [ ] (à faire) `make test` / `make smoke` au vert

## 14. Questions ouvertes (à trancher avant de coder)

1. **Quota gratuit** : ~~combien de requêtes RAG/jour~~ → **tranché** :
   **2 requêtes max** puis **attente de 24 h** (fenêtre glissante, cf. §3.2),
   pour un utilisateur authentifié non abonné.
2. **Anonymes** : ~~quota ou assistant réservé aux comptes ?~~ → **tranché** :
   accès autorisé, **2 requêtes max** par fenêtre glissante de 24 h (compteur
   par `ip_hash`), même seuil que l'utilisateur authentifié non abonné.
3. **Abonné** : ~~usage illimité ou cap ?~~ → **tranché** : cap anti-abus de
   **6 requêtes/jour**. Calé sous le seuil d'équilibre (~7/j net pour un
   abonnement à 9 €/mois) pour rester rentable même si l'abonné sature son
   quota tous les jours.
4. **Prix** de l'abonnement mensuel ? Tarif solidaire/réduit prévu (comme pour
   les cotisations) ?
5. **Option annuelle** en plus du mensuel ?
6. **Webhook** : endpoint séparé `/abonnements/webhook/stripe` ou mutualisé avec
   le webhook adhésions existant ?
7. **Intent en attente** : créer un modèle `AbonnementIntent` (miroir
   d'`AdhesionIntent`) ou se reposer uniquement sur les webhooks ?

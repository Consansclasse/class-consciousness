# Politique de sécurité

## Versions supportées

Phase 0 — projet pré-1.0. Toutes les versions taggées sont actives mais aucune n'a encore reçu d'audit formel. Une politique formelle de support sera publiée à v1.0.

## Signaler une vulnérabilité

**Ne pas ouvrir d'issue publique.**

- **Email** : `security@class-consciousness.org` *(à activer en phase 0)*
- **PGP** : empreinte à publier dès activation, signée par les mainteneurs
- **Alternative** : GitHub Security Advisory privée — onglet « Security » du repo

## Engagement

- **Accusé de réception** sous 72 h ouvrées
- **Première évaluation** sous 7 jours
- **Divulgation coordonnée** : publication conjointe sous **90 jours** par défaut, plus tôt si correctif disponible et déployé
- Mention publique du·de la signaleur·euse (avec son accord)

## Périmètre

**Concerné** :
- Failles d'authentification, d'autorisation, d'injection (SQL, XSS, CSRF, prompt injection)
- Fuites de données (configuration, logs, secrets)
- Compromission de l'intégrité du corpus (bypass de validation TEI/Sigstore)
- Compromission de l'intégrité des citations RAG (génération de citations falsifiées passant la validation)
- Vulnérabilités dans les dépendances que nous embarquons

**Hors périmètre** (ne pas signaler) :
- Vulnérabilités dans les services tiers (Anthropic, Voyage, Hetzner) — signaler directement chez eux
- Manque de header HTTP best-practice sans impact démontré
- Rate-limit non strict sur endpoints lecture (par design : archive publique)
- Engineering social, phishing visant des mainteneurs hors infrastructure projet

## Récompenses

Pas de bug bounty pour l'instant (projet sans budget). Reconnaissance publique et co-publication d'avis de sécurité.

## Bonnes pratiques pour les déployeurs self-host

- Lire [`docs/deploy/self-host.md`](./docs/deploy/self-host.md) en entier
- Renouveler les clés API (Anthropic, Voyage) tous les 6 mois
- Activer 2FA sur les comptes mainteneurs
- Garder Postgres + Qdrant + Redis derrière le réseau interne (jamais exposés sur Internet)
- Mises à jour Dependabot acceptées sous 7 jours pour les niveaux high/critical

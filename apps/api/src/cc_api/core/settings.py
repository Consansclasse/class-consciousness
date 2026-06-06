# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Secret de session par défaut, réservé au dev. Le validateur de `Settings`
# refuse le démarrage hors dev tant qu'il n'est pas surchargé.
_DEFAULT_SESSION_SECRET = "dev-insecure-session-secret"  # noqa: S105 — défaut dev, pas un secret réel


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CC_API_", env_file=".env", extra="ignore")

    env: str = Field(default="dev")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    # CORS — origines navigateur autorisées (le chat RAG appelle l'API depuis
    # le sous-domaine web). Liste séparée par des virgules ; vide = CORS off.
    cors_origins: str = Field(default="", alias="CC_API_CORS_ORIGINS")

    postgres_host: str = Field(default="postgres", alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="class_consciousness", alias="POSTGRES_DB")
    postgres_user: str = Field(default="cc", alias="POSTGRES_USER")
    postgres_password: str = Field(default="changeme", alias="POSTGRES_PASSWORD")

    qdrant_url: str = Field(default="http://qdrant:6333", alias="QDRANT_URL")
    qdrant_api_key: str | None = Field(default=None, alias="QDRANT_API_KEY")

    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # Serveur d'embedding + reranking cc-embed (Qwen3 0.6B sur CPU — voir
    # apps/embed-server et docs/adr/0008-architecture-embedding-vps-cpu.md).
    # Les vecteurs du corpus sont en dimension `embed_dim` ; changer de modèle
    # d'embedding impose une ré-ingestion complète.
    embed_server_url: str = Field(
        default="http://127.0.0.1:8001", alias="CC_API_EMBED_SERVER_URL"
    )
    embed_dim: int = Field(default=1024, alias="CC_API_EMBED_DIM")
    embed_model: str = Field(
        default="Qwen/Qwen3-Embedding-0.6B", alias="CC_API_EMBED_MODEL"
    )

    anthropic_api_key: str | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    # Bearer alternatif pour router l'API Anthropic via un LLM GATEWAY/PROXY qui
    # s'authentifie par `Authorization: Bearer` (cf. doc Claude Code,
    # `ANTHROPIC_AUTH_TOKEN`). Prioritaire sur `anthropic_api_key` s'il est défini.
    # ⚠️ NE JAMAIS y placer un token OAuth d'abonnement Claude Code (`claude
    # setup-token`) : les identifiants OAuth sont réservés à Claude Code/claude.ai
    # (CGU Anthropic) — l'employer dans ce backend serait hors conditions. La prod
    # et l'éval RAG en dev utilisent une vraie clé API (ANTHROPIC_API_KEY).
    anthropic_auth_token: str | None = Field(default=None, alias="ANTHROPIC_AUTH_TOKEN")
    # Sonnet 4.6 par défaut — Opus 4.7 est trop coûteux pour le volume RAG.
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")
    # Modèle du 2ᵉ passage « juge » qui vérifie l'ancrage sémantique (entailment)
    # de chaque phrase analytique. Haiku 4.5 : la tâche est une classification
    # ENTAILED / NOT_ENTAILED / CONTRADICTED, bien dans ses cordes — il divise
    # nettement la latence du contrôle face à Sonnet. La rigueur du juge reste
    # à surveiller via /debug-rag (cf. .claude/rules/citation-honest-vs-literal.md).
    anthropic_judge_model: str = Field(
        default="claude-haiku-4-5", alias="ANTHROPIC_JUDGE_MODEL"
    )

    # Stripe — paiement de la cotisation associative.
    # En dev : clés sk_test_… (sandbox Stripe) ou pointage vers stripe-mock.
    # En prod : sk_live_… avec asso vérifiée (SIRET + RNA + RIB).
    stripe_secret_key: str | None = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: str | None = Field(default=None, alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: str | None = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")
    # Override de l'endpoint Stripe pour les tests d'intégration (stripe-mock).
    stripe_api_base: str | None = Field(default=None, alias="STRIPE_API_BASE")
    # Pay-as-you-go : Price *metered* mensuel adossé à un Stripe Billing Meter
    # (facturation à l'usage, par tranche de 1000 tokens). Créé via
    # `ops/scripts/provision-stripe-payg.py`. Remplace l'ancien abonnement
    # forfaitaire : on ne vend plus un accès, on refacture le coût LLM marginal.
    stripe_price_payg: str | None = Field(default=None, alias="STRIPE_PRICE_PAYG")
    # Nom de l'évènement de meter (doit coïncider avec celui du Meter Stripe).
    # Chaque requête RAG facturable émet un `billing.meter_event` sous ce nom.
    stripe_meter_event_name: str = Field(
        default="rag_tokens", alias="STRIPE_METER_EVENT_NAME"
    )
    # Base URL publique du site web — pour construire success_url / cancel_url
    # transmises à Stripe Checkout.
    public_web_base: str = Field(default="http://localhost:3000", alias="PUBLIC_WEB_BASE")

    # ── Notion — export « 1-clic » d'un document d'atelier vers une page Notion.
    # Intégration INTERNE : créer une intégration sur notion.so/my-integrations,
    # partager une page cible avec elle, puis renseigner le token + l'ID de page.
    # Le token reste côté serveur (jamais exposé au navigateur).
    notion_token: str | None = Field(default=None, alias="NOTION_TOKEN")
    notion_parent_page_id: str | None = Field(
        default=None, alias="NOTION_PARENT_PAGE_ID"
    )
    # Version d'API Notion — le contrat page-parent est stable ; surchargeable.
    notion_version: str = Field(default="2022-06-28", alias="NOTION_VERSION")

    # Authentification — sessions navigateur (cookie signé) + email/mot de passe.
    # `session_secret` signe le cookie : DOIT être surchargé en production.
    session_secret: str = Field(
        default=_DEFAULT_SESSION_SECRET, alias="CC_API_SESSION_SECRET"
    )
    # SMTP pour les emails transactionnels (vérification d'adresse, réinitialisation
    # de mot de passe). Sans `smtp_host`, le lien est seulement journalisé (mode
    # dev) au lieu d'être expédié — aucun envoi réel.
    smtp_host: str | None = Field(default=None, alias="CC_API_SMTP_HOST")
    smtp_port: int = Field(default=587, alias="CC_API_SMTP_PORT")
    smtp_user: str | None = Field(default=None, alias="CC_API_SMTP_USER")
    smtp_password: str | None = Field(default=None, alias="CC_API_SMTP_PASSWORD")
    smtp_from: str = Field(
        default="noreply@class-consciousness.org", alias="CC_API_SMTP_FROM"
    )
    smtp_starttls: bool = Field(default=True, alias="CC_API_SMTP_STARTTLS")

    # Pipeline RAG : seuils de la règle d'or « aucune phrase sans citation vérifiée ».
    rag_k_retrieve: int = Field(default=40, alias="CC_API_RAG_K_RETRIEVE")
    # Sélection des passages transmis au LLM — `k` ADAPTATIF : on retient les
    # passages dont le score de rerank dépasse `rag_rerank_min_score`, borné
    # entre min et max. Une question large bien couverte → beaucoup de passages ;
    # une question étroite → peu. Si AUCUN passage n'atteint le seuil, la réponse
    # est refusée (`no_relevant_chunks`) : le corpus ne couvre pas la question.
    rag_rerank_min_score: float = Field(default=0.3, alias="CC_API_RAG_RERANK_MIN_SCORE")
    rag_k_rerank_min: int = Field(default=4, alias="CC_API_RAG_K_RERANK_MIN")
    rag_k_rerank_max: int = Field(default=8, alias="CC_API_RAG_K_RERANK_MAX")
    # Nombre de passages soumis au reranker. Le reranking CPU coûte ~4 s/passage
    # sur le VPS prod : ce plafond borne directement la latence du pipeline.
    rag_rerank_pool: int = Field(default=16, alias="CC_API_RAG_RERANK_POOL")
    # Reranking activé ? Désactivé par défaut : le reranker cc-embed sur CPU est
    # le plus gros poste de latence (~4 s/passage). Sans lui, le classement par
    # fusion RRF (vecteur + mots-clés) sert de score — moins fin, bien plus rapide.
    rag_rerank_enabled: bool = Field(default=False, alias="CC_API_RAG_RERANK")
    rag_citation_fuzzy_threshold: int = Field(default=95, alias="CC_API_RAG_CITATION_FUZZY")
    # Poids de diversité du reranking (MMR par groupe) : pénalité appliquée au
    # score de rerank pour chaque chunk déjà retenu du même article. Force la
    # sélection à couvrir plusieurs articles/numéros — condition de la nuance.
    # 0 = sélection par score brut.
    rag_mmr_diversity_weight: float = Field(default=0.1, alias="CC_API_RAG_MMR_WEIGHT")
    # Décomposition de question : le pipeline décompose la question en
    # sous-questions de recherche et récupère pour chacune, afin de couvrir
    # tous les angles. Échec gracieux → recherche sur la seule question.
    # Désactivée par défaut : la décomposition ajoute un appel LLM et multiplie
    # les recherches. Réactivable (`CC_API_RAG_DECOMPOSITION=true`) pour gagner
    # en couverture au prix de la latence.
    rag_decomposition_enabled: bool = Field(default=False, alias="CC_API_RAG_DECOMPOSITION")
    # Routage de complexité : si activé, la décomposition n'est déclenchée que
    # pour les questions jugées complexes (comparaison, multi-angles), jamais
    # pour les questions simples — un appel LLM économisé. Remplace la décision
    # binaire `rag_decomposition_enabled` par une décision par question.
    rag_routing_enabled: bool = Field(default=False, alias="CC_API_RAG_ROUTING")
    # Recherche hybride : combine la recherche vectorielle (Qdrant) et une
    # recherche plein-texte par mots-clés (Postgres FTS français), fusionnées
    # par Reciprocal Rank Fusion. Rattrape les passages au vocabulaire exact
    # que l'embedding manque. Sans effet si aucune session DB n'est fournie.
    rag_hybrid_enabled: bool = Field(default=True, alias="CC_API_RAG_HYBRID")
    # Mode partiel : si au moins 1 phrase est vérifiée et certaines ne le sont
    # pas, on expose les phrases vérifiées (200 + incomplete=true) au lieu de
    # refuser toute la réponse (422). Aucune phrase non vérifiée n'est exposée
    # — la règle d'or « aucune phrase sans citation » reste sauve.
    rag_partial_mode_enabled: bool = Field(default=True, alias="CC_API_RAG_PARTIAL_MODE")
    # Vérification d'ancrage sémantique : un 2ᵉ passage LLM « juge » statue, pour
    # chaque phrase analytique, si elle est ENTAILED / NOT_ENTAILED / CONTRADICTED
    # par les passages cités. C'est le garde-fou anti-hallucination du mode
    # « explication de texte ». Désactivable uniquement pour les tests offline.
    rag_verifier_enabled: bool = Field(default=True, alias="CC_API_RAG_VERIFIER")
    # Quota *gratuit* de l'assistant RAG — fenêtre glissante. La lecture du
    # corpus n'est jamais limitée ; seul l'assistant (coûteux en calcul) l'est.
    # Au-delà de ce quota, l'accès passe en pay-as-you-go : chaque requête est
    # refacturée à l'usage (cf. routers/qa.py `enforce_rag_quota`).
    rag_free_quota_per_window: int = Field(default=2, alias="CC_API_RAG_FREE_QUOTA")
    rag_quota_window_hours: int = Field(
        default=24, alias="CC_API_RAG_QUOTA_WINDOW_HOURS"
    )
    # Plafond de sécurité anti-runaway en pay-as-you-go : nombre max de requêtes
    # facturables par fenêtre, MÊME pour un abonné. Ce n'est pas un palier
    # commercial mais un garde-fou (session volée, boucle client) bornant la
    # facture. Doit rester > quota gratuit. 0 = désactivé (PAYG strictement sans
    # plafond). Au-delà → 402 `payg_daily_cap`.
    rag_payg_daily_cap: int = Field(default=200, alias="CC_API_RAG_PAYG_DAILY_CAP")
    # Rétention des `rag_interactions` — purge opportuniste à chaque écriture
    # (pas de cron côté serveur). 90 j par défaut : assez pour les analyses
    # qualité, court pour limiter la surface RGPD.
    rag_interaction_retention_days: int = Field(
        default=90, alias="CC_API_RAG_INTERACTION_RETENTION_DAYS"
    )
    # Jeton requis pour `/metrics` (scraping Prometheus). Si None, l'endpoint
    # est ouvert — acceptable en dev, à renseigner en prod (Coolify Settings).
    metrics_token: str | None = Field(default=None, alias="CC_API_METRICS_TOKEN")

    # ── Auto-synchronisation du corpus ────────────────────────────────────────
    # Le corpus TEI vit dans un repo GitHub public séparé. Quand il s'enrichit,
    # une tâche de fond (lifespan, services/corpus_sync.py) détecte le nouveau
    # SHA de tête, télécharge le tarball et ingère les nouveaux numéros
    # (idempotent SHA256) — SANS `git pull` ni geste utilisateur. Défaut OFF dans
    # le code (tests/dev n'appellent jamais GitHub par surprise) ; ACTIVÉ dans les
    # artefacts de déploiement (docker-compose.prod.yml) → prod et self-host se
    # mettent à jour seuls. La revue éditoriale se fait au merge dans le repo
    # corpus (source canonique de confiance).
    corpus_sync_enabled: bool = Field(default=False, alias="CC_API_CORPUS_SYNC_ENABLED")
    corpus_sync_interval_hours: int = Field(
        default=24, alias="CC_API_CORPUS_SYNC_INTERVAL_HOURS"
    )
    corpus_sync_repo: str = Field(
        default="Consansclasse/class-consciousness-corpus",
        alias="CC_API_CORPUS_SYNC_REPO",
    )
    corpus_sync_ref: str = Field(default="main", alias="CC_API_CORPUS_SYNC_REF")
    # Glob (relatif à la racine du tarball extrait) des TEI canoniques à ingérer.
    # Strict 3 chiffres → exclut les variantes découpées (bilan-001-introduction…),
    # exactement comme l'ingestion prod du runbook.
    corpus_sync_glob: str = Field(
        default="**/bilan/bilan-[0-9][0-9][0-9].tei.xml",
        alias="CC_API_CORPUS_SYNC_GLOB",
    )
    # Jeton GitHub optionnel : relève le quota API de 60→5000 req/h. Inutile au
    # rythme par défaut (1 requête SHA / cycle, le tarball passe par le CDN
    # codeload hors-quota).
    corpus_sync_token: str | None = Field(
        default=None, alias="CC_API_CORPUS_SYNC_TOKEN"
    )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def smtp_configured(self) -> bool:
        """Vrai si un serveur SMTP est configuré ; sinon le magic-link est
        seulement journalisé (mode dev)."""
        return bool(self.smtp_host)

    @model_validator(mode="after")
    def _forbid_default_secret_outside_dev(self) -> "Settings":
        """Hors dev, le secret de session ne doit jamais rester le défaut : il
        est public (dépôt AGPL) — un cookie de session serait alors forgeable."""
        if self.env != "dev" and self.session_secret == _DEFAULT_SESSION_SECRET:
            raise ValueError(
                "CC_API_SESSION_SECRET doit être défini lorsque CC_API_ENV != dev"
            )
        return self


settings = Settings()

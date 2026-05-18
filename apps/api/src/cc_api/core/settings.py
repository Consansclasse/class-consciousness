# SPDX-License-Identifier: AGPL-3.0-or-later
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    # Sonnet 4.6 par défaut — Opus 4.7 est trop coûteux pour le volume RAG.
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")
    # Modèle du 2ᵉ passage « juge » qui vérifie l'ancrage sémantique (entailment)
    # de chaque phrase analytique. Sonnet 4.6 également — bon compromis
    # rigueur / coût pour ce contrôle.
    anthropic_judge_model: str = Field(
        default="claude-sonnet-4-6", alias="ANTHROPIC_JUDGE_MODEL"
    )

    # Stripe — paiement de la cotisation associative.
    # En dev : clés sk_test_… (sandbox Stripe) ou pointage vers stripe-mock.
    # En prod : sk_live_… avec asso vérifiée (SIRET + RNA + RIB).
    stripe_secret_key: str | None = Field(default=None, alias="STRIPE_SECRET_KEY")
    stripe_publishable_key: str | None = Field(default=None, alias="STRIPE_PUBLISHABLE_KEY")
    stripe_webhook_secret: str | None = Field(default=None, alias="STRIPE_WEBHOOK_SECRET")
    # Override de l'endpoint Stripe pour les tests d'intégration (stripe-mock).
    stripe_api_base: str | None = Field(default=None, alias="STRIPE_API_BASE")
    # Base URL publique du site web — pour construire success_url / cancel_url
    # transmises à Stripe Checkout.
    public_web_base: str = Field(default="http://localhost:3000", alias="PUBLIC_WEB_BASE")

    # Pipeline RAG : seuils de la règle d'or « aucune phrase sans citation vérifiée ».
    rag_k_retrieve: int = Field(default=40, alias="CC_API_RAG_K_RETRIEVE")
    # Sélection des passages transmis au LLM — `k` ADAPTATIF : on retient les
    # passages dont le score de rerank dépasse `rag_rerank_min_score`, borné
    # entre min et max. Une question large bien couverte → beaucoup de passages ;
    # une question étroite → peu. Si AUCUN passage n'atteint le seuil, la réponse
    # est refusée (`no_relevant_chunks`) : le corpus ne couvre pas la question.
    rag_rerank_min_score: float = Field(default=0.3, alias="CC_API_RAG_RERANK_MIN_SCORE")
    rag_k_rerank_min: int = Field(default=4, alias="CC_API_RAG_K_RERANK_MIN")
    rag_k_rerank_max: int = Field(default=6, alias="CC_API_RAG_K_RERANK_MAX")
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


settings = Settings()

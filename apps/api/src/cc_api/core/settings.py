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
    anthropic_model: str = Field(default="claude-opus-4-7", alias="ANTHROPIC_MODEL")

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
    rag_k_retrieve: int = Field(default=20, alias="CC_API_RAG_K_RETRIEVE")
    rag_k_rerank: int = Field(default=5, alias="CC_API_RAG_K_RERANK")
    rag_citation_fuzzy_threshold: int = Field(default=95, alias="CC_API_RAG_CITATION_FUZZY")
    # Mode partiel : si au moins 1 phrase est vérifiée et certaines ne le sont
    # pas, on expose les phrases vérifiées (200 + incomplete=true) au lieu de
    # refuser toute la réponse (422). Aucune phrase non vérifiée n'est exposée
    # — la règle d'or « aucune phrase sans citation » reste sauve.
    rag_partial_mode_enabled: bool = Field(default=True, alias="CC_API_RAG_PARTIAL_MODE")

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

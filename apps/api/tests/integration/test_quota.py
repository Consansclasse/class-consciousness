# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du quota d'usage de l'assistant RAG (Lot E).

DB et Redis sont de vrais testcontainers (règle « pas de mock »). `answer_question`
est substitué par un RagResult contrôlé : on teste le quota et la protection des
endpoints, pas le pipeline (couvert ailleurs).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from cc_api.clients.anthropic import GeneratedPhrase
from cc_api.models import Abonnement, AbonnementStatus, User
from cc_api.services.citation import CitationReport, CitationVerdict, SentenceVerdict
from cc_api.services.rag import RagResult


@pytest_asyncio.fixture
async def quota_env(
    monkeypatch: pytest.MonkeyPatch, migrated_db: str, redis_url: str
) -> AsyncIterator[None]:
    """DB + Redis pointés vers les testcontainers ; Redis vidé ; services RAG
    externes neutralisés (answer_question est substitué dans chaque test)."""
    from cc_api.clients import db as db_module
    from cc_api.clients import redis as redis_module
    from cc_api.core.settings import settings

    parsed = urlparse(migrated_db)
    monkeypatch.setattr(settings, "postgres_host", parsed.hostname or "localhost")
    monkeypatch.setattr(settings, "postgres_port", parsed.port or 5432)
    monkeypatch.setattr(settings, "postgres_user", parsed.username or "cc")
    monkeypatch.setattr(settings, "postgres_password", parsed.password or "cc")
    monkeypatch.setattr(settings, "postgres_db", (parsed.path or "/cc_test").lstrip("/"))
    monkeypatch.setattr(settings, "redis_url", redis_url)
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()
    redis_module.get_redis.cache_clear()
    await redis_module.get_redis().flushdb()
    for getter in (
        "get_qdrant",
        "get_embed_client",
        "get_rerank_client",
        "get_anthropic_client",
    ):
        monkeypatch.setattr(f"cc_api.routers.qa.{getter}", lambda: None)
    yield
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()
    redis_module.get_redis.cache_clear()


def _success_result(question: str) -> RagResult:
    """RagResult abouti minimal — le pipeline n'est pas exercé ici."""
    report = CitationReport(
        sentences=[
            SentenceVerdict(
                phrase=GeneratedPhrase(
                    texte="Phrase ancrée.", citations=["s:0"], citations_directes=[]
                ),
                paragraphe=0,
                verdict=CitationVerdict.SUPPORTED,
                best_score=100.0,
                reason="test",
            )
        ],
        all_verified=True,
        n_supported=1,
        n_rejected=0,
    )
    return RagResult(
        question=question,
        retrieved=[],
        reranked=[],
        answer="Phrase ancrée.",
        citation_report=report,
        refused_reason=None,
        model="claude-sonnet-4-6",
        latency_ms=100,
        latencies={},
    )


def _login(client: Any, email: str) -> None:
    """Ouvre une session pour `email` via le flux mot de passe (register → verify)."""
    reg = client.post(
        "/auth/register",
        json={"email": email, "password": "motdepasse-de-test", "consent_data": True},
    )
    token = parse_qs(urlparse(reg.json()["devLink"]).query)["token"][0]
    assert client.post("/auth/verify-email", json={"token": token}).status_code == 200


def _active_abonnement(user_id: int) -> Abonnement:
    """Abonnement pay-as-you-go actif, couvrant la date courante."""
    return Abonnement(
        user_id=user_id,
        stripe_customer_id="cus_test",
        stripe_subscription_id="sub_test",
        stripe_price_id="price_test",
        status=AbonnementStatus.ACTIVE,
        current_period_end=datetime.now(UTC) + timedelta(days=20),
    )


async def test_qa_requires_authentication(
    quota_env: None, clean_db: None, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """L'assistant n'est plus accessible anonymement : /qa sans session → 401."""

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)
    assert client.post("/qa", json={"question": "Anonyme ?"}).status_code == 401


async def test_quota_blocks_after_free_limit(
    quota_env: None, clean_db: None, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Quota gratuit (compte sans abonnement) : 2 requêtes passent, la 3ᵉ → 402."""

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    _login(client, "quota@example.org")
    assert client.post("/qa", json={"question": "Question un ?"}).status_code == 200
    assert client.post("/qa", json={"question": "Question deux ?"}).status_code == 200
    refused = client.post("/qa", json={"question": "Question trois ?"})
    assert refused.status_code == 402
    assert refused.json()["detail"]["error"] == "quota_exceeded"


async def test_quota_never_blocks_corpus(
    quota_env: None, clean_db: None, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """La lecture du corpus n'est jamais soumise au quota de l'assistant."""

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)
    _login(client, "lecture@example.org")
    for _ in range(4):  # épuise le quota RAG
        client.post("/qa", json={"question": "Une question quelconque ?"})

    assert client.get("/corpus").status_code == 200


async def test_payg_subscriber_unlimited_beyond_free_quota(
    quota_env: None,
    clean_db: None,
    client: Any,
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un abonné pay-as-you-go n'a plus de plafond au-delà du quota gratuit.

    L'enregistrement d'usage Stripe est best-effort : ici Stripe n'est pas
    configuré (`stripe_secret_key` absent), donc `_record_usage` échoue en
    silence (journalisé, compté) sans jamais bloquer la réponse. On vérifie
    qu'au-delà du quota gratuit (2), de nombreuses requêtes passent malgré tout.
    """

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    user = User(email="payg@example.org", consent_data_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    db_session.add(_active_abonnement(user.id))
    await db_session.commit()

    _login(client, "payg@example.org")
    for i in range(6):  # bien au-delà du quota gratuit (2) : aucun plafond
        res = client.post("/qa", json={"question": f"Question {i} ?"})
        assert res.status_code == 200, res.text


async def test_payg_daily_cap_blocks_runaway(
    quota_env: None,
    clean_db: None,
    client: Any,
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le plafond anti-runaway borne un abonné PAYG : au-delà du cap → 402."""
    from cc_api.core.settings import settings

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)
    # Quota gratuit 1, plafond de sécurité 3 → 3 requêtes passent, la 4ᵉ casse.
    monkeypatch.setattr(settings, "rag_free_quota_per_window", 1)
    monkeypatch.setattr(settings, "rag_payg_daily_cap", 3)

    user = User(email="runaway@example.org", consent_data_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    db_session.add(_active_abonnement(user.id))
    await db_session.commit()

    _login(client, "runaway@example.org")
    for i in range(3):
        assert client.post("/qa", json={"question": f"Q{i} ?"}).status_code == 200
    blocked = client.post("/qa", json={"question": "Q de trop ?"})
    assert blocked.status_code == 402
    assert blocked.json()["detail"]["error"] == "payg_daily_cap"


async def test_abonnement_checkout_requires_auth(
    quota_env: None, clean_db: None, client: Any
) -> None:
    """POST /abonnements/checkout sans session ouverte → 401."""
    assert client.post("/abonnements/checkout").status_code == 401


async def test_abonnement_checkout_unconfigured_returns_503(
    quota_env: None, clean_db: None, client: Any
) -> None:
    """Connecté mais Stripe non configuré (clé ou price absents) → 503, pas 500."""
    _login(client, "client@example.org")
    res = client.post("/abonnements/checkout")
    assert res.status_code == 503

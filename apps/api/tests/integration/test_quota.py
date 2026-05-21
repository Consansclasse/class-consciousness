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
    """Ouvre une session pour `email` via le flux magic-link."""
    req = client.post("/auth/request-link", json={"email": email})
    token = parse_qs(urlparse(req.json()["devMagicLink"]).query)["token"][0]
    assert client.post("/auth/verify", json={"token": token}).status_code == 200


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


async def test_quota_bypassed_for_active_subscriber(
    quota_env: None,
    clean_db: None,
    client: Any,
    db_session: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un abonné actif dépasse le quota gratuit (cap anti-abus plus élevé)."""

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    user = User(email="abonne@example.org", consent_data_at=datetime.now(UTC))
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        Abonnement(
            user_id=user.id,
            stripe_customer_id="cus_test",
            stripe_subscription_id="sub_test",
            stripe_price_id="price_test",
            status=AbonnementStatus.ACTIVE,
            current_period_end=datetime.now(UTC) + timedelta(days=20),
        )
    )
    await db_session.commit()

    _login(client, "abonne@example.org")
    for i in range(3):  # au-delà du quota gratuit (2), sous le cap abonné (6)
        res = client.post("/qa", json={"question": f"Question {i} ?"})
        assert res.status_code == 200, res.text


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

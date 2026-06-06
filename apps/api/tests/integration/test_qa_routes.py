# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration de l'endpoint /qa — persistance des interactions RAG.

Le pipeline RAG lui-même est couvert par test_pipeline_rag.py. Ici on valide le
contrat du lot « closed-loop » : tout appel à /qa — réponse aboutie ou refus —
écrit une ligne `rag_interactions` fidèle au RagResult produit.

`answer_question` est substitué par un RagResult contrôlé (le pipeline n'est pas
rejoué, ni les services externes appelés) ; la base est un vrai testcontainer
Postgres, jamais mockée — conforme à la règle « pas de mock DB ».
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from cc_api.clients.anthropic import GeneratedPhrase, GenerationUsage
from cc_api.core.settings import settings
from cc_api.models import RagFeedback, RagFeedbackKind, RagInteraction, User
from cc_api.services.citation import CitationReport, CitationVerdict, SentenceVerdict
from cc_api.services.rag import RagResult
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def qa_env(
    monkeypatch: pytest.MonkeyPatch, migrated_db: str, redis_url: str
) -> AsyncIterator[str]:
    """Pointe la DB applicative et Redis vers les testcontainers ; neutralise
    les services externes du pipeline — `answer_question` étant substitué dans
    chaque test, Qdrant / embed / rerank / Anthropic ne sont jamais sollicités.

    Redis est flushé en début de fixture : sans cela le compteur de quota fuit
    entre tests `/qa` (le testcontainer Redis est session-scoped) et un test
    tardif reçoit 402 au lieu de la réponse attendue.
    """
    from cc_api.clients import db as db_module
    from cc_api.clients import redis as redis_module

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

    yield migrated_db
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()
    redis_module.get_redis.cache_clear()


def _verdict(texte: str, citations: list[str], verdict: CitationVerdict) -> SentenceVerdict:
    return SentenceVerdict(
        phrase=GeneratedPhrase(texte=texte, citations=citations, citations_directes=[]),
        paragraphe=0,
        verdict=verdict,
        best_score=100.0,
        reason="test",
    )


def _success_result(question: str) -> RagResult:
    """RagResult abouti : une phrase SUPPORTED, génération + juge facturés."""
    report = CitationReport(
        sentences=[_verdict("Une phrase ancrée.", ["bilan-1/art:0"], CitationVerdict.SUPPORTED)],
        all_verified=True,
        n_supported=1,
        n_rejected=0,
        judge_usage=GenerationUsage(120, 40, 0, 0),
    )
    return RagResult(
        question=question,
        retrieved=[],
        reranked=[],
        answer="Une phrase ancrée.",
        citation_report=report,
        refused_reason=None,
        model="claude-sonnet-4-6",
        latency_ms=4200,
        latencies={"generate_ms": 3800, "verify_ms": 300},
        generation_usage=GenerationUsage(900, 350, 0, 600),
    )


def _refused_result(question: str) -> RagResult:
    """RagResult refusé en amont : aucun chunk retrouvé, pas de génération."""
    return RagResult(
        question=question,
        retrieved=[],
        reranked=[],
        answer=None,
        citation_report=None,
        refused_reason="no_chunks_retrieved",
        model="claude-sonnet-4-6",
        latency_ms=110,
        latencies={"embed_ms": 50, "qdrant_ms": 60},
    )


async def _interactions(db_url: str) -> list[RagInteraction]:
    """Relit toutes les interactions via une session fraîche (le router commit
    sur sa propre session)."""
    engine = create_async_engine(db_url, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            rows = await session.execute(select(RagInteraction).order_by(RagInteraction.id))
            return list(rows.scalars().all())
    finally:
        await engine.dispose()


async def _feedbacks(db_url: str) -> list[RagFeedback]:
    """Relit tous les feedbacks via une session fraîche."""
    engine = create_async_engine(db_url, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            rows = await session.execute(select(RagFeedback).order_by(RagFeedback.id))
            return list(rows.scalars().all())
    finally:
        await engine.dispose()


async def _seed_interaction(session: Any, user_id: int | None = None) -> int:
    """Insère une RagInteraction minimale et renvoie son id.

    `user_id` rattache l'interaction à un compte — requis pour les tests de
    feedback depuis le verrouillage par compte (la propriété est vérifiée).
    """
    interaction = RagInteraction(
        user_id=user_id,
        question="Question préexistante pour le feedback.",
        answer="Réponse ancrée.",
        incomplete=False,
        model="claude-sonnet-4-6",
        latency_ms=100,
        latencies={},
        usage={},
        sentences=[],
        cited_source_ids=[],
        cited_chunks=[],
        retrieval_count=0,
        rerank_count=0,
    )
    session.add(interaction)
    await session.commit()
    return interaction.id


async def _user_id(db_url: str, email: str) -> int:
    """Relit l'id du compte créé par le flux magic-link."""
    engine = create_async_engine(db_url, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as session:
            uid = await session.scalar(select(User.id).where(User.email == email))
            assert uid is not None
            return uid
    finally:
        await engine.dispose()


async def test_qa_persists_interaction_on_success(
    qa_env: str,
    clean_db: None,
    client: Any,
    login: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une réponse aboutie écrit une ligne rag_interactions fidèle au RagResult,
    rattachée au compte connecté et à un fil de conversation."""
    question = "Que dit le corpus sur la lutte des classes ?"

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    login(client, "militante@example.org")
    res = client.post("/qa", json={"question": question})
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body["conversationId"], int)

    uid = await _user_id(qa_env, "militante@example.org")
    rows = await _interactions(qa_env)
    assert len(rows) == 1
    row = rows[0]
    assert row.question == question
    assert row.answer == "Une phrase ancrée."
    assert row.refused_reason is None
    assert row.incomplete is False
    assert row.model == "claude-sonnet-4-6"
    assert row.latency_ms == 4200
    assert row.latencies == {"generate_ms": 3800, "verify_ms": 300}
    assert row.usage["generation"]["input_tokens"] == 900
    assert row.usage["generation"]["cache_read_input_tokens"] == 600
    assert row.usage["generation"]["model"] == "claude-sonnet-4-6"
    assert row.usage["judge"]["input_tokens"] == 120
    assert row.usage["judge"]["model"] == settings.anthropic_judge_model
    assert len(row.sentences) == 1
    assert row.sentences[0]["verdict"] == "SUPPORTED"
    assert row.sentences[0]["verified"] is True
    assert row.cited_source_ids == ["bilan-1/art:0"]
    assert row.cited_chunks == []  # reranked vide dans le RagResult de test
    assert row.user_id == uid
    assert row.conversation_id == body["conversationId"]
    assert row.ip_hash is not None
    assert len(row.ip_hash) == 64


async def test_qa_requires_authentication(
    qa_env: str, clean_db: None, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sans compte, l'assistant est inaccessible : /qa → 401, aucune ligne écrite."""

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    res = client.post("/qa", json={"question": "Une question sans session ?"})
    assert res.status_code == 401
    assert await _interactions(qa_env) == []


async def test_qa_links_same_conversation(
    qa_env: str,
    clean_db: None,
    client: Any,
    login: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deux questions avec le même conversationId tombent dans le même fil."""

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    login(client, "fil@example.org")
    first = client.post("/qa", json={"question": "Première question du fil ?"})
    conv_id = first.json()["conversationId"]
    second = client.post(
        "/qa",
        json={"question": "Deuxième question du fil ?", "conversationId": conv_id},
    )
    assert second.status_code == 200, second.text
    assert second.json()["conversationId"] == conv_id

    rows = await _interactions(qa_env)
    assert [r.conversation_id for r in rows] == [conv_id, conv_id]


async def test_qa_persists_interaction_on_refusal(
    qa_env: str,
    clean_db: None,
    client: Any,
    login: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un refus 422 écrit aussi une ligne — un refus est un artefact à tracer."""
    question = "Une question dont les sources sont totalement absentes du corpus ?"

    async def _fake(q: str, **_: Any) -> RagResult:
        return _refused_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    login(client, "refus@example.org")
    res = client.post("/qa", json={"question": question})
    assert res.status_code == 422, res.text

    rows = await _interactions(qa_env)
    assert len(rows) == 1
    row = rows[0]
    assert row.question == question
    assert row.answer is None
    assert row.refused_reason == "no_chunks_retrieved"
    assert row.incomplete is False
    assert row.sentences == []
    assert row.cited_source_ids == []
    assert row.usage["generation"]["input_tokens"] == 0
    assert row.usage["judge"]["input_tokens"] == 0


async def test_qa_response_exposes_interaction_id(
    qa_env: str,
    clean_db: None,
    client: Any,
    login: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La réponse /qa porte interactionId — socle du rattachement d'un feedback."""

    async def _fake(q: str, **_: Any) -> RagResult:
        return _success_result(q)

    monkeypatch.setattr("cc_api.routers.qa.answer_question", _fake)

    login(client, "feedback@example.org")
    res = client.post("/qa", json={"question": "Une question pour le feedback ?"})
    assert res.status_code == 200, res.text
    interaction_id = res.json()["interactionId"]
    assert isinstance(interaction_id, int)

    rows = await _interactions(qa_env)
    assert [r.id for r in rows] == [interaction_id]


async def test_feedback_up_is_recorded(
    qa_env: str, clean_db: None, client: Any, db_session: Any, login: Any
) -> None:
    """Un pouce haut crée une ligne rag_feedback rattachée à l'interaction."""
    login(client, "pouce@example.org")
    uid = await _user_id(qa_env, "pouce@example.org")
    interaction_id = await _seed_interaction(db_session, user_id=uid)

    res = client.post(f"/qa/interactions/{interaction_id}/feedback", json={"kind": "UP"})
    assert res.status_code == 201, res.text

    rows = await _feedbacks(qa_env)
    assert len(rows) == 1
    assert rows[0].rag_interaction_id == interaction_id
    assert rows[0].kind == RagFeedbackKind.UP
    assert rows[0].comment is None
    assert rows[0].ip_hash is not None


async def test_feedback_flag_carries_comment(
    qa_env: str, clean_db: None, client: Any, db_session: Any, login: Any
) -> None:
    """Un signalement (FLAG) transporte le commentaire du lecteur."""
    login(client, "signal@example.org")
    uid = await _user_id(qa_env, "signal@example.org")
    interaction_id = await _seed_interaction(db_session, user_id=uid)

    res = client.post(
        f"/qa/interactions/{interaction_id}/feedback",
        json={"kind": "FLAG", "comment": "La citation 2 inverse le sens du passage."},
    )
    assert res.status_code == 201, res.text

    rows = await _feedbacks(qa_env)
    assert len(rows) == 1
    assert rows[0].kind == RagFeedbackKind.FLAG
    assert rows[0].comment == "La citation 2 inverse le sens du passage."


async def test_feedback_requires_authentication(
    qa_env: str, clean_db: None, client: Any, db_session: Any
) -> None:
    """Un feedback sans session est refusé (401)."""
    interaction_id = await _seed_interaction(db_session)
    res = client.post(f"/qa/interactions/{interaction_id}/feedback", json={"kind": "UP"})
    assert res.status_code == 401
    assert await _feedbacks(qa_env) == []


async def test_feedback_on_other_users_interaction_returns_404(
    qa_env: str, clean_db: None, client: Any, db_session: Any, login: Any
) -> None:
    """Un feedback sur l'interaction d'autrui est refusé (404), sans ligne — on
    ne révèle pas l'existence des interactions d'un autre compte."""
    other = User(email="autrui@example.org")
    db_session.add(other)
    await db_session.flush()
    interaction_id = await _seed_interaction(db_session, user_id=other.id)

    login(client, "intrus@example.org")
    res = client.post(f"/qa/interactions/{interaction_id}/feedback", json={"kind": "DOWN"})
    assert res.status_code == 404
    assert await _feedbacks(qa_env) == []


async def test_feedback_unknown_interaction_returns_404(
    qa_env: str, clean_db: None, client: Any, login: Any
) -> None:
    """Un feedback sur une interaction inexistante est refusé (404), sans ligne."""
    login(client, "inconnu@example.org")
    res = client.post("/qa/interactions/999999/feedback", json={"kind": "DOWN"})
    assert res.status_code == 404

    rows = await _feedbacks(qa_env)
    assert rows == []

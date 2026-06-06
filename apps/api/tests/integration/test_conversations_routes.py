# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests d'intégration du router /conversations — historique des fils RAG.

DB = testcontainer Postgres réel (règle « pas de mock »). Les fils et messages
sont semés directement en base ; on vérifie le contrat HTTP : liste, détail
réaffichable, renommage, suppression, propriété (404 sur le fil d'autrui),
authentification (401 sans session).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlparse

import pytest
import pytest_asyncio
from cc_api.models import Conversation, RagInteraction, User


@pytest_asyncio.fixture
async def conv_env(monkeypatch: pytest.MonkeyPatch, migrated_db: str) -> AsyncIterator[str]:
    """Pointe la DB applicative vers le testcontainer et purge les caches."""
    from cc_api.clients import db as db_module
    from cc_api.core.settings import settings

    parsed = urlparse(migrated_db)
    monkeypatch.setattr(settings, "postgres_host", parsed.hostname or "localhost")
    monkeypatch.setattr(settings, "postgres_port", parsed.port or 5432)
    monkeypatch.setattr(settings, "postgres_user", parsed.username or "cc")
    monkeypatch.setattr(settings, "postgres_password", parsed.password or "cc")
    monkeypatch.setattr(settings, "postgres_db", (parsed.path or "/cc_test").lstrip("/"))
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()
    yield migrated_db
    db_module.get_engine.cache_clear()
    db_module.get_session_maker.cache_clear()


async def _seed_conversation(session: Any, user_id: int, title: str = "Fil semé") -> int:
    conv = Conversation(user_id=user_id, title=title)
    session.add(conv)
    await session.flush()
    cid = conv.id
    await session.commit()
    return cid


async def _seed_message(session: Any, user_id: int, conversation_id: int) -> int:
    interaction = RagInteraction(
        user_id=user_id,
        conversation_id=conversation_id,
        question="Que dit le corpus sur l'État ?",
        answer="L'État est un instrument de classe.",
        incomplete=False,
        model="claude-sonnet-4-6",
        latency_ms=100,
        latencies={},
        usage={},
        sentences=[
            {
                "text": "L'État est un instrument de classe.",
                "verdict": "SUPPORTED",
                "verified": True,
                "citations": ["bilan-1/etat:0"],
                "paragraphe": 0,
                "best_score": 100.0,
                "reason": "test",
            }
        ],
        cited_source_ids=["bilan-1/etat:0"],
        cited_chunks=[
            {
                "sourceId": "bilan-1/etat:0",
                "issueSlug": "bilan-1",
                "issueArk": "ark:/x/i1",
                "articleSlug": "etat",
                "articleArk": "ark:/x/a1",
                "articleTitle": "Sur l'État",
                "authorName": "Bilan",
                "chunkIdx": 0,
                "charStart": 0,
                "charEnd": 40,
                "quotedText": "L'État est un instrument de classe.",
                "retrievalScore": 0.9,
                "rerankScore": 0.8,
            }
        ],
        retrieval_count=1,
        rerank_count=1,
    )
    session.add(interaction)
    await session.commit()
    return interaction.id


async def _uid(session: Any, email: str) -> int:
    """Id du compte `email` — récupéré s'il existe (créé par `login`), sinon créé."""
    from sqlalchemy import select

    existing = await session.scalar(select(User.id).where(User.email == email))
    if existing is not None:
        return existing
    user = User(email=email)
    session.add(user)
    await session.flush()
    uid = user.id
    await session.commit()
    return uid


def test_list_requires_authentication(conv_env: str, clean_db: None, client: Any) -> None:
    """GET /conversations sans session → 401."""
    assert client.get("/conversations").status_code == 401


async def test_create_then_list(conv_env: str, clean_db: None, client: Any, login: Any) -> None:
    """Un fil créé apparaît dans la liste de l'utilisateur."""
    login(client, "creatrice@example.org")
    created = client.post("/conversations")
    assert created.status_code == 201, created.text
    cid = created.json()["id"]

    listed = client.get("/conversations")
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [cid]


async def test_get_detail_replays_messages(
    conv_env: str, clean_db: None, client: Any, db_session: Any, login: Any
) -> None:
    """Le détail d'un fil renvoie ses messages réaffichables (question + sources)."""
    login(client, "fil@example.org")
    uid = await _uid(db_session, "fil@example.org")
    cid = await _seed_conversation(db_session, uid)
    await _seed_message(db_session, uid, cid)

    res = client.get(f"/conversations/{cid}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == cid
    assert len(body["messages"]) == 1
    msg = body["messages"][0]
    assert msg["question"] == "Que dit le corpus sur l'État ?"
    assert msg["sentences"][0]["verified"] is True
    assert msg["citedChunks"][0]["articleTitle"] == "Sur l'État"


async def test_rename_conversation(conv_env: str, clean_db: None, client: Any, login: Any) -> None:
    """PATCH renomme un fil possédé."""
    login(client, "renomme@example.org")
    cid = client.post("/conversations").json()["id"]

    res = client.patch(f"/conversations/{cid}", json={"title": "Sur la valeur"})
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Sur la valeur"


async def test_delete_conversation_hides_it(
    conv_env: str, clean_db: None, client: Any, login: Any
) -> None:
    """DELETE retire le fil de la liste et le rend introuvable (404)."""
    login(client, "supprime@example.org")
    cid = client.post("/conversations").json()["id"]

    assert client.delete(f"/conversations/{cid}").status_code == 204
    assert client.get("/conversations").json() == []
    assert client.get(f"/conversations/{cid}").status_code == 404


async def test_cannot_access_other_users_conversation(
    conv_env: str, clean_db: None, client: Any, db_session: Any, login: Any
) -> None:
    """Le fil d'autrui est introuvable (404) — propriété stricte."""
    other = await _uid(db_session, "autre@example.org")
    cid = await _seed_conversation(db_session, other)

    login(client, "intruse@example.org")
    assert client.get(f"/conversations/{cid}").status_code == 404
    assert client.patch(f"/conversations/{cid}", json={"title": "x"}).status_code == 404
    assert client.delete(f"/conversations/{cid}").status_code == 404

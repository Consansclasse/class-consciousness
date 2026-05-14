# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures pytest partagées — testcontainers Postgres+Qdrant éphémères.

Pas de mocks. Pas de stubs. Vrais services jetables par session pytest.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest
import pytest_asyncio


@pytest.fixture(scope="session")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """URL Postgres testcontainer (skip si testcontainers indisponible)."""
    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed — install via apps/api dev extras")

    with PostgresContainer("postgres:17-alpine", username="cc", password="cc", dbname="cc_test") as pg:
        url = pg.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        yield url


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """URL Qdrant testcontainer."""
    try:
        from testcontainers.qdrant import QdrantContainer
    except ImportError:
        pytest.skip("testcontainers[qdrant] not installed")

    with QdrantContainer("qdrant/qdrant:latest") as q:
        yield f"http://{q.get_container_host_ip()}:{q.get_exposed_port(6333)}"


@pytest_asyncio.fixture
async def db_session(postgres_url: str) -> AsyncIterator[Any]:
    """Session SQLAlchemy avec rollback automatique à la fin du test."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(postgres_url, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Instance FastAPI avec env de test (CC_API_ENV=dev forcé)."""
    monkeypatch.setenv("CC_API_ENV", "dev")
    from cc_api.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
def client(app: Any) -> Iterator[Any]:
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c

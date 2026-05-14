# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures pytest partagées — testcontainers Postgres+Qdrant éphémères.

Pas de mocks pour la DB ou Qdrant. Voyage AI est testé via httpx.MockTransport
(transport, pas mock métier), avec des embeddings déterministes par hash du
texte (unicité garantie pour le self-test).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import pytest
import pytest_asyncio

REPO_ROOT = Path(__file__).resolve().parents[3]
API_DIR = REPO_ROOT / "apps" / "api"
CANONICAL_TEI = REPO_ROOT / "corpus" / "_seed" / "bilan-001.tei.xml"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    """URL Postgres testcontainer (skip si testcontainers indisponible).

    Wait strategy via `LogMessageWaitStrategy` : la wait strategy par défaut de
    testcontainers 4.x (ExecWaitStrategy `psql --host 127.0.0.1`) ne fonctionne
    pas quand le host a déjà un Postgres système sur 5432. Le log-based wait
    scanne stdout du container et est insensible aux conflits de ports host.
    Postgres émet « database system is ready » 2 fois ; on attend la 2e
    occurrence (`times=2`) pour s'assurer que l'init est terminé.
    """
    try:
        from testcontainers.core.wait_strategies import LogMessageWaitStrategy
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] not installed — install via apps/api dev extras")

    container = PostgresContainer(
        "postgres:17-alpine", username="cc", password="cc", dbname="cc_test"
    )
    container.waiting_for(
        LogMessageWaitStrategy("database system is ready to accept connections", times=2)
    )
    container.start()
    try:
        url = container.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        yield url
    finally:
        container.stop()


@pytest.fixture(scope="session")
def qdrant_url() -> Iterator[str]:
    """URL Qdrant testcontainer (HTTP)."""
    try:
        from testcontainers.qdrant import QdrantContainer
    except ImportError:
        pytest.skip("testcontainers[qdrant] not installed")

    with QdrantContainer("qdrant/qdrant:latest") as q:
        yield f"http://{q.get_container_host_ip()}:{q.get_exposed_port(6333)}"


@pytest.fixture(scope="session")
def migrated_db(postgres_url: str) -> str:
    """Applique `alembic upgrade head` une fois par session sur le testcontainer."""
    parsed = urlparse(postgres_url)
    env = os.environ.copy()
    env["POSTGRES_HOST"] = parsed.hostname or "localhost"
    env["POSTGRES_PORT"] = str(parsed.port or 5432)
    env["POSTGRES_USER"] = parsed.username or "cc"
    env["POSTGRES_PASSWORD"] = parsed.password or "cc"
    env["POSTGRES_DB"] = (parsed.path or "/cc_test").lstrip("/")
    proc = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        env=env,
        cwd=str(API_DIR),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(f"alembic upgrade head failed.\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}")
    return postgres_url


@pytest_asyncio.fixture
async def clean_db(migrated_db: str) -> AsyncIterator[None]:
    """Vide les tables business avant chaque test (isolation function-scope)."""
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(migrated_db, echo=False)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql("TRUNCATE chunks, works, authors RESTART IDENTITY CASCADE")
    finally:
        await engine.dispose()
    yield


@pytest_asyncio.fixture
async def db_session(migrated_db: str) -> AsyncIterator[Any]:
    """Session AsyncSession liée au testcontainer (function-scope)."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    engine = create_async_engine(migrated_db, echo=False)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def qdrant_client(qdrant_url: str) -> AsyncIterator[Any]:
    """AsyncQdrantClient function-scope avec warmup + close propre."""
    from qdrant_client import AsyncQdrantClient

    client = AsyncQdrantClient(url=qdrant_url, timeout=30, prefer_grpc=False)
    # Warmup : vérifie connectivité avant de yield (force la première connexion HTTP)
    await client.get_collections()
    try:
        yield client
    finally:
        await client.close()


@pytest_asyncio.fixture
async def clean_qdrant(qdrant_client: Any) -> AsyncIterator[None]:
    """Drop la collection `bilan` avant chaque test pour isolation."""
    cols = await qdrant_client.get_collections()
    if "bilan" in {c.name for c in cols.collections}:
        await qdrant_client.delete_collection("bilan")
    yield


def _deterministic_embedding(text: str, dim: int = 1024) -> list[float]:
    """Embedding déterministe : hash → vecteur normalisé L2 unique par texte."""
    h = hashlib.sha256(text.encode("utf-8")).digest()
    raw = (h * (dim * 4 // len(h) + 1))[: dim * 4]
    floats = list(struct.unpack(f"{dim}f", raw))
    floats = [x if math.isfinite(x) else 0.001 for x in floats]
    norm = math.sqrt(sum(x * x for x in floats)) or 1.0
    return [x / norm for x in floats]


@pytest_asyncio.fixture
async def mock_voyage_client() -> AsyncIterator[Any]:
    """VoyageClient avec httpx.MockTransport qui produit des embeddings déterministes."""
    from cc_api.clients.voyage import VoyageClient

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": _deterministic_embedding(t), "index": i}
                    for i, t in enumerate(body["input"])
                ],
                "model": body["model"],
                "usage": {"total_tokens": sum(len(t) for t in body["input"])},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        vc = VoyageClient(api_key="sk-mock", client=http_client, backoff_base=0)
        yield vc


@pytest.fixture
def canonical_tei_path() -> Path:
    assert CANONICAL_TEI.exists(), f"fixture canonique absente : {CANONICAL_TEI}"
    return CANONICAL_TEI


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

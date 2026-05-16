# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test verrou anti-drift : la migration Alembic appliquée correspond à Base.metadata.

Ce test garantit qu'on ne peut pas, par inadvertance, ajouter un modèle SQLAlchemy
sans la migration correspondante (ou inversement). Il applique `alembic upgrade head`
sur un testcontainer Postgres frais, puis reflect le schéma et le compare à
`Base.metadata.tables`.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlparse

import pytest
from cc_api.models import Base
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

REPO_ROOT = Path(__file__).resolve().parents[4]
API_DIR = REPO_ROOT / "apps" / "api"
ALEMBIC_INI = API_DIR / "alembic.ini"
ALEMBIC_DIR = API_DIR / "alembic"


def _alembic_env(postgres_url: str) -> dict[str, str]:
    parsed = urlparse(postgres_url)
    env = os.environ.copy()
    env["POSTGRES_HOST"] = parsed.hostname or "localhost"
    env["POSTGRES_PORT"] = str(parsed.port or 5432)
    env["POSTGRES_USER"] = parsed.username or "cc"
    env["POSTGRES_PASSWORD"] = parsed.password or "cc"
    env["POSTGRES_DB"] = (parsed.path or "/cc_test").lstrip("/")
    return env


def _run_alembic(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "alembic", *args],
        env=env,
        cwd=str(API_DIR),
        capture_output=True,
        text=True,
        check=False,
    )


async def test_alembic_upgrade_head_matches_models(alembic_pg: str) -> None:
    """Apply migrations, reflect, compare tables + colonnes à Base.metadata."""
    env = _alembic_env(alembic_pg)
    proc = _run_alembic(["upgrade", "head"], env)
    assert proc.returncode == 0, (
        f"alembic upgrade head a échoué.\nSTDOUT={proc.stdout}\nSTDERR={proc.stderr}"
    )

    engine = create_async_engine(alembic_pg, echo=False)
    try:
        async with engine.connect() as conn:
            db_state: dict[str, set[str]] = await conn.run_sync(
                lambda sync_conn: {
                    t: {c["name"] for c in inspect(sync_conn).get_columns(t)}
                    for t in inspect(sync_conn).get_table_names()
                }
            )
    finally:
        await engine.dispose()

    expected_tables = set(Base.metadata.tables.keys())
    actual_tables = set(db_state.keys()) - {"alembic_version"}
    missing = expected_tables - actual_tables
    extra = actual_tables - expected_tables
    assert not missing, f"tables manquantes dans la migration : {missing}"
    assert not extra, f"tables superflues en DB (modèle absent ?) : {extra}"

    for table_name in expected_tables:
        model_cols = set(Base.metadata.tables[table_name].columns.keys())
        db_cols = db_state[table_name]
        col_missing = model_cols - db_cols
        col_extra = db_cols - model_cols
        assert not col_missing, f"colonnes manquantes dans {table_name} : {col_missing}"
        assert not col_extra, f"colonnes superflues dans {table_name} : {col_extra}"


async def test_alembic_downgrade_drops_all_tables(alembic_pg: str) -> None:
    """Apply puis downgrade base : toutes les tables disparaissent."""
    env = _alembic_env(alembic_pg)
    up = _run_alembic(["upgrade", "head"], env)
    assert up.returncode == 0, up.stderr

    down = _run_alembic(["downgrade", "base"], env)
    assert down.returncode == 0, down.stderr

    engine = create_async_engine(alembic_pg, echo=False)
    try:
        async with engine.connect() as conn:
            remaining: list[str] = await conn.run_sync(
                lambda sync_conn: inspect(sync_conn).get_table_names()
            )
    finally:
        await engine.dispose()

    # Seules les tables système Alembic peuvent rester
    business_tables = [t for t in remaining if t in Base.metadata.tables]
    assert business_tables == [], f"tables non droppées : {business_tables}"


@pytest.fixture(scope="module")
def alembic_pg() -> Iterator[str]:
    """Conteneur Postgres DÉDIÉ aux tests de migration.

    Ces tests droppent/recréent le schéma et downgradent jusqu'à `base` : ils
    NE DOIVENT PAS partager le testcontainer `postgres_url` (session-scoped) du
    reste de la suite, sinon ils détruisent le schéma migré que les autres
    fichiers de tests attendent (`clean_db` → « relation chunks does not exist »).
    """
    try:
        from testcontainers.core.wait_strategies import LogMessageWaitStrategy
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("testcontainers[postgres] non installé")

    container = PostgresContainer(
        "postgres:17-alpine", username="cc", password="cc", dbname="cc_test"
    )
    container.waiting_for(
        LogMessageWaitStrategy(
            "database system is ready to accept connections", times=2
        ).with_startup_timeout(240)
    )
    container.start()
    try:
        yield container.get_connection_url().replace(
            "postgresql+psycopg2", "postgresql+asyncpg"
        )
    finally:
        container.stop()


@pytest.fixture(autouse=True)
async def _reset_db(alembic_pg: str) -> None:
    """Drop schema public + recreate avant chaque test pour isoler les migrations."""
    engine = create_async_engine(alembic_pg, echo=False, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql("DROP SCHEMA public CASCADE")
            await conn.exec_driver_sql("CREATE SCHEMA public")
    finally:
        await engine.dispose()

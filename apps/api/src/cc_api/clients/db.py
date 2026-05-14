# SPDX-License-Identifier: AGPL-3.0-or-later
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from cc_api.core.settings import settings


@lru_cache(maxsize=1)
def get_engine() -> AsyncEngine:
    return create_async_engine(settings.postgres_dsn, echo=False, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_maker() -> async_sessionmaker:
    return async_sessionmaker(get_engine(), expire_on_commit=False)

# SPDX-License-Identifier: AGPL-3.0-or-later
from functools import lru_cache

from redis.asyncio import Redis, from_url

from cc_api.core.settings import settings


@lru_cache(maxsize=1)
def get_redis() -> Redis:
    return from_url(settings.redis_url, decode_responses=True)

# SPDX-License-Identifier: AGPL-3.0-or-later
from functools import lru_cache

from qdrant_client import AsyncQdrantClient

from cc_api.core.settings import settings


@lru_cache(maxsize=1)
def get_qdrant() -> AsyncQdrantClient:
    return AsyncQdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)

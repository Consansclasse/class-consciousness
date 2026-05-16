# SPDX-License-Identifier: AGPL-3.0-or-later
from functools import lru_cache

from qdrant_client import AsyncQdrantClient

from cc_api.core.settings import settings


@lru_cache(maxsize=1)
def get_qdrant() -> AsyncQdrantClient:
    # timeout 120s : pendant l'ingest, l'embedding GPU d'un article peut prendre
    # plusieurs dizaines de secondes (serveur cc-embed). Avec un timeout client
    # par défaut de 5s, la connexion HTTP keep-alive vers Qdrant serait
    # considérée morte et la requête suivante lèverait ResponseHandlingException.
    return AsyncQdrantClient(
        url=settings.qdrant_url, api_key=settings.qdrant_api_key, timeout=120
    )

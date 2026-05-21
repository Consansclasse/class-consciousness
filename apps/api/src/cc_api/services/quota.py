# SPDX-License-Identifier: AGPL-3.0-or-later
"""Quota d'usage de l'assistant RAG — compteur Redis à fenêtre glissante.

Le quota est *vérifié* avant la requête (`peek_quota`, sans incrément) et
*consommé* seulement après une génération réussie (`consume_quota`) : une panne
ou un refus en amont ne doit jamais coûter une requête à l'utilisateur.

Fenêtre glissante de 24 h : `consume_quota` crée la clé avec son TTL en une
opération atomique (`SET … EX … NX`) puis l'incrémente — un crash ne peut donc
pas laisser une clé sans expiration (pas de blocage permanent). La clé expire
24 h après la première requête de la fenêtre.

Le quota porte UNIQUEMENT sur l'assistant RAG (coûteux en calcul) ; la lecture
du corpus reste libre. Un abonné actif bénéficie d'un cap anti-abus plus élevé.
"""

from __future__ import annotations

from dataclasses import dataclass

from cc_api.clients.redis import get_redis
from cc_api.core.logging import get_logger
from cc_api.core.metrics import rag_quota_redis_errors_total
from cc_api.core.settings import settings

log = get_logger(__name__)

_KEY_PREFIX = "rag:quota:"


@dataclass(frozen=True)
class QuotaState:
    """Issue d'une vérification de quota."""

    allowed: bool
    limit: int
    retry_after_s: int  # TTL résiduel avant réinitialisation ; 0 si autorisé


def _key(identity: str) -> str:
    return f"{_KEY_PREFIX}{identity}"


async def peek_quota(identity: str, *, limit: int) -> QuotaState:
    """Indique si une requête passerait — SANS consommer le quota.

    Fail-open : une panne Redis laisse passer (le quota protège le coût, pas la
    sécurité) ; l'incident est journalisé et compté (`cc_rag_quota_redis_errors`).
    """
    try:
        redis = get_redis()
        raw = await redis.get(_key(identity))
        used = int(raw) if raw is not None else 0
        if used < limit:
            return QuotaState(allowed=True, limit=limit, retry_after_s=0)
        ttl = await redis.ttl(_key(identity))
        return QuotaState(allowed=False, limit=limit, retry_after_s=max(ttl, 0))
    except Exception as exc:
        log.warning("quota.redis_unavailable", op="peek", error=str(exc))
        rag_quota_redis_errors_total.inc()
        return QuotaState(allowed=True, limit=limit, retry_after_s=0)


async def consume_quota(identity: str) -> None:
    """Consomme une unité de quota — à appeler APRÈS une génération réussie.

    `SET … EX … NX` pose la clé et son TTL en une seule opération atomique :
    aucun crash ne peut laisser une clé sans expiration. Fail-open silencieux
    (journalisé, compté) sur panne Redis.
    """
    try:
        redis = get_redis()
        window_s = settings.rag_quota_window_hours * 3600
        await redis.set(_key(identity), 0, ex=window_s, nx=True)
        await redis.incr(_key(identity))
    except Exception as exc:
        log.warning("quota.redis_unavailable", op="consume", error=str(exc))
        rag_quota_redis_errors_total.inc()

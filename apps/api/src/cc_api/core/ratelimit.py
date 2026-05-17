# SPDX-License-Identifier: AGPL-3.0-or-later
"""Limiteur de débit partagé — slowapi.

Un seul `Limiter` pour toute l'app : importé par les routers qui décorent
leurs endpoints et par `main.py` qui l'enregistre sur `app.state`.

La clé de limitation est l'IP client (`get_remote_address` → `request.client.host`).
Pour que cette IP soit la vraie IP de l'appelant et non celle du reverse proxy,
uvicorn doit tourner avec `--proxy-headers` ET un `FORWARDED_ALLOW_IPS` couvrant
le proxy (cf. `infra/Dockerfile.api`, `infra/docker-compose.yml`,
`docker-compose.prod.yml`). Sans cela, tous les clients passant par le proxy
partagent le même `request.client.host` — donc le même bucket — et la limite
devient un plafond global trivialement saturable.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

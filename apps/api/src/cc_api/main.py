# SPDX-License-Identifier: AGPL-3.0-or-later
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from cc_api.core.logging import configure_logging
from cc_api.core.ratelimit import limiter
from cc_api.core.settings import settings
from cc_api.routers import abonnements, adhesions, corpus, debug, qa

configure_logging()

app = FastAPI(title="class-consciousness API", version="0.0.1")
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)


@app.middleware("http")
async def _reject_nul_in_path(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Rejette tout octet NUL dans le chemin d'URL.

    Un `%00` décodé atteindrait sinon une requête SQL et asyncpg lèverait un
    `ValueError` non capturé (« string cannot contain NUL ») → 500 nu. Un NUL
    n'a jamais sa place dans un chemin : 400 immédiat, avant tout accès DB.
    """
    if "\x00" in request.url.path:
        return JSONResponse(
            status_code=400,
            content={"detail": "caractère NUL interdit dans l'URL"},
        )
    return await call_next(request)


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit dépassé", "limit": str(exc.detail)},
    )


async def _recursion_handler(request: Request, exc: RecursionError) -> JSONResponse:
    """Un JSON exagérément imbriqué fait dérailler `json.loads` en `RecursionError`.

    Sans ce gestionnaire, c'est un 500 nu (un client peut le déclencher avec un
    petit payload). On le traite comme une requête malformée : 400.
    """
    return JSONResponse(
        status_code=400,
        content={"detail": "structure JSON trop imbriquée"},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]
app.add_exception_handler(RecursionError, _recursion_handler)  # type: ignore[arg-type]

# CORS — le chat RAG (page web) appelle l'API depuis un autre sous-domaine.
# Ajouté en dernier → middleware le plus externe : les en-têtes CORS sont
# présents même sur les réponses d'erreur et les préflights OPTIONS.
if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(corpus.router)
app.include_router(qa.router)
app.include_router(adhesions.router)
app.include_router(abonnements.router)

if settings.is_dev:
    app.include_router(debug.router)
    app.include_router(corpus.admin_router)

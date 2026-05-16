# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from cc_api.core.logging import configure_logging
from cc_api.core.settings import settings
from cc_api.routers import adhesions, corpus, debug, qa

configure_logging()

app = FastAPI(title="class-consciousness API", version="0.0.1")
app.state.limiter = qa.limiter
app.add_middleware(SlowAPIMiddleware)


async def _rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "rate limit dépassé", "limit": str(exc.detail)},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)  # type: ignore[arg-type]


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(corpus.router)
app.include_router(qa.router)
app.include_router(adhesions.router)

if settings.is_dev:
    app.include_router(debug.router)
    app.include_router(corpus.admin_router)

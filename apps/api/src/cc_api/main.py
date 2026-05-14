# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import FastAPI

from cc_api.core.logging import configure_logging
from cc_api.core.settings import settings
from cc_api.routers import corpus, debug

configure_logging()

app = FastAPI(title="class-consciousness API", version="0.0.1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(corpus.router)

if settings.is_dev:
    app.include_router(debug.router)
    app.include_router(corpus.admin_router)

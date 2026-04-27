# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import FastAPI

app = FastAPI(title="class-consciousness API", version="0.0.1")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Point d'entrée : `python -m cc_embed` lance le serveur uvicorn."""

from __future__ import annotations

import uvicorn

from cc_embed.config import settings


def main() -> None:
    uvicorn.run(
        "cc_embed.app:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

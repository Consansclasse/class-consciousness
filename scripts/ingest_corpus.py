#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ingère un batch de fichiers TEI directement via `cc_api.services.ingest`.

Évite le détour par l'API HTTP : appelle `ingest_issue` en async sur chaque
fichier, log la progression, gère les erreurs sans interrompre le batch.

Pré-requis : `.env` chargé (POSTGRES_HOST=127.0.0.1, POSTGRES_PORT=5433,
QDRANT_URL=http://127.0.0.1:6333) et, pour le backend par défaut, le serveur
cc-embed démarré (`python -m cc_embed`, CC_API_EMBED_SERVER_URL).

Usage :
    set -a && source .env && set +a
    uv run python scripts/ingest_corpus.py ../class-consciousness-corpus/bilan/bilan-[0-9][0-9][0-9].tei.xml
"""

from __future__ import annotations

import asyncio
import glob
import os
import sys
import time
from pathlib import Path

# Charge .env manuellement si non déjà exporté (idempotent).
_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
if _ENV_PATH.exists():
    for line in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


async def _ingest_one(
    path: Path, embed: object, qdrant: object
) -> tuple[str, dict[str, object]]:
    """Ingère un fichier en réutilisant les clients partagés. Retourne (status, payload)."""
    from cc_api.services.ingest import ingest_issue

    started = time.monotonic()
    try:
        ref = await ingest_issue(path, embed=embed, qdrant=qdrant)  # type: ignore[arg-type]
    except Exception as exc:  # on veut continuer le batch malgré un échec isolé
        return (
            "error",
            {"path": str(path), "error_type": type(exc).__name__, "message": str(exc)},
        )
    duration = time.monotonic() - started
    return (
        "duplicate" if ref.was_duplicate else "ingested",
        {
            "path": str(path),
            "slug": ref.slug,
            "ark": ref.ark,
            "n_articles": ref.n_articles,
            "n_chunks": ref.n_chunks,
            "duration_s": round(duration, 2),
        },
    )


def _is_empty_tei(path: Path) -> bool:
    """Détecte les TEI sans `<div type="article">` (scrape échoué)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return True
    return '<div type="article"' not in text


async def main(patterns: list[str]) -> int:
    from cc_api.clients.embed import get_embed_client
    from cc_api.clients.qdrant import get_qdrant

    # Expand globs + filtrer les TEI vides (scrape échoué).
    raw_files: list[Path] = []
    for pat in patterns:
        for m in glob.glob(pat, recursive=True) or [pat]:
            p = Path(m).resolve()
            if p.is_file():
                raw_files.append(p)
    raw_files = sorted(set(raw_files))
    files: list[Path] = []
    skipped_empty: list[Path] = []
    for f in raw_files:
        if _is_empty_tei(f):
            skipped_empty.append(f)
        else:
            files.append(f)
    if skipped_empty:
        print(f"⚠ {len(skipped_empty)} fichier(s) TEI vide(s) ignoré(s) :", file=sys.stderr)
        for f in skipped_empty:
            print(f"   - {f.name}", file=sys.stderr)
    if not files:
        print(f"Aucun fichier valide à ingérer pour : {patterns}", file=sys.stderr)
        return 1

    # Clients partagés pour tout le batch (le service ingest_issue ne ferme pas
    # ce qu'il n'a pas créé — voir `owns_embed` dans services/ingest.py).
    embed = get_embed_client()
    qdrant = get_qdrant()

    print(f"Ingestion de {len(files)} fichier(s)…\n")
    n_ingested = 0
    n_duplicate = 0
    n_error = 0
    total_chunks = 0
    total_articles = 0
    started = time.monotonic()

    try:
        for idx, f in enumerate(files, 1):
            prefix = f"[{idx:3d}/{len(files)}] {f.name:30s}"
            status, payload = await _ingest_one(f, embed, qdrant)
            if status == "ingested":
                n_ingested += 1
                total_chunks += int(payload["n_chunks"])  # type: ignore[arg-type]
                total_articles += int(payload["n_articles"])  # type: ignore[arg-type]
                print(
                    f"{prefix} ✓ {payload['n_articles']} articles, "
                    f"{payload['n_chunks']} chunks, {payload['duration_s']}s"
                )
            elif status == "duplicate":
                n_duplicate += 1
                print(f"{prefix} ⊙ déjà ingéré (SHA256 connu)")
            else:
                n_error += 1
                print(
                    f"{prefix} ✗ {payload['error_type']}: "
                    f"{str(payload['message'])[:120]}",
                    file=sys.stderr,
                )
    finally:
        await embed.aclose()

    total_duration = time.monotonic() - started
    print()
    print(f"Terminé en {total_duration:.1f}s ({total_duration / 60:.1f} min)")
    print(f"  Ingérés     : {n_ingested} (articles={total_articles}, chunks={total_chunks})")
    print(f"  Doublons    : {n_duplicate}")
    print(f"  Échecs      : {n_error}")
    if skipped_empty:
        print(f"  TEI vides   : {len(skipped_empty)} (scrape à relancer)")
    return 0 if n_error == 0 else 2


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        print("Usage: ingest_corpus.py <fichier-ou-glob.tei.xml> [...]", file=sys.stderr)
        sys.exit(1)
    sys.exit(asyncio.run(main(args)))

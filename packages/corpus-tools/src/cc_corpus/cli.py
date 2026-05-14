# SPDX-License-Identifier: AGPL-3.0-or-later
"""CLI cc-corpus — interface ligne de commande pour l'ingestion TEI.

Appelle l'endpoint `POST /admin/ingest` de l'API locale (dev only).
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Annotated

import httpx
import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

app = typer.Typer(help="cc-corpus — ingestion TEI P5 pour l'archive Conscience de classe.")
console = Console()


def _expand(patterns: list[str]) -> list[Path]:
    """Étend les globs et résout chaque fichier en path absolu existant."""
    paths: list[Path] = []
    for pattern in patterns:
        matched = glob.glob(pattern, recursive=True) or [pattern]
        for m in matched:
            p = Path(m).resolve()
            if p.is_file():
                paths.append(p)
    return paths


@app.command()
def version() -> None:
    """Affiche la version du paquet."""
    typer.echo("0.0.1")


@app.command()
def ingest(
    paths: Annotated[
        list[str],
        typer.Argument(help="Fichiers .tei.xml ou globs (ex: corpus/_seed/*.tei.xml)"),
    ],
    api_base: Annotated[
        str,
        typer.Option(
            "--api-base",
            envvar="CC_API_BASE",
            help="URL de l'API (défaut http://localhost:8000)",
        ),
    ] = "http://localhost:8000",
    timeout: Annotated[float, typer.Option(help="Timeout HTTP par fichier (secondes)")] = 120.0,
) -> None:
    """Ingère un ou plusieurs fichiers TEI P5 via POST /admin/ingest."""
    files = _expand(paths)
    if not files:
        console.print(f"[red]Aucun fichier trouvé pour : {paths}[/red]")
        raise typer.Exit(code=1)

    total_chunks = 0
    failures = 0
    duplicates = 0
    url = f"{api_base.rstrip('/')}/admin/ingest"

    with (
        httpx.Client(timeout=timeout) as client,
        Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
        ) as progress,
    ):
        task = progress.add_task("Ingestion…", total=len(files))
        for f in files:
            progress.update(task, description=f"Ingest {f.name}")
            try:
                resp = client.post(url, json={"path": str(f)})
            except httpx.RequestError as exc:
                console.print(f"[red]Erreur réseau {f.name} : {exc}[/red]")
                failures += 1
                progress.advance(task)
                continue
            if resp.status_code >= 400:
                console.print(f"[red]API {resp.status_code} pour {f.name} : {resp.text}[/red]")
                failures += 1
                progress.advance(task)
                continue
            body = resp.json()
            total_chunks += int(body.get("nChunks", body.get("n_chunks", 0)))
            if body.get("wasDuplicate") or body.get("was_duplicate"):
                duplicates += 1
            progress.advance(task)

    console.print(
        f"[bold]Terminé[/bold] : {len(files)} fichier(s), "
        f"{total_chunks} chunks indexés, {duplicates} déjà présent(s), {failures} échec(s)."
    )
    if failures > 0:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

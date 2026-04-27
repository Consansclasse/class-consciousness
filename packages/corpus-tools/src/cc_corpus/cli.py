# SPDX-License-Identifier: AGPL-3.0-or-later
import typer

app = typer.Typer(help="cc-corpus — ingestion CLI for class-consciousness.")


@app.command()
def version() -> None:
    typer.echo("0.0.1")


if __name__ == "__main__":
    app()

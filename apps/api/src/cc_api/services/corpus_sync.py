# SPDX-License-Identifier: AGPL-3.0-or-later
"""Auto-synchronisation du corpus depuis le repo GitHub public.

Le corpus TEI vit dans un dépôt séparé (`Consansclasse/class-consciousness-corpus`).
Cette tâche de fond (branchée au `lifespan` de l'API quand `corpus_sync_enabled`)
récupère les **nouveaux numéros tout seule** — sans `git pull`, sans geste de
l'utilisateur, sans `git` dans l'image (fetch HTTP pur). Elle sert les DEUX
populations d'un même mécanisme : le site (prod) et les self-hébergeurs.

Chaque cycle :

1. Lit le **SHA de tête** du repo (1 petite requête API GitHub). Inchangé depuis
   le dernier cycle (mémorisé dans Redis) → on s'arrête là, zéro téléchargement.
2. Sinon : télécharge le **tarball** (CDN codeload, hors-quota API), l'extrait en
   dossier temporaire (extraction sécurisée anti path-traversal), sélectionne les
   TEI canoniques (`corpus_sync_glob`).
3. Ingère chaque fichier via `ingest_issue` — **idempotent par SHA256** : les
   numéros déjà connus sont ignorés (`was_duplicate`), les nouveaux sont indexés
   (embeddings via cc-embed : GPU en local, CPU en prod).
4. Mémorise le SHA dans Redis **seulement si 0 échec** → un échec réseau ou un TEI
   cassé fait re-tenter au cycle suivant, jamais de numéro silencieusement sauté.

Hors-scope : le ré-encodage d'un numéro existant (même slug/ARK, contenu changé)
produit un nouveau SHA256 → `ingest_issue` tente un INSERT en conflit de contrainte
unique → l'échec est capturé par fichier (loggé, non fatal). On couvre les AJOUTS.
"""

from __future__ import annotations

import asyncio
import glob as globlib
import io
import tarfile
import tempfile
from collections.abc import Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast
from uuid import uuid4

import httpx
from qdrant_client import AsyncQdrantClient

from cc_api.clients.embed import EmbedClient, get_embed_client
from cc_api.clients.qdrant import get_qdrant
from cc_api.clients.redis import get_redis
from cc_api.core.logging import get_logger
from cc_api.core.settings import settings
from cc_api.services.ingest import ingest_issue

log = get_logger(__name__)

_GITHUB_API = "https://api.github.com"
_CODELOAD = "https://codeload.github.com"
_REDIS_LAST_SHA = "corpus_sync:last_sha"
_REDIS_LOCK = "corpus_sync:lock"
_HTTP_TIMEOUT_S = 60.0
# Le 1er cycle d'une base neuve ingère les ~46 numéros ; sur CPU c'est long. TTL
# large pour que le verrou couvre la passe complète, mais borné pour qu'un process
# mort le libère. L'intervalle (24 h) >> TTL → pas de chevauchement légitime.
_LOCK_TTL_S = 3600
# Délai avant la 1ère passe : laisse cc-embed et la DB finir de chauffer au boot.
_INITIAL_DELAY_S = 15.0
# Libération atomique du verrou : ne supprime que si on en est toujours le porteur
# (évite de relâcher un verrou repris par un autre process après expiration).
_UNLOCK_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('del', KEYS[1]) else return 0 end"
)


@dataclass
class SyncReport:
    """Bilan d'un cycle d'ingestion."""

    ingested: int = 0
    duplicates: int = 0
    errors: int = 0
    chunks: int = 0
    ingested_slugs: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.errors == 0


def _select_from_tarball(tar_bytes: bytes, glob_pattern: str, dest: Path) -> list[Path]:
    """Extrait l'archive `.tar.gz` dans `dest` puis renvoie les fichiers matchant
    `glob_pattern` (relatif à `dest`). Fonction pure (aucun réseau) — testable avec
    une archive construite en mémoire.

    `filter="data"` (Python 3.12) neutralise les entrées dangereuses (chemins
    absolus, `..`, liens, fichiers spéciaux) : protection anti path-traversal.
    """
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as tar:
        tar.extractall(dest, filter="data")
    return sorted(
        p
        for raw in globlib.glob(str(dest / glob_pattern), recursive=True)
        if (p := Path(raw)).is_file()
    )


class GitHubTarballSource:
    """Source HTTP du corpus : SHA de tête (détection) + tarball (contenu).

    Aucune dépendance à `git` : tout passe par HTTPS (`ca-certificates` est dans
    l'image). Pour les tests on injecte un `httpx.AsyncClient` (transport ASGI/mock
    de transport), sinon le client est créé et possédé par l'instance.
    """

    def __init__(
        self,
        repo: str,
        ref: str,
        token: str | None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.repo = repo
        self.ref = ref
        self._token = token
        self._client = client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT_S, follow_redirects=True)
        self._owns_client = client is None

    def _headers(self, accept: str) -> dict[str, str]:
        headers = {"Accept": accept, "User-Agent": "class-consciousness-corpus-sync"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def current_revision(self) -> str:
        """SHA du commit de tête de `ref` (texte brut via `Accept: vnd.github.sha`)."""
        url = f"{_GITHUB_API}/repos/{self.repo}/commits/{self.ref}"
        resp = await self._client.get(url, headers=self._headers("application/vnd.github.sha"))
        resp.raise_for_status()
        return resp.text.strip()

    async def fetch_tarball(self) -> bytes:
        """Archive `.tar.gz` de `ref` via le CDN codeload (hors quota API GitHub)."""
        url = f"{_CODELOAD}/{self.repo}/tar.gz/refs/heads/{self.ref}"
        resp = await self._client.get(url, headers=self._headers("application/x-gzip"))
        resp.raise_for_status()
        return resp.content

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


async def sync_once(
    docs: list[Path],
    *,
    embed: EmbedClient,
    qdrant: AsyncQdrantClient,
) -> SyncReport:
    """Ingère une liste de fichiers TEI. Réutilise les clients partagés (le client
    d'embedding est le singleton de l'app : on ne le ferme JAMAIS ici). Un échec
    isolé n'interrompt pas le lot."""
    report = SyncReport()
    for doc in docs:
        try:
            ref = await ingest_issue(doc, embed=embed, qdrant=qdrant)
        except Exception as exc:  # un fichier cassé ne doit pas tuer le lot
            report.errors += 1
            log.error(
                "corpus_sync.ingest_failed",
                file=doc.name,
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            continue
        if ref.was_duplicate:
            report.duplicates += 1
        else:
            report.ingested += 1
            report.chunks += ref.n_chunks
            report.ingested_slugs.append(ref.slug)
            log.info(
                "corpus_sync.ingested",
                slug=ref.slug,
                n_articles=ref.n_articles,
                n_chunks=ref.n_chunks,
            )
    return report


async def run_sync_cycle(
    *, source: GitHubTarballSource | None = None, force: bool = False
) -> SyncReport | None:
    """Un cycle complet, protégé par un verrou Redis. Renvoie :
    - `None` si rien à faire (verrou pris ailleurs, ou SHA inchangé sans `force`) ;
    - un `SyncReport` sinon.
    """
    redis = get_redis()
    token = uuid4().hex
    if not await redis.set(_REDIS_LOCK, token, nx=True, ex=_LOCK_TTL_S):
        log.info("corpus_sync.locked_skip")
        return None

    own_source = source is None
    if source is None:
        source = GitHubTarballSource(
            settings.corpus_sync_repo,
            settings.corpus_sync_ref,
            settings.corpus_sync_token,
        )
    try:
        sha = await source.current_revision()
        if not force and await redis.get(_REDIS_LAST_SHA) == sha:
            log.info("corpus_sync.unchanged", sha=sha[:12])
            return None

        tar_bytes = await source.fetch_tarball()
        with tempfile.TemporaryDirectory(prefix="cc-corpus-") as tmp:
            docs = await asyncio.to_thread(
                _select_from_tarball, tar_bytes, settings.corpus_sync_glob, Path(tmp)
            )
            if not docs:
                log.warning("corpus_sync.no_documents", glob=settings.corpus_sync_glob)
                return SyncReport()
            report = await sync_once(docs, embed=get_embed_client(), qdrant=get_qdrant())

        if report.ok:
            await redis.set(_REDIS_LAST_SHA, sha)
        log.info(
            "corpus_sync.cycle_done",
            sha=sha[:12],
            ingested=report.ingested,
            duplicates=report.duplicates,
            errors=report.errors,
        )
        return report
    finally:
        if own_source:
            await source.aclose()
        # Le client async renvoie toujours un awaitable ; les stubs partagés
        # sync/async typent `eval` en union → cast explicite.
        await cast("Awaitable[object]", redis.eval(_UNLOCK_LUA, 1, _REDIS_LOCK, token))


async def corpus_sync_loop() -> None:
    """Boucle de fond : 1ère passe eager après un court délai, puis à l'intervalle.
    Ne bloque jamais le démarrage ni ne crash l'app (chaque cycle est isolé)."""
    interval_s = max(1, settings.corpus_sync_interval_hours) * 3600
    log.info(
        "corpus_sync.loop_start",
        repo=settings.corpus_sync_repo,
        ref=settings.corpus_sync_ref,
        interval_hours=settings.corpus_sync_interval_hours,
    )
    await asyncio.sleep(_INITIAL_DELAY_S)
    while True:
        try:
            await run_sync_cycle()
        except asyncio.CancelledError:
            log.info("corpus_sync.loop_stop")
            raise
        except Exception as exc:  # réseau, GitHub down, etc. → on re-tentera
            log.error(
                "corpus_sync.cycle_error",
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
        await asyncio.sleep(interval_s)


def _main() -> int:
    """Déclenche un cycle à la demande (utilisé par `make sandbox-corpus-sync` pour
    vérifier l'ingestion GPU sans attendre l'intervalle).

    Sans argument : cycle réel depuis GitHub (`--force`, ignore le SHA-gating).
    `--local <glob>` : ingère un glob local (offline, ex. le corpus déjà monté)."""
    import argparse

    parser = argparse.ArgumentParser(description="Cycle d'auto-synchro du corpus.")
    parser.add_argument(
        "--local",
        metavar="GLOB",
        help="ingère un glob local au lieu de GitHub (offline)",
    )
    args = parser.parse_args()

    async def _run() -> int:
        if args.local:
            docs = sorted(
                p for raw in globlib.glob(args.local, recursive=True) if (p := Path(raw)).is_file()
            )
            if not docs:
                log.error("corpus_sync.no_local_files", glob=args.local)
                return 1
            report: SyncReport | None = await sync_once(
                docs, embed=get_embed_client(), qdrant=get_qdrant()
            )
        else:
            report = await run_sync_cycle(force=True)
        log.info(
            "corpus_sync.manual_done",
            ingested=getattr(report, "ingested", 0),
            duplicates=getattr(report, "duplicates", 0),
            errors=getattr(report, "errors", 0),
        )
        return 0 if (report is None or report.ok) else 2

    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(_main())

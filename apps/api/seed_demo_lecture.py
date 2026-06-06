# SPDX-License-Identifier: AGPL-3.0-or-later
"""Insert d'un numéro de DÉMO (sans embeddings) pour tester l'UI de lecture / audio.

À lancer DANS le conteneur api (où cc_api + la config DB sont disponibles) :

    docker compose -f infra/docker-compose.yml exec -T api \\
        python /app/apps/api/seed_demo_lecture.py

Idempotent : si le numéro de démo existe déjà, ne réinsère pas. Pour repartir
de zéro : passer l'argument `--reset` (supprime le numéro de démo d'abord).

N'utilise NI le serveur d'embeddings NI Qdrant : on écrit seulement Postgres
(Issue → Author → Article → Chunks). Les endpoints de lecture (`GET /corpus`,
`/corpus/{issue}`, `/corpus/{issue}/{article}`) lisent uniquement Postgres.
"""

from __future__ import annotations

import asyncio
import hashlib
import sys
import uuid
from datetime import date

from sqlalchemy import delete, func, select

from cc_api.clients.db import get_session_maker
from cc_api.models import Article, Author, Chunk, Issue

SLUG = "bilan-demo"
ARTICLE_SLUG = "note-de-demonstration"

PARAS = [
    "Ceci est un numéro de démonstration inséré manuellement dans la base, sans "
    "passer par le moteur d'embeddings. Il sert uniquement à vérifier que "
    "l'interface de lecture affiche correctement un texte, paragraphe par "
    "paragraphe, et que la lecture audio peut le parcourir.",
    "La revue théorique se donne pour tâche d'analyser les événements à la lumière "
    "des principes, sans complaisance ni précipitation. Tirer le bilan d'une "
    "période, c'est confronter les mots d'ordre à leurs résultats réels, et refuser "
    "de prendre les espérances pour des certitudes.",
    "Une organisation ne se juge pas à ses proclamations mais à sa capacité de "
    "comprendre les rapports de force et d'y intervenir avec lucidité. Là où la "
    "confusion règne, le premier devoir est de rétablir la clarté, fût-ce au prix "
    "de l'isolement momentané.",
    "L'histoire ne récompense pas la fidélité aux formules, mais la justesse de "
    "l'analyse. Chaque défaite mal comprise prépare la suivante ; chaque défaite "
    "comprise devient une arme. C'est pourquoi l'examen critique du passé n'est "
    "jamais un exercice académique.",
    "Ce paragraphe final clôt le texte de démonstration. Si vous le lisez à "
    "l'écran, et si la lecture audio l'énonce jusqu'ici sans accroc, alors la "
    "chaîne d'affichage et de restitution fonctionne de bout en bout.",
]


async def main(reset: bool) -> None:
    Session = get_session_maker()
    async with Session() as s:
        if reset:
            existing = (await s.execute(select(Issue).where(Issue.slug == SLUG))).scalar_one_or_none()
            if existing is not None:
                await s.execute(delete(Issue).where(Issue.id == existing.id))
                await s.commit()
                print(f"[reset] numéro de démo supprimé (issue_id={existing.id})")

        already = (await s.execute(select(Issue.id).where(Issue.slug == SLUG))).first()
        if already:
            print(f"[skip] le numéro de démo existe déjà (issue_id={already[0]})")
        else:
            issue = Issue(
                slug=SLUG,
                ark="ark:/demo/bilan-demo",
                journal_title="Bilan",
                issue_number=None,
                title="Bilan — numéro de démonstration (DÉMO)",
                published_date=date(1933, 11, 1),
                license="CC BY-SA 4.0",
                source_desc="Insertion manuelle locale (test lecture/audio) — sans embeddings.",
                sha256=hashlib.sha256(b"bilan-demo-lecture").hexdigest(),
            )
            s.add(issue)
            await s.flush()

            author = Author(display_name="Rédaction (démo)")
            s.add(author)
            await s.flush()

            article = Article(
                issue_id=issue.id,
                slug=ARTICLE_SLUG,
                ark=f"{issue.ark}/{ARTICLE_SLUG}",
                title="Note de démonstration — test de lecture",
                author_id=author.id,
                idx_in_issue=0,
            )
            s.add(article)
            await s.flush()

            pos = 0
            for i, text in enumerate(PARAS):
                start, end = pos, pos + len(text)
                pos = end + 1
                s.add(
                    Chunk(
                        article_id=article.id,
                        idx=i,
                        text=text,
                        char_start=start,
                        char_end=end,
                        token_count=len(text.split()),
                        embedding_model="manual-demo",
                        qdrant_point_id=uuid.uuid4(),
                    )
                )
            await s.commit()
            print(f"[ok] inséré issue_id={issue.id} article_id={article.id} paragraphes={len(PARAS)}")

        # Vérification dans le même process (pas de course possible).
        n_issues = (await s.execute(select(func.count()).select_from(Issue))).scalar_one()
        n_articles = (await s.execute(select(func.count()).select_from(Article))).scalar_one()
        n_chunks = (await s.execute(select(func.count()).select_from(Chunk))).scalar_one()
        print(f"[verif] issues={n_issues} articles={n_articles} chunks={n_chunks}")
        print("[urls]")
        print("  liste   : http://localhost:8000/corpus")
        print(f"  numéro  : http://localhost:8000/corpus/{SLUG}")
        print(f"  article : http://localhost:8000/corpus/{SLUG}/{ARTICLE_SLUG}")


if __name__ == "__main__":
    asyncio.run(main(reset="--reset" in sys.argv))

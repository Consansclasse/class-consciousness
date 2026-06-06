# SPDX-License-Identifier: AGPL-3.0-or-later
"""rag_interactions : colonnes d'observabilité agentique (G6)

Ajoute quatre colonnes ADDITIVES à `rag_interactions` pour mesurer le pipeline
agentique au fil de ses lots :
- `route`         : décision de routage de complexité (G3, déjà active) —
                    "simple" | "complexe" | "off" | NULL (lignes antérieures).
- `n_iterations`  : itérations de récupération (boucle bornée G5), défaut 1.
- `crag_verdict`  : verdict de couverture des passages (CRAG G4) — NULL tant que
                    G4 n'est pas livré.
- `cache_hit`     : réponse servie depuis le cache sémantique (G2), défaut false.

Les défauts serveur garantissent que les lignes existantes restent valides et que
les insertions sans valeur explicite fonctionnent (compatibilité ascendante).

Revision ID: 20260606_0014
Revises: 20260521_0013
Create Date: 2026-06-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260606_0014"
down_revision: str | None = "20260521_0013"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rag_interactions", sa.Column("route", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "rag_interactions",
        sa.Column(
            "n_iterations",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )
    op.add_column(
        "rag_interactions",
        sa.Column("crag_verdict", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "rag_interactions",
        sa.Column(
            "cache_hit",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("rag_interactions", "cache_hit")
    op.drop_column("rag_interactions", "crag_verdict")
    op.drop_column("rag_interactions", "n_iterations")
    op.drop_column("rag_interactions", "route")

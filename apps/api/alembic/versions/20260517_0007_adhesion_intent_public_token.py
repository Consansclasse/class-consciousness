# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ajoute `adhesion_intents.public_token` — identifiant public opaque

Corrige un IDOR : `GET /adhesions/intent/{intent_id}` était indexé par l'id
séquentiel auto-incrément, sans authentification. Un attaquant pouvait énumérer
les entiers et lire tout le registre des adhésions (statuts, montants, dates).
Le jeton opaque (`secrets.token_urlsafe(24)`, 192 bits) remplace l'entier dans
les URLs de retour et le lookup public.

Le back-fill génère un jeton aléatoire distinct par ligne existante : on ne peut
pas utiliser un server_default constant (l'unicité serait violée).

Revision ID: 20260517_0007
Revises: 20260516_0006
Create Date: 2026-05-17
"""

from __future__ import annotations

import secrets
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260517_0007"
down_revision: str | None = "20260516_0006"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 1. Colonne nullable d'abord — les lignes existantes n'ont pas de jeton.
    op.add_column(
        "adhesion_intents",
        sa.Column("public_token", sa.String(64), nullable=True),
    )

    # 2. Back-fill : un jeton aléatoire unique par ligne existante.
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id FROM adhesion_intents")).fetchall()
    for (row_id,) in rows:
        conn.execute(
            sa.text("UPDATE adhesion_intents SET public_token = :tok WHERE id = :id"),
            {"tok": secrets.token_urlsafe(24), "id": row_id},
        )

    # 3. Verrou NOT NULL une fois toutes les lignes peuplées.
    op.alter_column(
        "adhesion_intents",
        "public_token",
        existing_type=sa.String(64),
        nullable=False,
    )

    # 4. Index unique — le lookup public se fait par ce jeton.
    op.create_index(
        "ix_adhesion_intents_public_token",
        "adhesion_intents",
        ["public_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_adhesion_intents_public_token", table_name="adhesion_intents")
    op.drop_column("adhesion_intents", "public_token")

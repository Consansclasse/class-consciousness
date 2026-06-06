# SPDX-License-Identifier: AGPL-3.0-or-later
"""rag_feedback (retour d'un lecteur sur une réponse de l'assistant)

Table `rag_feedback` : pouce haut/bas ou signalement (FLAG) rattaché à une
`RagInteraction`. Ferme la boucle humaine du closed-loop RAG.

Revision ID: 20260519_0010
Revises: 20260519_0009
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260519_0010"
down_revision: str | None = "20260519_0009"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    rag_feedback_kind = postgresql.ENUM(
        "UP", "DOWN", "FLAG", name="rag_feedback_kind", create_type=True
    )
    rag_feedback_kind.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "rag_feedback",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("rag_interaction_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            postgresql.ENUM(name="rag_feedback_kind", create_type=False),
            nullable=False,
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["rag_interaction_id"], ["rag_interactions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rag_feedback_rag_interaction_id"),
        "rag_feedback",
        ["rag_interaction_id"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_rag_feedback_rag_interaction_id"), table_name="rag_feedback")
    op.drop_table("rag_feedback")
    sa.Enum(name="rag_feedback_kind").drop(op.get_bind(), checkfirst=True)

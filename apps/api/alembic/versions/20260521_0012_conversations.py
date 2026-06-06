# SPDX-License-Identifier: AGPL-3.0-or-later
"""conversations (fils d'échanges) + rattachement des rag_interactions

Crée la table `conversations` (un fil = un regroupement d'interactions d'un
compte, façon historique latéral Claude/Gemini) et ajoute à `rag_interactions`
deux colonnes :
- `conversation_id` (FK SET NULL) — le fil auquel l'interaction appartient ;
- `cited_chunks` (JSONB) — l'appareil de sources complet, pour réafficher un
  fil d'historique à l'identique sans re-résoudre les chunks dans Qdrant.

Revision ID: 20260521_0012
Revises: 20260519_0011
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260521_0012"
down_revision: str | None = "20260519_0011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_conversations_user_id"), "conversations", ["user_id"])

    op.add_column(
        "rag_interactions",
        sa.Column("conversation_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_rag_interactions_conversation_id",
        "rag_interactions",
        "conversations",
        ["conversation_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_rag_interactions_conversation_id"),
        "rag_interactions",
        ["conversation_id"],
    )
    op.add_column(
        "rag_interactions",
        sa.Column(
            "cited_chunks",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
    )


def downgrade() -> None:
    op.drop_column("rag_interactions", "cited_chunks")
    op.drop_index(op.f("ix_rag_interactions_conversation_id"), table_name="rag_interactions")
    op.drop_constraint(
        "fk_rag_interactions_conversation_id",
        "rag_interactions",
        type_="foreignkey",
    )
    op.drop_column("rag_interactions", "conversation_id")
    op.drop_index(op.f("ix_conversations_user_id"), table_name="conversations")
    op.drop_table("conversations")

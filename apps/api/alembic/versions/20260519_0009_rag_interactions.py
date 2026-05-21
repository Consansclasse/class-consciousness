# SPDX-License-Identifier: AGPL-3.0-or-later
"""rag_interactions (trace persistée de chaque requête à l'assistant RAG)

Table `rag_interactions` : une ligne par appel à /qa ou /qa/stream — question,
réponse ou refus, verdicts d'ancrage par phrase, latences par étape, tokens
consommés. Rend l'historique RAG interrogeable (closed-loop, observabilité) au
lieu de le laisser dans des logs JSON dispersés.

Revision ID: 20260519_0009
Revises: 20260517_0008
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260519_0009"
down_revision: str | None = "20260517_0008"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rag_interactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("ip_hash", sa.String(length=64), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column(
            "incomplete",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("refused_reason", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("latencies", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("usage", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sentences", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "cited_source_ids",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("retrieval_count", sa.Integer(), nullable=False),
        sa.Column("rerank_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_rag_interactions_created_at"), "rag_interactions", ["created_at"]
    )
    op.create_index(
        op.f("ix_rag_interactions_user_id"), "rag_interactions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_rag_interactions_user_id"), table_name="rag_interactions")
    op.drop_index(
        op.f("ix_rag_interactions_created_at"), table_name="rag_interactions"
    )
    op.drop_table("rag_interactions")

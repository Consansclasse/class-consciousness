# SPDX-License-Identifier: AGPL-3.0-or-later
"""init corpus — authors, works, chunks + extensions Postgres MCP Pro.

Revision ID: 20260514_0001
Revises:
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Extensions Postgres : pg_stat_statements est universel (postgres:17 standard),
    # hypopg requiert un package OS (postgresql-17-hypopg) — best-effort via DO block
    # (compatible online + offline mode Alembic).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_stat_statements")
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name='hypopg') THEN "
        "CREATE EXTENSION IF NOT EXISTS hypopg; "
        "END IF; "
        "END $$;"
    )

    op.create_table(
        "authors",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("viaf_id", sa.String(length=64), nullable=True),
        sa.Column("idref_id", sa.String(length=64), nullable=True),
        sa.Column("wikidata_id", sa.String(length=64), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("death_year", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("viaf_id"),
        sa.UniqueConstraint("idref_id"),
        sa.UniqueConstraint("wikidata_id"),
    )
    op.create_index(op.f("ix_authors_display_name"), "authors", ["display_name"])

    op.create_table(
        "works",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ark", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ark"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index(op.f("ix_works_ark"), "works", ["ark"])
    op.create_index(op.f("ix_works_author_id"), "works", ["author_id"])
    op.create_index(op.f("ix_works_sha256"), "works", ["sha256"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qdrant_point_id"),
    )
    op.create_index(op.f("ix_chunks_work_id"), "chunks", ["work_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_chunks_work_id"), table_name="chunks")
    op.drop_table("chunks")
    op.drop_index(op.f("ix_works_sha256"), table_name="works")
    op.drop_index(op.f("ix_works_author_id"), table_name="works")
    op.drop_index(op.f("ix_works_ark"), table_name="works")
    op.drop_table("works")
    op.drop_index(op.f("ix_authors_display_name"), table_name="authors")
    op.drop_table("authors")
    # Les extensions sont volontairement laissées en place (utilisées par d'autres outils).

# SPDX-License-Identifier: AGPL-3.0-or-later
"""refactor en hiérarchie Issue → Article → Chunk

Bilan n°1 = 1 issue contenant N articles. Auparavant, chaque article était un
`work` isolé, perdant le rattachement à son numéro de revue. On modélise
correctement : issues → articles → chunks.

Revision ID: 20260514_0002
Revises: 20260514_0001
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0002"
down_revision: str | None = "20260514_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Drop l'ancienne structure (CASCADE chunks → works → authors).
    op.drop_table("chunks")
    op.drop_table("works")
    op.drop_table("authors")

    # Recrée authors (identique à 0001).
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

    # Nouvelle table : issues (numéros de revue).
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("ark", sa.String(length=255), nullable=False),
        sa.Column("journal_title", sa.String(length=128), nullable=False),
        sa.Column("issue_number", sa.Integer(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("license", sa.Text(), nullable=False),
        sa.Column("source_desc", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("ark"),
        sa.UniqueConstraint("sha256"),
    )
    op.create_index(op.f("ix_issues_slug"), "issues", ["slug"])
    op.create_index(op.f("ix_issues_ark"), "issues", ["ark"])
    op.create_index(op.f("ix_issues_journal_title"), "issues", ["journal_title"])
    op.create_index(op.f("ix_issues_sha256"), "issues", ["sha256"])

    # Nouvelle table : articles (anciens works, avec FK vers issue).
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("ark", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("author_id", sa.Integer(), nullable=False),
        sa.Column("idx_in_issue", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column(
            "inserted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["authors.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ark"),
        sa.UniqueConstraint("issue_id", "slug", name="uq_articles_issue_slug"),
    )
    op.create_index(op.f("ix_articles_issue_id"), "articles", ["issue_id"])
    op.create_index(op.f("ix_articles_slug"), "articles", ["slug"])
    op.create_index(op.f("ix_articles_ark"), "articles", ["ark"])
    op.create_index(op.f("ix_articles_author_id"), "articles", ["author_id"])

    # Recrée chunks (avec FK article_id au lieu de work_id).
    op.create_table(
        "chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("idx", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("qdrant_point_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qdrant_point_id"),
    )
    op.create_index(op.f("ix_chunks_article_id"), "chunks", ["article_id"])


def downgrade() -> None:
    # Drop nouvelle structure.
    op.drop_index(op.f("ix_chunks_article_id"), table_name="chunks")
    op.drop_table("chunks")
    op.drop_index(op.f("ix_articles_author_id"), table_name="articles")
    op.drop_index(op.f("ix_articles_ark"), table_name="articles")
    op.drop_index(op.f("ix_articles_slug"), table_name="articles")
    op.drop_index(op.f("ix_articles_issue_id"), table_name="articles")
    op.drop_table("articles")
    op.drop_index(op.f("ix_issues_sha256"), table_name="issues")
    op.drop_index(op.f("ix_issues_journal_title"), table_name="issues")
    op.drop_index(op.f("ix_issues_ark"), table_name="issues")
    op.drop_index(op.f("ix_issues_slug"), table_name="issues")
    op.drop_table("issues")
    op.drop_index(op.f("ix_authors_display_name"), table_name="authors")
    op.drop_table("authors")

    # Recrée l'ancienne structure (works) pour que 0001 reste cohérent en rollback.
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

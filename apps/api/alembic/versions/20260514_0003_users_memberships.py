# SPDX-License-Identifier: AGPL-3.0-or-later
"""users + memberships (cotisations associatives)

Modèle d'adhésion : User (email unique, soft-deletable) → Memberships
(cotisation annuelle datée, tier individual/structure/mécène, flag solidaire).

Voir mémoire `project_tier_strategy` pour la stratégie de paliers et
`project_fiscal_thresholds_fr` pour les seuils fiscaux.

Revision ID: 20260514_0003
Revises: 20260514_0002
Create Date: 2026-05-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260514_0003"
down_revision: str | None = "20260514_0002"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Types enum Postgres natifs — créés avant les tables qui les référencent.
    membership_tier = postgresql.ENUM(
        "INDIVIDUAL",
        "STRUCTURE",
        "MECENE",
        name="membership_tier",
        create_type=True,
    )
    membership_tier.create(op.get_bind(), checkfirst=True)

    membership_source = postgresql.ENUM(
        "OPENCOLLECTIVE",
        "MANUEL",
        "ADMIN",
        "AUTRE",
        name="membership_source",
        create_type=True,
    )
    membership_source.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"])

    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "tier",
            postgresql.ENUM(name="membership_tier", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "solidaire",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=False),
        sa.Column("amount_eur_cents", sa.Integer(), nullable=False),
        sa.Column(
            "source",
            postgresql.ENUM(name="membership_source", create_type=False),
            nullable=False,
        ),
        sa.Column("external_reference", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_memberships_user_id"), "memberships", ["user_id"])
    op.create_index(op.f("ix_memberships_tier"), "memberships", ["tier"])
    op.create_index(op.f("ix_memberships_valid_until"), "memberships", ["valid_until"])
    # Index composite pour la requête "tier actif du user X à la date Y".
    op.create_index(
        "ix_memberships_user_valid_until",
        "memberships",
        ["user_id", "valid_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_memberships_user_valid_until", table_name="memberships")
    op.drop_index(op.f("ix_memberships_valid_until"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_tier"), table_name="memberships")
    op.drop_index(op.f("ix_memberships_user_id"), table_name="memberships")
    op.drop_table("memberships")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")

    # Drop des types enum APRÈS les tables (sinon PG refuse).
    sa.Enum(name="membership_source").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="membership_tier").drop(op.get_bind(), checkfirst=True)

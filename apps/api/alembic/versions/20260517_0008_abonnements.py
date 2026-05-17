# SPDX-License-Identifier: AGPL-3.0-or-later
"""abonnements (abonnement mensuel récurrent à l'app)

Table `abonnements` : abonnement de service vendu (prestation), distinct de la
cotisation associative (`memberships`). Alimentée par les webhooks Stripe
Billing `customer.subscription.*`. Sert au déblocage du quota RAG quotidien.

Revision ID: 20260517_0008
Revises: 20260517_0007
Create Date: 2026-05-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260517_0008"
down_revision: str | None = "20260517_0007"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    abonnement_status = postgresql.ENUM(
        "ACTIVE",
        "TRIALING",
        "PAST_DUE",
        "CANCELED",
        "INCOMPLETE",
        "UNPAID",
        name="abonnement_status",
        create_type=True,
    )
    abonnement_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "abonnements",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_price_id", sa.String(length=255), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="abonnement_status", create_type=False),
            nullable=False,
        ),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "cancel_at_period_end",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_subscription_id"),
    )
    op.create_index(op.f("ix_abonnements_user_id"), "abonnements", ["user_id"])
    op.create_index(
        op.f("ix_abonnements_stripe_subscription_id"),
        "abonnements",
        ["stripe_subscription_id"],
    )
    op.create_index(op.f("ix_abonnements_status"), "abonnements", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_abonnements_status"), table_name="abonnements")
    op.drop_index(
        op.f("ix_abonnements_stripe_subscription_id"), table_name="abonnements"
    )
    op.drop_index(op.f("ix_abonnements_user_id"), table_name="abonnements")
    op.drop_table("abonnements")
    sa.Enum(name="abonnement_status").drop(op.get_bind(), checkfirst=True)

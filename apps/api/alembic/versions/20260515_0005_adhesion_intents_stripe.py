# SPDX-License-Identifier: AGPL-3.0-or-later
"""adhesion_intents + STRIPE source + consent users

Ajoute :

1. Valeur `STRIPE` à l'enum Postgres `membership_source` (ALTER TYPE ADD VALUE).
   Note : on ne **retire pas** `OPENCOLLECTIVE` même si on a basculé sur Stripe :
   PG ne permet pas DROP VALUE FROM ENUM sans recréer le type. Coût nul à
   garder une valeur orpheline.
2. Enum `adhesion_intent_status` (PENDING / COMPLETED / EXPIRED / FAILED).
3. Table `adhesion_intents` : trace des intentions de paiement avant qu'elles
   ne deviennent des `memberships` (séparation intention / fait). Permet de
   rattacher le webhook Stripe à un User connu et de détecter les abandons.
4. Colonnes `consent_data_at` + `consent_newsletter_at` sur `users` :
   horodatage du consentement RGPD exigé par la CNIL en cas de contrôle.

Revision ID: 20260515_0005
Revises: 20260514_0004
Create Date: 2026-05-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260515_0005"
down_revision: str | None = "20260514_0004"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # 1. Ajouter STRIPE à l'enum existant. ALTER TYPE ADD VALUE doit être
    # exécuté hors transaction sur certaines versions PG ; en Alembic 1.13 +
    # PG 17 c'est OK en transaction implicite.
    op.execute("ALTER TYPE membership_source ADD VALUE IF NOT EXISTS 'STRIPE'")

    # 2. Nouvel enum pour le statut d'une intention de paiement.
    intent_status = postgresql.ENUM(
        "PENDING",
        "COMPLETED",
        "EXPIRED",
        "FAILED",
        name="adhesion_intent_status",
        create_type=True,
    )
    intent_status.create(op.get_bind(), checkfirst=True)

    # 3. Table adhesion_intents.
    op.create_table(
        "adhesion_intents",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        # user_id nullable : l'intention peut être créée avant que l'utilisateur
        # ait été persisté (ex: doublon d'email géré en upsert au webhook).
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "tier",
            postgresql.ENUM(name="membership_tier", create_type=False),
            nullable=False,
        ),
        sa.Column("amount_eur_cents", sa.Integer(), nullable=False),
        sa.Column(
            "solidaire",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Identifiant Stripe Checkout Session — unique pour idempotence webhook.
        sa.Column("stripe_session_id", sa.String(length=255), nullable=False),
        sa.Column("stripe_redirect_url", sa.Text(), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="adhesion_intent_status", create_type=False),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        # Trace du dernier event Stripe traité — debug + audit.
        sa.Column("last_event_id", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_session_id"),
    )
    op.create_index(op.f("ix_adhesion_intents_user_id"), "adhesion_intents", ["user_id"])
    op.create_index(op.f("ix_adhesion_intents_email"), "adhesion_intents", ["email"])
    op.create_index(op.f("ix_adhesion_intents_status"), "adhesion_intents", ["status"])
    op.create_index(
        op.f("ix_adhesion_intents_stripe_session_id"),
        "adhesion_intents",
        ["stripe_session_id"],
    )

    # 4. Consentement RGPD horodaté sur les utilisateurs.
    op.add_column(
        "users",
        sa.Column("consent_data_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("consent_newsletter_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "consent_newsletter_at")
    op.drop_column("users", "consent_data_at")

    op.drop_index(
        op.f("ix_adhesion_intents_stripe_session_id"), table_name="adhesion_intents"
    )
    op.drop_index(op.f("ix_adhesion_intents_status"), table_name="adhesion_intents")
    op.drop_index(op.f("ix_adhesion_intents_email"), table_name="adhesion_intents")
    op.drop_index(op.f("ix_adhesion_intents_user_id"), table_name="adhesion_intents")
    op.drop_table("adhesion_intents")

    sa.Enum(name="adhesion_intent_status").drop(op.get_bind(), checkfirst=True)
    # Pas de drop de la valeur STRIPE de membership_source : impossible sans
    # recréer le type. Acceptable.

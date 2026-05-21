# SPDX-License-Identifier: AGPL-3.0-or-later
"""abonnements.last_event_at (ordre des webhooks Stripe)

Ajoute `last_event_at` : le `created` du dernier event Stripe appliqué. Permet
à `handle_stripe_event` d'ignorer les webhooks `customer.subscription.*` livrés
dans le désordre — Stripe ne garantit pas l'ordre de livraison.

Revision ID: 20260519_0011
Revises: 20260519_0010
Create Date: 2026-05-19
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260519_0011"
down_revision: str | None = "20260519_0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "abonnements",
        sa.Column("last_event_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("abonnements", "last_event_at")

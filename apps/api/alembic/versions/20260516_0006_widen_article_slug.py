# SPDX-License-Identifier: AGPL-3.0-or-later
"""Élargit `articles.slug` de VARCHAR(128) à VARCHAR(255)

Certains articles de Bilan ont des titres longs dont le slug dérivé dépasse
128 caractères (ex. bilan-041 : 147, bilan-045 : 139), ce qui provoquait un
`StringDataRightTruncationError` à l'ingestion. 255 aligne `slug` sur la borne
de `ark` (dont le slug est une composante). Migration non destructive.

Revision ID: 20260516_0006
Revises: 20260515_0005
Create Date: 2026-05-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260516_0006"
down_revision: str | None = "20260515_0005"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "articles",
        "slug",
        existing_type=sa.String(128),
        type_=sa.String(255),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "articles",
        "slug",
        existing_type=sa.String(255),
        type_=sa.String(128),
        existing_nullable=False,
    )

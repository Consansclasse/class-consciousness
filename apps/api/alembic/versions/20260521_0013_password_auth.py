# SPDX-License-Identifier: AGPL-3.0-or-later
"""authentification par mot de passe : hash + email vérifié + purpose des tokens

- `users.password_hash` (Argon2id, nullable : un compte créé par don n'en a pas)
- `users.email_verified_at` (NULL tant que l'email n'est pas confirmé)
- `auth_tokens.purpose` (ENUM token_purpose) — distingue vérification d'email et
  réinitialisation de mot de passe ; remplace l'usage magic-link unique.

Revision ID: 20260521_0013
Revises: 20260521_0012
Create Date: 2026-05-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260521_0013"
down_revision: str | None = "20260521_0012"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

_PURPOSE = postgresql.ENUM(
    "VERIFY_EMAIL", "RESET_PASSWORD", name="token_purpose", create_type=False
)


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True)
    )

    _PURPOSE.create(op.get_bind(), checkfirst=True)
    # server_default temporaire : les éventuels tokens magic-link existants (à
    # usage unique, TTL 15 min) deviennent VERIFY_EMAIL puis expirent. On retire
    # ensuite le défaut pour que l'application pose toujours le purpose
    # explicitement.
    op.add_column(
        "auth_tokens",
        sa.Column("purpose", _PURPOSE, nullable=False, server_default="VERIFY_EMAIL"),
    )
    op.alter_column("auth_tokens", "purpose", server_default=None)
    op.create_index(op.f("ix_auth_tokens_purpose"), "auth_tokens", ["purpose"])


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_tokens_purpose"), table_name="auth_tokens")
    op.drop_column("auth_tokens", "purpose")
    _PURPOSE.drop(op.get_bind(), checkfirst=True)
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "password_hash")

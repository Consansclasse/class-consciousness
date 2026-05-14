# SPDX-License-Identifier: AGPL-3.0-or-later
"""Base SQLAlchemy 2.0 async (DeclarativeBase).

Aucun import en dehors de sqlalchemy + typing + entre modèles.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base déclarative partagée par tous les modèles."""

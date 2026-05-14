# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèles SQLAlchemy — corpus class-consciousness.

Exporte `Base.metadata` pour Alembic --autogenerate.
"""

from __future__ import annotations

from cc_api.models.author import Author
from cc_api.models.base import Base
from cc_api.models.chunk import Chunk
from cc_api.models.work import Work

__all__ = ["Author", "Base", "Chunk", "Work"]

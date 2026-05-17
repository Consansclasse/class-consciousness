# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèles SQLAlchemy — corpus class-consciousness.

Hiérarchie corpus : Issue (revue, ex Bilan n°1) → Articles → Chunks.
Adhésion : User → Memberships (cotisations annuelles).
Exporte `Base.metadata` pour Alembic --autogenerate.
"""

from __future__ import annotations

from cc_api.models.abonnement import Abonnement, AbonnementStatus
from cc_api.models.adhesion_intent import AdhesionIntent, AdhesionIntentStatus
from cc_api.models.article import Article
from cc_api.models.auth_token import AuthToken
from cc_api.models.author import Author
from cc_api.models.base import Base
from cc_api.models.chunk import Chunk
from cc_api.models.issue import Issue
from cc_api.models.membership import Membership, MembershipSource, MembershipTier
from cc_api.models.user import User

__all__ = [
    "Abonnement",
    "AbonnementStatus",
    "AdhesionIntent",
    "AdhesionIntentStatus",
    "Article",
    "AuthToken",
    "Author",
    "Base",
    "Chunk",
    "Issue",
    "Membership",
    "MembershipSource",
    "MembershipTier",
    "User",
]

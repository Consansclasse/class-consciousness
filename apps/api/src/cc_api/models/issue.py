# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle Issue — numéro de revue (ex: « Bilan n°1 — Novembre 1933 »).

Un Issue groupe N Articles. Identifiant humain : `slug` (« bilan-1 »).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.article import Article


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    ark: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    journal_title: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    issue_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    license: Mapped[str] = mapped_column(Text, nullable=False)
    source_desc: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    articles: Mapped[list[Article]] = relationship(
        back_populates="issue", cascade="all, delete-orphan", passive_deletes=True
    )

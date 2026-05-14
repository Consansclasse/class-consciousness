# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle Work — œuvre ingérée (1 fichier TEI source ↔ 1 work).

Idempotence : works.sha256 UNIQUE sur les bytes bruts du fichier source.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.author import Author
    from cc_api.models.chunk import Chunk


class Work(Base):
    __tablename__ = "works"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ark: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("authors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    license: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    author: Mapped[Author] = relationship(back_populates="works")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="work", cascade="all, delete-orphan", passive_deletes=True
    )

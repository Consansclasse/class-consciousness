# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle Article — texte signé à l'intérieur d'un Issue.

Plusieurs articles par numéro. Slug unique au sein de son issue parent.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.author import Author
    from cc_api.models.chunk import Chunk
    from cc_api.models.issue import Issue


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("issue_id", "slug", name="uq_articles_issue_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_id: Mapped[int] = mapped_column(
        ForeignKey("issues.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slug: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    ark: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[int] = mapped_column(
        ForeignKey("authors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    idx_in_issue: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    inserted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    issue: Mapped[Issue] = relationship(back_populates="articles")
    author: Mapped[Author] = relationship(back_populates="articles")
    chunks: Mapped[list[Chunk]] = relationship(
        back_populates="article", cascade="all, delete-orphan", passive_deletes=True
    )

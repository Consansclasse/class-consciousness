# SPDX-License-Identifier: AGPL-3.0-or-later
"""Modèle Author — auteur d'un Article.

Identifiants d'autorité optionnels : VIAF, IdRef, Wikidata.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from cc_api.models.base import Base

if TYPE_CHECKING:
    from cc_api.models.article import Article


class Author(Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    viaf_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    idref_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    wikidata_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    death_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    articles: Mapped[list[Article]] = relationship(back_populates="author")

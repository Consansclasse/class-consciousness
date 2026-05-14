# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke test des modèles — pas d'import cyclique, Base.metadata cohérente."""

from __future__ import annotations


def test_base_imports_without_pulling_services() -> None:
    """R3 : modèles n'importent rien de cc_api.services / cc_api.clients (sauf db ?)."""
    import sys

    for mod_name in list(sys.modules):
        if mod_name.startswith("cc_api."):
            del sys.modules[mod_name]

    from cc_api.models import Author, Base, Chunk, Work  # noqa: F401

    cc_modules = {m for m in sys.modules if m.startswith("cc_api.")}
    forbidden = {m for m in cc_modules if m.startswith(("cc_api.services", "cc_api.routers"))}
    assert not forbidden, f"modèles ont importé : {forbidden}"


def test_base_metadata_lists_all_tables() -> None:
    from cc_api.models import Base

    table_names = set(Base.metadata.tables.keys())
    assert table_names == {"authors", "works", "chunks"}


def test_works_has_unique_sha256_and_ark() -> None:
    from cc_api.models import Work

    sha_col = Work.__table__.c.sha256
    ark_col = Work.__table__.c.ark
    assert sha_col.unique is True
    assert ark_col.unique is True


def test_chunks_cascade_delete_from_work() -> None:
    from cc_api.models import Chunk

    fk = next(iter(Chunk.__table__.c.work_id.foreign_keys))
    assert fk.ondelete == "CASCADE"

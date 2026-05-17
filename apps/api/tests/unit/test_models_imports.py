# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke test des modèles — pas d'import cyclique, Base.metadata cohérente."""

from __future__ import annotations


def test_base_imports_without_pulling_services() -> None:
    """R3 : modèles n'importent rien de cc_api.services / cc_api.routers."""
    import sys

    for mod_name in list(sys.modules):
        if mod_name.startswith("cc_api."):
            del sys.modules[mod_name]

    from cc_api.models import (  # noqa: F401
        AdhesionIntent,
        Article,
        Author,
        AuthToken,
        Base,
        Chunk,
        Issue,
        Membership,
        User,
    )

    cc_modules = {m for m in sys.modules if m.startswith("cc_api.")}
    forbidden = {m for m in cc_modules if m.startswith(("cc_api.services", "cc_api.routers"))}
    assert not forbidden, f"modèles ont importé : {forbidden}"


def test_base_metadata_lists_all_tables() -> None:
    from cc_api.models import Base

    table_names = set(Base.metadata.tables.keys())
    assert table_names == {
        "authors",
        "issues",
        "articles",
        "chunks",
        "users",
        "memberships",
        "auth_tokens",
        "adhesion_intents",
        "abonnements",
    }


def test_issues_have_unique_sha256_and_ark() -> None:
    """L'idempotence et la persistance des URI sont au niveau Issue."""
    from cc_api.models import Issue

    sha_col = Issue.__table__.c.sha256
    ark_col = Issue.__table__.c.ark
    slug_col = Issue.__table__.c.slug
    assert sha_col.unique is True
    assert ark_col.unique is True
    assert slug_col.unique is True


def test_articles_have_unique_ark() -> None:
    """Chaque article expose un ARK propre (composite issue/article)."""
    from cc_api.models import Article

    ark_col = Article.__table__.c.ark
    assert ark_col.unique is True


def test_chunks_cascade_delete_from_article() -> None:
    from cc_api.models import Chunk

    fk = next(iter(Chunk.__table__.c.article_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_articles_cascade_delete_from_issue() -> None:
    from cc_api.models import Article

    fk = next(iter(Article.__table__.c.issue_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_articles_restrict_delete_on_author() -> None:
    """RESTRICT : on n'efface pas un auteur tant qu'il a des articles."""
    from cc_api.models import Article

    fk = next(iter(Article.__table__.c.author_id.foreign_keys))
    assert fk.ondelete == "RESTRICT"


def test_users_email_unique() -> None:
    from cc_api.models import User

    assert User.__table__.c.email.unique is True


def test_memberships_cascade_delete_from_user() -> None:
    from cc_api.models import Membership

    fk = next(iter(Membership.__table__.c.user_id.foreign_keys))
    assert fk.ondelete == "CASCADE"


def test_auth_tokens_hash_unique() -> None:
    from cc_api.models import AuthToken

    assert AuthToken.__table__.c.token_hash.unique is True

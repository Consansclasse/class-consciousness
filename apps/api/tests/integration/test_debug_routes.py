# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests des routes /__debug/* — vue panoptique de l'app pour l'agent IA."""

from __future__ import annotations

from typing import Any


def test_debug_state_returns_panoptic_view(client: Any) -> None:
    """GET /__debug/state retourne un JSON avec env, git, alembic, postgres, qdrant, redis."""
    response = client.get("/__debug/state")
    # En l'absence de services live, l'endpoint répond quand même (avec _error dans les sections).
    assert response.status_code == 200
    body = response.json()
    assert body["env"] == "dev"
    assert "git" in body
    assert "alembic" in body
    assert "postgres" in body
    assert "qdrant" in body
    assert "redis" in body


def test_debug_state_refused_outside_dev(client: Any, monkeypatch: Any) -> None:
    """Tout endpoint /__debug doit refuser si CC_API_ENV != dev."""
    from cc_api.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "env", "prod")
    response = client.get("/__debug/state")
    assert response.status_code == 403


def test_debug_reset_refused_outside_dev(client: Any, monkeypatch: Any) -> None:
    """POST /__debug/reset doit refuser si CC_API_ENV != dev."""
    from cc_api.core import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "env", "staging")
    response = client.post("/__debug/reset")
    assert response.status_code == 403

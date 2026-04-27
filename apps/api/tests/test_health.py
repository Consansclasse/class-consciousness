# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi.testclient import TestClient

from cc_api.main import app


def test_health() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests unitaires du client Voyage AI.

httpx.MockTransport est un transport, pas un mock métier — autorisé.
Pas de fallback OpenAI : si Voyage échoue, le client propage l'erreur.
"""

from __future__ import annotations

import json

import httpx
import pytest
from cc_api.clients.voyage import VOYAGE_URL, VoyageClient, VoyageError


def _ok_response(n: int, dim: int = 1024) -> dict[str, object]:
    return {
        "data": [{"embedding": [0.001 * (i + 1)] * dim, "index": i} for i in range(n)],
        "model": "voyage-4",
        "usage": {"total_tokens": n * 5},
    }


async def test_embed_batch_serializes_request_correctly() -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_ok_response(1))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        vc = VoyageClient(api_key="sk-test", client=client, backoff_base=0)
        await vc.embed_batch(["hello world"])

    assert len(captured) == 1
    req = captured[0]
    assert str(req.url) == VOYAGE_URL
    assert req.headers["authorization"] == "Bearer sk-test"
    body = json.loads(req.content)
    assert body["model"] == "voyage-4"
    assert body["input"] == ["hello world"]


async def test_embed_batch_chunks_at_128() -> None:
    captured: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        n = len(body["input"])
        captured.append(n)
        return httpx.Response(200, json=_ok_response(n))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        vc = VoyageClient(api_key="sk-test", client=client, backoff_base=0)
        result = await vc.embed_batch([f"text-{i}" for i in range(300)])

    assert captured == [128, 128, 44]
    assert len(result) == 300


async def test_retry_on_5xx_up_to_3_times() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, text="upstream error")
        return httpx.Response(200, json=_ok_response(1))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        vc = VoyageClient(api_key="sk-test", client=client, backoff_base=0)
        result = await vc.embed_batch(["x"])

    assert calls["n"] == 3
    assert len(result) == 1


async def test_no_retry_on_4xx() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, text="unauthorized")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        vc = VoyageClient(api_key="sk-bad", client=client, backoff_base=0)
        with pytest.raises(VoyageError, match=r"(?i)401"):
            await vc.embed_batch(["x"])

    assert calls["n"] == 1


async def test_raises_when_5xx_exhausts_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="permanent failure")

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        vc = VoyageClient(api_key="sk-test", client=client, backoff_base=0)
        with pytest.raises(VoyageError):
            await vc.embed_batch(["x"])


def test_raises_explicit_error_on_missing_api_key() -> None:
    with pytest.raises(RuntimeError, match=r"(?i)VOYAGE_API_KEY"):
        VoyageClient(api_key="")
    with pytest.raises(RuntimeError, match=r"(?i)VOYAGE_API_KEY"):
        VoyageClient(api_key=None)  # type: ignore[arg-type]


async def test_embed_returns_dim_vectors_in_order() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json=_ok_response(len(body["input"]), dim=1024))

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        vc = VoyageClient(api_key="sk-test", client=client, backoff_base=0)
        result = await vc.embed_batch(["a", "b", "c"])

    assert len(result) == 3
    assert all(len(vec) == 1024 for vec in result)

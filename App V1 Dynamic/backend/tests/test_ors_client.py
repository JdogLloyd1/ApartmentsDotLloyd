"""Unit tests for :mod:`app.routing.ors_client`.

We stub the HTTP layer with a custom ``httpx.MockTransport`` so the tests
run offline and never need an ORS API key.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.routing.ors_client import ORSClient, ORSError

FIXTURES = Path(__file__).parent / "fixtures" / "ors"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _transport(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        headers={
            "Authorization": "test-key",
            "Content-Type": "application/json",
        },
    )


@pytest.mark.asyncio
async def test_matrix_flattens_durations_and_posts_correct_body() -> None:
    payload = _load("matrix_foot_walking.json")
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=payload)

    async with _transport(handler) as http_client:
        client = ORSClient("test-key", client=http_client)
        durations = await client.matrix(
            "foot-walking",
            sources=[(-71.1429, 42.3944), (-71.1439, 42.3941)],
            destination=(-71.1426, 42.3954),
        )

    assert durations[:2] == [72.3, 82.9]
    assert captured["url"].endswith("/v2/matrix/foot-walking")
    assert captured["body"]["sources"] == [0, 1]
    assert captured["body"]["destinations"] == [2]
    assert captured["body"]["locations"][-1] == [-71.1426, 42.3954]


@pytest.mark.asyncio
async def test_isochrones_returns_feature_collection() -> None:
    payload = _load("isochrones_foot_walking.json")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with _transport(handler) as http_client:
        client = ORSClient("test-key", client=http_client)
        response = await client.isochrones(
            "foot-walking",
            anchor=(-71.1426, 42.3954),
            range_seconds=[300, 600, 900],
        )

    assert response["type"] == "FeatureCollection"
    assert len(response["features"]) == 3
    assert response["features"][0]["properties"]["value"] == 300


@pytest.mark.asyncio
async def test_non_2xx_raises_ors_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    async with _transport(handler) as http_client:
        client = ORSClient("test-key", client=http_client)
        with pytest.raises(ORSError):
            await client.matrix(
                "foot-walking",
                sources=[(-71.14, 42.39)],
                destination=(-71.14, 42.40),
            )


def test_constructor_requires_api_key() -> None:
    with pytest.raises(ValueError):
        ORSClient("")

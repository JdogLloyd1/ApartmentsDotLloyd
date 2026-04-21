"""Smoke tests for the /api/health endpoint."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    """The liveness probe always returns status=ok."""

    response = client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["app"] == "Alewife Apartment Intelligence"
    assert "version" in payload
    assert "environment" in payload


def test_openapi_docs_available(client: TestClient) -> None:
    """OpenAPI docs render so developers can inspect the API surface."""

    response = client.get("/docs")

    assert response.status_code == 200
    assert "swagger" in response.text.lower()

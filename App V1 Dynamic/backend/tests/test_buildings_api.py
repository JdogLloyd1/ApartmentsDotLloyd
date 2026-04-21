"""Integration tests for the /api/buildings endpoints."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import configure_engine, reset_engine
from app.main import create_app
from app.seed.loader import DEFAULT_SEED_FILE, load_buildings


@pytest.fixture
def seeded_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A test client backed by a fresh SQLite DB populated from the seed."""

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")

    load_buildings(DEFAULT_SEED_FILE)

    app = create_app()
    with TestClient(app) as http_client:
        yield http_client

    reset_engine()


def test_list_returns_all_buildings(seeded_client: TestClient) -> None:
    """GET /api/buildings returns every seeded building."""

    response = seeded_client.get("/api/buildings")

    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == 19

    first = payload[0]
    for key in ("slug", "name", "address", "lat", "lng", "score", "amenities"):
        assert key in first


def test_list_uses_js_field_aliases(seeded_client: TestClient) -> None:
    """Field aliases match the static dashboard's JS property names."""

    response = seeded_client.get("/api/buildings")
    first = response.json()[0]

    assert "oneBR" in first
    assert "twoBR" in first
    assert "oneBRSrc" in first
    assert "wlabel" in first
    assert "rc" in first


def test_detail_returns_single_building(seeded_client: TestClient) -> None:
    """GET /api/buildings/{slug} returns the matching building."""

    response = seeded_client.get("/api/buildings/hanover-alewife")

    assert response.status_code == 200
    payload = response.json()
    assert payload["slug"] == "hanover-alewife"
    assert payload["name"] == "Hanover Alewife"
    assert payload["rating"] == 4.8
    assert payload["score"] == 67


def test_detail_returns_404_for_unknown_slug(seeded_client: TestClient) -> None:
    """Unknown slugs return 404 with a helpful detail."""

    response = seeded_client.get("/api/buildings/does-not-exist")

    assert response.status_code == 404
    assert "does-not-exist" in response.json()["detail"]


def test_health_reports_row_count(seeded_client: TestClient) -> None:
    """After seeding the DB, /api/health reports the building count."""

    response = seeded_client.get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["building_count"] == 19
    assert payload["schema_version"] == 1

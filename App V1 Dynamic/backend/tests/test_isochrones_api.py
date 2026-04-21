"""Tests for ``/api/isochrones`` and live-time fallbacks in ``/api/buildings``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.config import get_settings
from app.db import configure_engine, get_engine, init_db, reset_engine, session_scope
from app.main import create_app
from app.models import Building, Isochrone, TravelTime


@pytest.fixture
def isochrone_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db_path = tmp_path / "iso_api.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    app = create_app()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        reset_engine()
        get_settings.cache_clear()


def _seed_building(**overrides: object) -> Building:
    defaults = dict(
        slug="hanover-alewife",
        name="Hanover Alewife",
        nbhd="Cambridge",
        address="420 Rindge Ave",
        lat=42.3944,
        lng=-71.1429,
        seed_walk_min=7,
        seed_drive_min=4,
        seed_one_br=3200,
        seed_rating=4.1,
    )
    defaults.update(overrides)
    return Building(**defaults)  # type: ignore[arg-type]


def test_isochrones_endpoint_returns_walk_and_drive_groups(isochrone_client: TestClient) -> None:
    with session_scope() as session:
        session.add_all(
            [
                Isochrone(
                    mode="walk",
                    minutes=5,
                    anchor="alewife_t",
                    geojson={"type": "Feature", "properties": {"value": 300}},
                ),
                Isochrone(
                    mode="walk",
                    minutes=10,
                    anchor="alewife_t",
                    geojson={"type": "Feature", "properties": {"value": 600}},
                ),
                Isochrone(
                    mode="drive",
                    minutes=5,
                    anchor="rt2_ramp",
                    geojson={"type": "Feature", "properties": {"value": 300}},
                ),
            ]
        )

    response = isochrone_client.get("/api/isochrones")
    assert response.status_code == 200
    data = response.json()
    assert {item["minutes"] for item in data["walk"]} == {5, 10}
    assert {item["minutes"] for item in data["drive"]} == {5}
    assert all(item["geojson"]["type"] == "Feature" for item in data["walk"])
    assert data["walk"][0]["anchor"] == "alewife_t"
    assert data["drive"][0]["anchor"] == "rt2_ramp"


def test_isochrones_endpoint_is_empty_when_no_rows(isochrone_client: TestClient) -> None:
    response = isochrone_client.get("/api/isochrones")
    assert response.status_code == 200
    assert response.json() == {"walk": [], "drive": []}


def test_building_endpoint_prefers_live_travel_time(isochrone_client: TestClient) -> None:
    with session_scope() as session:
        session.add(_seed_building())
    with session_scope() as session:
        building = session.exec(select(Building).where(Building.slug == "hanover-alewife")).one()
        session.add(
            TravelTime(
                building_id=building.id,  # type: ignore[arg-type]
                mode="walk",
                destination="alewife_t",
                minutes=2.5,
                source="ors",
            )
        )
        session.add(
            TravelTime(
                building_id=building.id,  # type: ignore[arg-type]
                mode="drive",
                destination="rt2_ramp",
                minutes=8.75,
                source="ors",
            )
        )

    response = isochrone_client.get("/api/buildings/hanover-alewife")
    assert response.status_code == 200
    payload = response.json()
    assert payload["walk"] == 2
    assert payload["drive"] == 9


def test_building_endpoint_falls_back_to_seed_without_travel_time(
    isochrone_client: TestClient,
) -> None:
    with session_scope() as session:
        session.add(_seed_building(slug="fresh-pond"))

    response = isochrone_client.get("/api/buildings/fresh-pond")
    assert response.status_code == 200
    payload = response.json()
    assert payload["walk"] == 7
    assert payload["drive"] == 4


def test_list_buildings_uses_travel_times_when_present(isochrone_client: TestClient) -> None:
    with session_scope() as session:
        session.add(_seed_building(slug="alpha", seed_walk_min=99, seed_drive_min=99))
        session.add(_seed_building(slug="bravo", seed_walk_min=10, seed_drive_min=10))
    with session_scope() as session:
        alpha = session.exec(select(Building).where(Building.slug == "alpha")).one()
        session.add(
            TravelTime(
                building_id=alpha.id,  # type: ignore[arg-type]
                mode="walk",
                destination="alewife_t",
                minutes=3.0,
                source="ors",
            )
        )

    response = isochrone_client.get("/api/buildings")
    assert response.status_code == 200
    items = {item["slug"]: item for item in response.json()}
    assert items["alpha"]["walk"] == 3
    assert items["bravo"]["walk"] == 10


def test_engine_uses_get_engine(isochrone_client: TestClient) -> None:
    assert get_engine() is not None

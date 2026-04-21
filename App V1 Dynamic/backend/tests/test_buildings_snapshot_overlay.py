"""``/api/buildings`` prefers the newest price + rating snapshots over seed."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from app.config import get_settings
from app.db import configure_engine, init_db, reset_engine, session_scope
from app.main import create_app
from app.models import Building, PriceSnapshot, RatingSnapshot, TravelTime


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db_path = tmp_path / "overlay.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    app = create_app()
    with session_scope() as session:
        session.add(
            Building(
                slug="hanover-alewife",
                name="Hanover Alewife",
                nbhd="Cambridge",
                address="420 Rindge Ave",
                lat=42.3944,
                lng=-71.1429,
                seed_rating=4.1,
                seed_review_count=100,
                seed_one_br=3000,
                seed_two_br=3800,
                seed_walk_min=7,
                seed_drive_min=4,
                seed_one_br_src="est.",
            )
        )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        reset_engine()
        get_settings.cache_clear()


def test_api_uses_latest_snapshots(api: TestClient) -> None:
    with session_scope() as session:
        building = session.exec(select(Building).where(Building.slug == "hanover-alewife")).one()
        assert building.id is not None
        now = datetime.now(UTC)
        session.add(
            PriceSnapshot(
                building_id=building.id,
                studio=None,
                one_br=3275,
                two_br=4200,
                studio_src=None,
                one_br_src="from $3,275",
                two_br_src="from $4,200",
                source_url="https://example.com/hanover",
                fetched_at=now - timedelta(hours=2),
            )
        )
        session.add(
            PriceSnapshot(
                building_id=building.id,
                studio=None,
                one_br=3350,
                two_br=4300,
                studio_src=None,
                one_br_src="from $3,350",
                two_br_src="from $4,300",
                source_url="https://example.com/hanover",
                fetched_at=now,
            )
        )
        session.add(
            RatingSnapshot(
                building_id=building.id,
                rating=4.8,
                review_count=247,
                source_url="https://maps.google.com",
                fetched_at=now,
            )
        )
        session.add(
            TravelTime(
                building_id=building.id,
                mode="walk",
                destination="alewife_t",
                minutes=5.0,
                source="ors",
            )
        )

    response = api.get("/api/buildings/hanover-alewife")
    payload = response.json()

    assert response.status_code == 200
    assert payload["oneBR"] == 3350
    assert payload["oneBRSrc"] == "from $3,350"
    assert payload["twoBR"] == 4300
    assert payload["rating"] == 4.8
    assert payload["rc"] == 247
    assert payload["walk"] == 5
    assert payload["drive"] == 4
    assert payload["pricesFetchedAt"] is not None
    assert payload["ratingFetchedAt"] is not None


def test_list_endpoint_uses_overlay_for_every_building(api: TestClient) -> None:
    with session_scope() as session:
        building = session.exec(select(Building).where(Building.slug == "hanover-alewife")).one()
        session.add(
            PriceSnapshot(
                building_id=building.id,  # type: ignore[arg-type]
                one_br=3333,
                one_br_src="from $3,333",
            )
        )

    response = api.get("/api/buildings")
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["oneBR"] == 3333


def test_building_without_snapshots_falls_back_to_seed(api: TestClient) -> None:
    response = api.get("/api/buildings/hanover-alewife")
    payload = response.json()

    assert payload["oneBR"] == 3000
    assert payload["rating"] == 4.1
    assert payload["walk"] == 7
    assert payload["drive"] == 4
    assert payload["pricesFetchedAt"] is None
    assert payload["ratingFetchedAt"] is None

"""Integration tests for travel-time + isochrone refresh services.

Uses a fake :class:`ORSClient` so the database paths are exercised end-to-end
without any network or API-key dependency.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.db import configure_engine, get_engine, init_db, reset_engine, session_scope
from app.models import Building, Isochrone, TravelTime
from app.routing.isochrone_service import refresh_isochrones
from app.routing.ors_client import ORSClient
from app.routing.travel_time_service import refresh_travel_times

FIXTURES = Path(__file__).parent / "fixtures" / "ors"


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class _FakeORSClient:
    """Drop-in replacement for :class:`ORSClient` that serves fixture data."""

    def __init__(self, num_buildings: int) -> None:
        self._num_buildings = num_buildings
        self.matrix_calls: list[str] = []
        self.isochrone_calls: list[str] = []

    async def matrix(
        self,
        profile: str,
        *,
        sources: list[tuple[float, float]],
        destination: tuple[float, float],
    ) -> list[float | None]:
        self.matrix_calls.append(profile)
        name = "matrix_foot_walking.json" if profile == "foot-walking" else "matrix_driving_car.json"
        payload = _load(name)
        durations: list[list[float]] = payload["durations"]
        base = [row[0] for row in durations]
        result: list[float | None] = []
        for i in range(len(sources)):
            result.append(base[i % len(base)])
        return result

    async def isochrones(
        self,
        profile: str,
        *,
        anchor: tuple[float, float],
        range_seconds: list[int],
    ) -> dict[str, Any]:
        self.isochrone_calls.append(profile)
        name = (
            "isochrones_foot_walking.json"
            if profile == "foot-walking"
            else "isochrones_driving_car.json"
        )
        return _load(name)

    async def aclose(self) -> None:
        return None


@pytest.fixture
def seeded_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Spin up a fresh DB with a handful of buildings seeded."""

    db_path = tmp_path / "routing.db"
    monkeypatch.setenv("ORS_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    try:
        with session_scope() as session:
            for i, slug in enumerate(["alpha", "bravo", "charlie"]):
                session.add(
                    Building(
                        slug=slug,
                        name=f"Building {slug}",
                        nbhd="Alewife",
                        address=f"{i} Test St",
                        lat=42.39 + i * 0.001,
                        lng=-71.14 - i * 0.001,
                    )
                )
        yield
    finally:
        reset_engine()
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_refresh_travel_times_writes_rows_per_mode(seeded_db: None) -> None:
    client = _FakeORSClient(num_buildings=3)
    counts = await refresh_travel_times(client=client)  # type: ignore[arg-type]

    assert counts == {"walk": 3, "drive": 3}
    assert client.matrix_calls == ["foot-walking", "driving-car"]

    with Session(get_engine()) as session:
        rows = session.exec(select(TravelTime)).all()

    assert len(rows) == 6
    modes = {row.mode for row in rows}
    destinations = {row.destination for row in rows}
    assert modes == {"walk", "drive"}
    assert destinations == {"alewife_t", "rt2_ramp"}
    assert all(row.source == "ors" for row in rows)


@pytest.mark.asyncio
async def test_refresh_travel_times_is_idempotent(seeded_db: None) -> None:
    client = _FakeORSClient(num_buildings=3)
    await refresh_travel_times(client=client)  # type: ignore[arg-type]
    await refresh_travel_times(client=client)  # type: ignore[arg-type]

    with Session(get_engine()) as session:
        rows = session.exec(select(TravelTime)).all()

    assert len(rows) == 6


@pytest.mark.asyncio
async def test_refresh_isochrones_replaces_existing_rows(seeded_db: None) -> None:
    client = _FakeORSClient(num_buildings=3)
    counts = await refresh_isochrones(client=client)  # type: ignore[arg-type]

    assert counts == {"walk": 3, "drive": 3}
    assert client.isochrone_calls == ["foot-walking", "driving-car"]

    with Session(get_engine()) as session:
        rows = session.exec(select(Isochrone)).all()

    assert len(rows) == 6
    walk_minutes = sorted(r.minutes for r in rows if r.mode == "walk")
    drive_minutes = sorted(r.minutes for r in rows if r.mode == "drive")
    assert walk_minutes == [5, 10, 15]
    assert drive_minutes == [2, 5, 10]
    assert all(row.geojson.get("type") == "Feature" for row in rows)

    await refresh_isochrones(client=client)  # type: ignore[arg-type]
    with Session(get_engine()) as session:
        rows_again = session.exec(select(Isochrone)).all()
    assert len(rows_again) == 6


@pytest.mark.asyncio
async def test_refresh_travel_times_without_api_key_raises(
    seeded_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ORS_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError):
        await refresh_travel_times()


def test_ors_client_import_surface() -> None:
    """Guardrail against accidentally renaming the public error class."""

    from app.routing import ors_client

    assert issubclass(ors_client.ORSError, RuntimeError)
    assert hasattr(ors_client, "ORSClient")


def test_fake_client_matches_real_client_protocol() -> None:
    """Keep the fake aligned with the real client's async surface."""

    fake = _FakeORSClient(num_buildings=1)
    for attr in ("matrix", "isochrones", "aclose"):
        assert hasattr(fake, attr)
        assert hasattr(ORSClient, attr)

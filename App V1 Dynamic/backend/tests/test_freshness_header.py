"""``/api/buildings`` and ``/api/isochrones`` must stamp ``X-Data-Freshness``."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cache import invalidate_all
from app.config import get_settings
from app.db import configure_engine, init_db, reset_engine, session_scope
from app.main import create_app
from app.models import Building


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db_path = tmp_path / "freshness.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    invalidate_all()
    with session_scope() as session:
        session.add(
            Building(
                slug="x",
                name="X",
                nbhd="Cambridge",
                address="1 Test Way",
                lat=42.4,
                lng=-71.1,
                seed_walk_min=5,
                seed_drive_min=2,
            )
        )
    app = create_app()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        reset_engine()
        get_settings.cache_clear()
        invalidate_all()


def test_buildings_endpoint_stamps_freshness_header(api: TestClient) -> None:
    response = api.get("/api/buildings")
    assert response.status_code == 200
    assert "X-Data-Freshness" in response.headers
    assert int(response.headers["X-Data-Freshness"]) == 0


def test_buildings_endpoint_returns_cached_payload(api: TestClient) -> None:
    """Successive reads should hit the cache; second call age \u2265 first."""

    first = api.get("/api/buildings")
    second = api.get("/api/buildings")
    assert first.json() == second.json()
    assert int(second.headers["X-Data-Freshness"]) >= int(first.headers["X-Data-Freshness"])


def test_isochrones_endpoint_stamps_freshness_header(api: TestClient) -> None:
    response = api.get("/api/isochrones")
    assert response.status_code == 200
    assert "X-Data-Freshness" in response.headers

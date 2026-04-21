"""End-to-end behavior of ``POST /api/refresh`` and the bearer guard.

Patches the orchestration entry point so we never touch ORS or
Playwright; the goal here is the auth boundary, the polling endpoint,
and that the cache is invalidated.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cache import invalidate_all
from app.config import get_settings
from app.db import configure_engine, init_db, reset_engine, session_scope
from app.main import create_app
from app.models import Building, RefreshRun

VALID_TOKEN = "test-token-123"


def _seed_a_building() -> None:
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


@pytest.fixture
def api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    db_path = tmp_path / "refresh.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("REFRESH_BEARER_TOKEN", VALID_TOKEN)
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    invalidate_all()
    _seed_a_building()
    app = create_app()
    try:
        with TestClient(app) as client:
            yield client
    finally:
        reset_engine()
        get_settings.cache_clear()
        invalidate_all()


@pytest.fixture
def stub_orchestration(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """Replace the heavy refresh path with a tiny coroutine."""

    counters = {"runs": 0}

    async def _fake_run_steps(
        run_id: int,
        *,
        fetcher: object | None,
        do_routing: bool,
        do_scrapers: bool,
        slugs: list[str] | None,
    ) -> dict[str, object]:
        counters["runs"] += 1
        await asyncio.sleep(0)
        return {
            "steps": {
                "travel_times": {"status": "ok", "walk": 1, "drive": 1},
                "prices": {
                    "status": "ok",
                    "attempted": 0,
                    "succeeded": 0,
                    "failed": 0,
                    "skipped": 0,
                },
            }
        }

    monkeypatch.setattr("app.refresh_service._run_steps", _fake_run_steps)
    return counters


def test_refresh_requires_bearer_token(api: TestClient) -> None:
    response = api.post("/api/refresh")
    assert response.status_code == 401


def test_refresh_rejects_wrong_token(api: TestClient) -> None:
    response = api.post(
        "/api/refresh",
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


def test_refresh_accepts_valid_token_and_returns_run_id(
    api: TestClient, stub_orchestration: dict[str, int]
) -> None:
    response = api.post(
        "/api/refresh",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        json={"skip_routing": True, "skip_scrapers": True},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "running"
    assert isinstance(body["run_id"], int)


def test_refresh_status_endpoint_returns_persisted_row(
    api: TestClient, stub_orchestration: dict[str, int]
) -> None:
    trigger = api.post(
        "/api/refresh",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        json={},
    )
    run_id = trigger.json()["run_id"]

    for _ in range(50):
        status_resp = api.get(f"/api/refresh/{run_id}")
        if status_resp.json()["status"] != "running":
            break
        import time

        time.sleep(0.05)

    assert status_resp.status_code == 200
    payload = status_resp.json()
    assert payload["run_id"] == run_id
    assert payload["status"] in {"succeeded", "failed"}
    assert payload["finished_at"] is not None
    assert "steps" in payload["detail"]


def test_refresh_status_404_for_unknown_run(api: TestClient) -> None:
    response = api.get("/api/refresh/999999")
    assert response.status_code == 404


def test_refresh_returns_503_when_token_unconfigured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """If the server boots without a token, the route must hard-fail with ``503``.

    Patches the settings dependency directly because ``.env`` may carry
    a real token in the developer's checkout, and pydantic-settings
    reads that file regardless of the process environment.
    """

    db_path = tmp_path / "no-token.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    invalidate_all()

    from app.config import Settings

    def _settings_without_token() -> Settings:
        live = Settings()
        return live.model_copy(update={"refresh_bearer_token": None})

    monkeypatch.setattr("app.api.refresh.get_settings", _settings_without_token)

    app = create_app()
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/refresh",
                headers={"Authorization": "Bearer anything"},
            )
        assert response.status_code == 503
    finally:
        reset_engine()
        get_settings.cache_clear()
        invalidate_all()


def test_refresh_records_failure_when_step_fails(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing step must result in ``status="failed"`` even when the runner returns."""

    async def _failing_steps(
        run_id: int,
        *,
        fetcher: object | None,
        do_routing: bool,
        do_scrapers: bool,
        slugs: list[str] | None,
    ) -> dict[str, object]:
        return {"steps": {"prices": {"status": "error", "error": "boom"}}}

    monkeypatch.setattr("app.refresh_service._run_steps", _failing_steps)

    trigger = api.post(
        "/api/refresh",
        headers={"Authorization": f"Bearer {VALID_TOKEN}"},
        json={},
    )
    run_id = trigger.json()["run_id"]

    import time

    for _ in range(50):
        status_resp = api.get(f"/api/refresh/{run_id}")
        if status_resp.json()["status"] != "running":
            break
        time.sleep(0.05)

    assert status_resp.json()["status"] == "failed"

    with session_scope() as session:
        run = session.get(RefreshRun, run_id)
        assert run is not None
        assert run.status == "failed"

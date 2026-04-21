"""Direct unit tests for :mod:`app.refresh_service`.

Stubs out ORS and the scraper services so we exercise the orchestration
state-machine in isolation \u2014 success path, failure path, cache
invalidation.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.cache import get_or_compute, invalidate_all
from app.config import get_settings
from app.db import configure_engine, init_db, reset_engine, session_scope
from app.models import RefreshRun
from app.refresh_service import execute_refresh
from app.scrapers.price_service import PriceRefreshResult
from app.scrapers.rating_service import RatingRefreshResult


@pytest.fixture
def isolated_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    db_path = tmp_path / "service.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    invalidate_all()
    yield
    reset_engine()
    get_settings.cache_clear()
    invalidate_all()


@pytest.mark.asyncio
async def test_execute_refresh_success_persists_succeeded(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _ok_travel() -> dict[str, int]:
        return {"walk": 5, "drive": 5}

    async def _ok_iso() -> dict[str, int]:
        return {"walk": 3, "drive": 3}

    async def _ok_prices(*, fetcher: object | None = None, slugs: list[str] | None = None) -> PriceRefreshResult:
        return PriceRefreshResult(attempted=2, succeeded=2, failed=0, skipped=0)

    async def _ok_ratings(*, fetcher: object | None = None, slugs: list[str] | None = None) -> RatingRefreshResult:
        return RatingRefreshResult(attempted=2, succeeded=2, failed=0, skipped=0)

    monkeypatch.setattr("app.refresh_service.refresh_travel_times", _ok_travel)
    monkeypatch.setattr("app.refresh_service.refresh_isochrones", _ok_iso)
    monkeypatch.setattr("app.refresh_service.refresh_prices", _ok_prices)
    monkeypatch.setattr("app.refresh_service.refresh_ratings", _ok_ratings)

    run_id = await execute_refresh(
        trigger="manual",
        fetcher=object(),
        do_routing=True,
        do_scrapers=True,
    )

    with session_scope() as session:
        run = session.get(RefreshRun, run_id)
        assert run is not None
        assert run.status == "succeeded"
        assert run.finished_at is not None
        steps = run.detail["steps"]
        assert steps["travel_times"]["status"] == "ok"
        assert steps["prices"]["succeeded"] == 2


@pytest.mark.asyncio
async def test_execute_refresh_marks_failed_when_step_raises(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raising_travel() -> dict[str, int]:
        raise RuntimeError("ORS down")

    async def _ok_iso() -> dict[str, int]:
        return {"walk": 0, "drive": 0}

    async def _skip_prices(*, fetcher: object | None = None, slugs: list[str] | None = None) -> PriceRefreshResult:
        return PriceRefreshResult(attempted=0, succeeded=0, failed=0, skipped=0)

    async def _skip_ratings(*, fetcher: object | None = None, slugs: list[str] | None = None) -> RatingRefreshResult:
        return RatingRefreshResult(attempted=0, succeeded=0, failed=0, skipped=0)

    monkeypatch.setattr("app.refresh_service.refresh_travel_times", _raising_travel)
    monkeypatch.setattr("app.refresh_service.refresh_isochrones", _ok_iso)
    monkeypatch.setattr("app.refresh_service.refresh_prices", _skip_prices)
    monkeypatch.setattr("app.refresh_service.refresh_ratings", _skip_ratings)

    run_id = await execute_refresh(
        trigger="manual",
        fetcher=object(),
        do_routing=True,
        do_scrapers=True,
    )

    with session_scope() as session:
        run = session.get(RefreshRun, run_id)
        assert run is not None
        assert run.status == "failed"
        assert run.detail["steps"]["travel_times"]["status"] == "error"
        assert "ORS down" in run.detail["steps"]["travel_times"]["error"]


@pytest.mark.asyncio
async def test_execute_refresh_invalidates_cache(
    isolated_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful run must clear the response cache so stale rows aren't served."""

    counter = {"n": 0}

    def compute() -> int:
        counter["n"] += 1
        return counter["n"]

    first, _ = get_or_compute("buildings:list", compute)

    async def _noop_travel() -> dict[str, int]:
        return {"walk": 0, "drive": 0}

    async def _noop_iso() -> dict[str, int]:
        return {"walk": 0, "drive": 0}

    async def _noop_prices(*, fetcher: object | None = None, slugs: list[str] | None = None) -> PriceRefreshResult:
        return PriceRefreshResult(attempted=0, succeeded=0, failed=0, skipped=0)

    async def _noop_ratings(*, fetcher: object | None = None, slugs: list[str] | None = None) -> RatingRefreshResult:
        return RatingRefreshResult(attempted=0, succeeded=0, failed=0, skipped=0)

    monkeypatch.setattr("app.refresh_service.refresh_travel_times", _noop_travel)
    monkeypatch.setattr("app.refresh_service.refresh_isochrones", _noop_iso)
    monkeypatch.setattr("app.refresh_service.refresh_prices", _noop_prices)
    monkeypatch.setattr("app.refresh_service.refresh_ratings", _noop_ratings)

    await execute_refresh(
        trigger="manual",
        fetcher=object(),
        do_routing=True,
        do_scrapers=True,
    )

    second, _ = get_or_compute("buildings:list", compute)
    assert first == 1
    assert second == 2

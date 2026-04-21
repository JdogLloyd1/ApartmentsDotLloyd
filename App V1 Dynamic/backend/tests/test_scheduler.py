"""APScheduler wiring inside the FastAPI lifespan."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.cache import invalidate_all
from app.config import get_settings
from app.db import configure_engine, init_db, reset_engine
from app.main import create_app
from app.scheduler import get_scheduler, shutdown_scheduler


@pytest.fixture
def empty_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    db_path = tmp_path / "scheduler.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    invalidate_all()
    yield
    shutdown_scheduler()
    reset_engine()
    get_settings.cache_clear()
    invalidate_all()


def test_scheduler_disabled_by_default(
    empty_app: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REFRESH_SCHEDULER_ENABLED", raising=False)
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app):
        assert get_scheduler() is None


def test_scheduler_starts_when_enabled(
    empty_app: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("REFRESH_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("REFRESH_DAILY_CRON", "30 7 * * *")
    monkeypatch.setenv("REFRESH_HOURLY_CRON", "0 13-23 * * *")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app):
        scheduler = get_scheduler()
        assert scheduler is not None
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert {"daily_refresh", "hourly_prices"} <= job_ids
    assert get_scheduler() is None

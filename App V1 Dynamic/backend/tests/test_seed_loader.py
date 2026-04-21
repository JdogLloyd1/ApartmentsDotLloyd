"""Tests for :mod:`app.seed.loader`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.db import configure_engine, get_engine, reset_engine
from app.models import Building
from app.seed.loader import DEFAULT_SEED_FILE, load_buildings


@pytest.fixture
def sqlite_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the app at a throwaway SQLite DB for the duration of the test."""

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    yield
    reset_engine()


def test_load_inserts_all_buildings(sqlite_engine: None) -> None:
    """A first run inserts every building from the seed file."""

    inserted, updated = load_buildings(DEFAULT_SEED_FILE)

    assert inserted == 19
    assert updated == 0

    with Session(get_engine()) as session:
        count = len(session.exec(select(Building)).all())
    assert count == 19


def test_load_is_idempotent(sqlite_engine: None) -> None:
    """Re-running the loader does not create duplicates or mark updates."""

    first_insert, first_update = load_buildings(DEFAULT_SEED_FILE)
    second_insert, second_update = load_buildings(DEFAULT_SEED_FILE)

    assert first_insert == 19
    assert second_insert == 0
    assert first_update == 0
    assert second_update == 0


def test_rating_range_matches_source(sqlite_engine: None) -> None:
    """The loaded data's rating bounds match the static dashboard spot-checks."""

    load_buildings(DEFAULT_SEED_FILE)

    with Session(get_engine()) as session:
        ratings = [
            b.seed_rating for b in session.exec(select(Building)).all() if b.seed_rating is not None
        ]

    assert min(ratings) == pytest.approx(2.9)
    assert max(ratings) == pytest.approx(4.9)


def test_hanover_alewife_spot_check(sqlite_engine: None) -> None:
    """Hanover Alewife retains its published rating through the round-trip."""

    load_buildings(DEFAULT_SEED_FILE)

    with Session(get_engine()) as session:
        hanover = session.exec(select(Building).where(Building.slug == "hanover-alewife")).one()

    assert hanover.seed_rating == pytest.approx(4.8)
    assert hanover.seed_review_count == 510
    assert "Heated Garage" in hanover.amenities

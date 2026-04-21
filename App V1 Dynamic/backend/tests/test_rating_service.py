"""Integration tests for :mod:`app.scrapers.rating_service`."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.db import configure_engine, get_engine, init_db, reset_engine, session_scope
from app.models import Building, RatingSnapshot
from app.scrapers.rating_service import refresh_ratings

FIXTURES = Path(__file__).parent / "fixtures" / "scrapers"


class _FakeFetcher:
    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    async def fetch(self, url: str, *, wait_for_selector: str | None = None) -> str:
        self.calls.append(url)
        return self._mapping.get(url, "")


@pytest.fixture
def db_with_buildings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    db_path = tmp_path / "ratings.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    init_db()
    with session_scope() as session:
        session.add(
            Building(
                slug="hanover-alewife",
                name="Hanover Alewife",
                nbhd="Cambridge",
                address="420 Rindge Ave",
                lat=42.3944,
                lng=-71.1429,
                google_place_id="ChIJPlaceHanover",
            )
        )
        session.add(
            Building(
                slug="cambridge-park",
                name="Cambridge Park",
                nbhd="Cambridge",
                address="30 Cambridgepark Dr",
                lat=42.3943,
                lng=-71.1429,
                google_place_id=None,
            )
        )
    try:
        yield
    finally:
        reset_engine()
        get_settings.cache_clear()


async def _no_jitter(*_args: object, **_kwargs: object) -> None:
    return None


async def test_refresh_ratings_skips_buildings_without_place_id(
    db_with_buildings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.scrapers.rating_service.jitter", _no_jitter)
    aria_html = (FIXTURES / "google_aria_rating.html").read_text(encoding="utf-8")
    fetcher = _FakeFetcher(
        {"https://www.google.com/maps/place/?q=place_id:ChIJPlaceHanover": aria_html}
    )

    result = await refresh_ratings(fetcher=fetcher)  # type: ignore[arg-type]

    assert result.attempted == 1
    assert result.succeeded == 1
    assert result.skipped == 1
    assert fetcher.calls == ["https://www.google.com/maps/place/?q=place_id:ChIJPlaceHanover"]

    with Session(get_engine()) as session:
        snaps = session.exec(select(RatingSnapshot)).all()
    assert len(snaps) == 1
    assert snaps[0].rating == 4.8
    assert snaps[0].review_count == 247


async def test_refresh_ratings_uses_search_url_when_forced_by_slug(
    db_with_buildings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.scrapers.rating_service.jitter", _no_jitter)
    json_html = (FIXTURES / "google_json_rating.html").read_text(encoding="utf-8")
    expected_url = (
        "https://www.google.com/search?q=Cambridge%20Park%2030%20Cambridgepark%20Dr"
    )
    fetcher = _FakeFetcher({expected_url: json_html})

    result = await refresh_ratings(fetcher=fetcher, slugs=["cambridge-park"])  # type: ignore[arg-type]

    assert result.attempted == 1
    assert result.succeeded == 1
    assert fetcher.calls == [expected_url]

    with Session(get_engine()) as session:
        snap = session.exec(select(RatingSnapshot)).first()
    assert snap is not None
    assert snap.rating == 4.5
    assert snap.review_count == 259


async def test_refresh_ratings_handles_fetch_failure(
    db_with_buildings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.scrapers.rating_service.jitter", _no_jitter)

    class _ExplodingFetcher:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def fetch(self, url: str, *, wait_for_selector: str | None = None) -> str:
            self.calls.append(url)
            raise RuntimeError("simulated network blip")

    result = await refresh_ratings(fetcher=_ExplodingFetcher())  # type: ignore[arg-type]

    assert result.attempted == 1
    assert result.failed == 1

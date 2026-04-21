"""Integration tests for :mod:`app.scrapers.price_service`.

Uses an in-memory fake :class:`HTMLFetcher` so the service paths are
exercised end-to-end without a real browser.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.db import configure_engine, get_engine, init_db, reset_engine, session_scope
from app.models import Building, PriceSnapshot
from app.scrapers.price_service import refresh_prices

FIXTURES = Path(__file__).parent / "fixtures" / "scrapers"


class _FakeFetcher:
    """Returns stored HTML per URL; never touches the network."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self._mapping = mapping
        self.calls: list[str] = []

    async def fetch(self, url: str, *, wait_for_selector: str | None = None) -> str:
        self.calls.append(url)
        return self._mapping.get(url, "")


@pytest.fixture
def db_with_buildings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    db_path = tmp_path / "scrape.db"
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
                apartments_com_url="https://example.com/hanover",
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
                apartments_com_url=None,
            )
        )
    try:
        yield
    finally:
        reset_engine()
        get_settings.cache_clear()


async def test_refresh_prices_writes_snapshot_and_skips_missing(
    db_with_buildings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.scrapers.price_service.jitter", _no_jitter)
    fetcher = _FakeFetcher(
        {
            "https://example.com/hanover": (FIXTURES / "apartments_with_json_ld.html").read_text(
                encoding="utf-8"
            ),
        }
    )

    result = await refresh_prices(fetcher=fetcher)  # type: ignore[arg-type]

    assert result.attempted == 1
    assert result.succeeded == 1
    assert result.failed == 0
    assert result.skipped == 1

    with Session(get_engine()) as session:
        snapshots = session.exec(select(PriceSnapshot)).all()
    assert len(snapshots) == 1
    snap = snapshots[0]
    assert snap.one_br == 3275
    assert snap.studio == 2430
    assert snap.source == "apartments_com"
    assert snap.source_url == "https://example.com/hanover"


async def test_refresh_prices_handles_failed_scrape(
    db_with_buildings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.scrapers.price_service.jitter", _no_jitter)
    fetcher = _FakeFetcher({"https://example.com/hanover": ""})

    result = await refresh_prices(fetcher=fetcher)  # type: ignore[arg-type]

    assert result.attempted == 1
    assert result.succeeded == 0
    assert result.failed == 1


async def test_refresh_prices_scopes_to_requested_slug(
    db_with_buildings: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.scrapers.price_service.jitter", _no_jitter)
    fetcher = _FakeFetcher(
        {
            "https://example.com/hanover": (FIXTURES / "apartments_with_grid.html").read_text(
                encoding="utf-8"
            ),
        }
    )

    result = await refresh_prices(fetcher=fetcher, slugs=["hanover-alewife"])  # type: ignore[arg-type]

    assert result.attempted == 1
    assert fetcher.calls == ["https://example.com/hanover"]

    with Session(get_engine()) as session:
        snaps = session.exec(select(PriceSnapshot)).all()
    assert len(snaps) == 1


async def _no_jitter(*_args: object, **_kwargs: object) -> None:
    return None

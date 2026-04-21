"""Populate :class:`PriceSnapshot` rows from apartments.com."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session, select

from app.db import get_engine
from app.models import Building, PriceSnapshot
from app.scrapers.apartments_com import ApartmentsListing, parse_apartments_html
from app.scrapers.base import HTMLFetcher, PlaywrightFetcher, jitter

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class PriceRefreshResult:
    """Summary returned by :func:`refresh_prices`."""

    attempted: int
    succeeded: int
    failed: int
    skipped: int


async def _scrape_one(
    session: Session, fetcher: HTMLFetcher, building: Building
) -> ApartmentsListing | None:
    if not building.apartments_com_url or building.id is None:
        return None
    try:
        html = await fetcher.fetch(building.apartments_com_url)
    except Exception as exc:
        logger.exception("fetch failed for %s: %s", building.slug, exc)
        return None
    listing = parse_apartments_html(html)
    session.add(
        PriceSnapshot(
            building_id=building.id,
            studio=listing.studio,
            one_br=listing.one_br,
            two_br=listing.two_br,
            studio_src=listing.studio_src,
            one_br_src=listing.one_br_src,
            two_br_src=listing.two_br_src,
            source_url=building.apartments_com_url,
            source="apartments_com",
        )
    )
    return listing


async def refresh_prices(
    fetcher: HTMLFetcher | None = None,
    *,
    slugs: list[str] | None = None,
) -> PriceRefreshResult:
    """Scrape prices for every building with an ``apartments_com_url``.

    ``slugs`` narrows the scrape to a subset, matching the verification
    requirement of running against a handful of known buildings.
    """

    own_fetcher = fetcher is None
    if own_fetcher:
        fetcher = PlaywrightFetcher()
        await fetcher.__aenter__()
    assert fetcher is not None

    attempted = succeeded = failed = skipped = 0
    try:
        with Session(get_engine()) as session:
            query = select(Building)
            if slugs:
                query = query.where(Building.slug.in_(slugs))  # type: ignore[attr-defined]
            buildings = session.exec(query.order_by(Building.name)).all()
            for building in buildings:
                if not building.apartments_com_url:
                    skipped += 1
                    continue
                attempted += 1
                listing = await _scrape_one(session, fetcher, building)
                if listing is None:
                    failed += 1
                elif any((listing.studio, listing.one_br, listing.two_br)):
                    succeeded += 1
                else:
                    failed += 1
                await jitter()
            session.commit()
    finally:
        if own_fetcher:
            await fetcher.__aexit__(None, None, None)

    return PriceRefreshResult(
        attempted=attempted, succeeded=succeeded, failed=failed, skipped=skipped
    )

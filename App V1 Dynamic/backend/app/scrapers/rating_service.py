"""Populate :class:`RatingSnapshot` rows from Google Maps place pages."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import quote

from sqlmodel import Session, select

from app.db import get_engine
from app.models import Building, RatingSnapshot
from app.scrapers.base import HTMLFetcher, PlaywrightFetcher, jitter
from app.scrapers.google_places import GooglePlaceData, parse_google_html

logger = logging.getLogger(__name__)

GOOGLE_SEARCH_URL = "https://www.google.com/search?q={query}"
GOOGLE_PLACE_URL = "https://www.google.com/maps/place/?q=place_id:{place_id}"


@dataclass(frozen=True, slots=True)
class RatingRefreshResult:
    """Summary returned by :func:`refresh_ratings`."""

    attempted: int
    succeeded: int
    failed: int
    skipped: int


def _rating_url_for(building: Building) -> str:
    """Prefer place_id pages when available; fall back to a search query."""

    if building.google_place_id:
        return GOOGLE_PLACE_URL.format(place_id=building.google_place_id)
    query = quote(f"{building.name} {building.address}")
    return GOOGLE_SEARCH_URL.format(query=query)


async def _scrape_one(
    session: Session, fetcher: HTMLFetcher, building: Building
) -> GooglePlaceData | None:
    if building.id is None:
        return None
    url = _rating_url_for(building)
    try:
        html = await fetcher.fetch(url)
    except Exception as exc:
        logger.exception("fetch failed for %s: %s", building.slug, exc)
        return None
    data = parse_google_html(html)
    session.add(
        RatingSnapshot(
            building_id=building.id,
            rating=data.rating,
            review_count=data.review_count,
            source_url=url,
            source="google_places",
        )
    )
    return data


async def refresh_ratings(
    fetcher: HTMLFetcher | None = None,
    *,
    slugs: list[str] | None = None,
) -> RatingRefreshResult:
    """Scrape ratings for every building, skipping ones without a place_id.

    Unlike price scraping we fall back to a Google Search query when
    ``google_place_id`` is missing because even the no-ID path is
    usually good enough to surface a rating in the knowledge panel.
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
                if not building.google_place_id and slugs is None:
                    skipped += 1
                    continue
                attempted += 1
                data = await _scrape_one(session, fetcher, building)
                if data is None:
                    failed += 1
                elif data.rating is not None or data.review_count is not None:
                    succeeded += 1
                else:
                    failed += 1
                await jitter()
            session.commit()
    finally:
        if own_fetcher:
            await fetcher.__aexit__(None, None, None)

    return RatingRefreshResult(
        attempted=attempted, succeeded=succeeded, failed=failed, skipped=skipped
    )

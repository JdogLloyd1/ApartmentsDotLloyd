"""Top-level CLI: refresh everything (ORS + scrapers) in one command.

Usage::

    python -m app.refresh_cli
    python -m app.refresh_cli --skip-scrapers        # routing only
    python -m app.refresh_cli --skip-routing         # scrapers only
    python -m app.refresh_cli --slugs hanover-alewife,cambridge-park
"""

from __future__ import annotations

import argparse
import asyncio

from sqlmodel import Session, func, select

from app.db import get_engine
from app.models import Building
from app.routing.isochrone_service import refresh_isochrones
from app.routing.travel_time_service import refresh_travel_times
from app.scrapers.base import PlaywrightFetcher
from app.scrapers.price_service import refresh_prices
from app.scrapers.rating_service import refresh_ratings


def _parse_slugs(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [slug.strip() for slug in raw.split(",") if slug.strip()]


def _preflight_counts() -> tuple[int, int, int]:
    """Return ``(buildings, with_apartments_url, with_place_id)``.

    Used to print a human-readable hint before the refresh runs so a
    silently empty DB or an all-null ``scrape_targets.json`` doesn't
    masquerade as a successful refresh.
    """

    with Session(get_engine()) as session:
        total = session.exec(select(func.count()).select_from(Building)).one()
        with_price_url = session.exec(
            select(func.count())
            .select_from(Building)
            .where(Building.apartments_com_url.is_not(None))  # type: ignore[attr-defined]
        ).one()
        with_place_id = session.exec(
            select(func.count()).select_from(Building).where(Building.google_place_id.is_not(None))  # type: ignore[attr-defined]
        ).one()
    return int(total), int(with_price_url), int(with_place_id)


async def _run(args: argparse.Namespace) -> None:
    slugs = _parse_slugs(args.slugs)

    total, with_price_url, with_place_id = _preflight_counts()
    print(
        f"buildings: total={total} "
        f"with_apartments_com_url={with_price_url} "
        f"with_google_place_id={with_place_id}"
    )
    if total == 0:
        print("  -> DB is empty; run `make seed` before refreshing.")
    elif with_price_url == 0 and with_place_id == 0 and not args.skip_scrapers:
        print(
            "  -> No buildings have scrape targets yet. Edit "
            "App V1 Dynamic/backend/app/seed/scrape_targets.json, then "
            "re-run `make seed` so the loader merges the new values."
        )

    if not args.skip_routing:
        travel = await refresh_travel_times()
        iso = await refresh_isochrones()
        print("travel_times:", travel, "| isochrones:", iso)
    else:
        print("(skipped routing)")

    if not args.skip_scrapers:
        async with PlaywrightFetcher() as fetcher:
            prices = await refresh_prices(fetcher=fetcher, slugs=slugs)
            ratings = await refresh_ratings(fetcher=fetcher, slugs=slugs)
        print("prices:", prices)
        print("ratings:", ratings)
    else:
        print("(skipped scrapers)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-routing", action="store_true", help="Don't call ORS")
    parser.add_argument(
        "--skip-scrapers", action="store_true", help="Don't run Playwright scrapers"
    )
    parser.add_argument(
        "--slugs",
        help="Comma-separated building slugs to scrape (default: all with scrape targets).",
    )
    asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    main()

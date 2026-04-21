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

from app.routing.isochrone_service import refresh_isochrones
from app.routing.travel_time_service import refresh_travel_times
from app.scrapers.base import PlaywrightFetcher
from app.scrapers.price_service import refresh_prices
from app.scrapers.rating_service import refresh_ratings


def _parse_slugs(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [slug.strip() for slug in raw.split(",") if slug.strip()]


async def _run(args: argparse.Namespace) -> None:
    slugs = _parse_slugs(args.slugs)

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

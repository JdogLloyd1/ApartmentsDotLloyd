"""CLI: run both price and rating scrapers in sequence.

Usage::

    python -m app.scrapers.refresh_all
    python -m app.scrapers.refresh_all --slugs hanover-alewife,cambridge-park
"""

from __future__ import annotations

import argparse
import asyncio

from app.scrapers.base import PlaywrightFetcher
from app.scrapers.price_service import refresh_prices
from app.scrapers.rating_service import refresh_ratings


def _parse_slugs(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [slug.strip() for slug in raw.split(",") if slug.strip()]


async def _run(slugs: list[str] | None) -> None:
    async with PlaywrightFetcher() as fetcher:
        prices = await refresh_prices(fetcher=fetcher, slugs=slugs)
        ratings = await refresh_ratings(fetcher=fetcher, slugs=slugs)
    print("prices:", prices)
    print("ratings:", ratings)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--slugs",
        help="Comma-separated list of building slugs to scrape (default: all).",
    )
    args = parser.parse_args()
    asyncio.run(_run(_parse_slugs(args.slugs)))


if __name__ == "__main__":
    main()

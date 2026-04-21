"""CLI entry point: refresh ORS-driven routing tables in one call.

Usage::

    python -m app.routing.refresh_all
"""

from __future__ import annotations

import asyncio

from app.routing.isochrone_service import refresh_isochrones
from app.routing.travel_time_service import refresh_travel_times


async def _run() -> None:
    travel = await refresh_travel_times()
    iso = await refresh_isochrones()
    print(
        "travel_times:",
        travel,
        "| isochrones:",
        iso,
    )


def main() -> None:
    """Script entry: run both refreshes sequentially."""

    asyncio.run(_run())


if __name__ == "__main__":
    main()

"""Populate :class:`TravelTime` rows from OpenRouteService matrix calls."""

from __future__ import annotations

from dataclasses import dataclass

from sqlmodel import Session, delete, select

from app.config import get_settings
from app.db import get_engine
from app.models import Building, TravelTime
from app.routing.anchors import (
    ALEWIFE_T_LATLNG,
    RT2_RAMP_LATLNG,
    latlng_to_lonlat,
)
from app.routing.ors_client import ORSClient


@dataclass(frozen=True, slots=True)
class RouteRequest:
    """Description of a single matrix call."""

    mode: str
    destination_label: str
    profile: str
    destination_lonlat: tuple[float, float]


WALK_REQUEST = RouteRequest(
    mode="walk",
    destination_label="alewife_t",
    profile="foot-walking",
    destination_lonlat=latlng_to_lonlat(ALEWIFE_T_LATLNG),
)
DRIVE_REQUEST = RouteRequest(
    mode="drive",
    destination_label="rt2_ramp",
    profile="driving-car",
    destination_lonlat=latlng_to_lonlat(RT2_RAMP_LATLNG),
)


def _seconds_to_minutes(seconds: float | None) -> float | None:
    if seconds is None:
        return None
    return round(seconds / 60.0, 2)


async def _refresh_one(session: Session, client: ORSClient, request: RouteRequest) -> int:
    """Compute a single matrix and upsert rows. Returns rows written."""

    buildings = session.exec(select(Building).order_by(Building.id)).all()
    if not buildings:
        return 0
    sources = [latlng_to_lonlat((b.lat, b.lng)) for b in buildings]
    durations = await client.matrix(
        request.profile,
        sources=sources,
        destination=request.destination_lonlat,
    )
    if len(durations) != len(buildings):
        raise RuntimeError(
            f"ORS returned {len(durations)} durations for {len(buildings)} buildings"
        )

    session.exec(
        delete(TravelTime).where(
            TravelTime.mode == request.mode,
            TravelTime.destination == request.destination_label,
        )
    )

    written = 0
    for building, seconds in zip(buildings, durations, strict=True):
        minutes = _seconds_to_minutes(seconds)
        if minutes is None or building.id is None:
            continue
        session.add(
            TravelTime(
                building_id=building.id,
                mode=request.mode,
                destination=request.destination_label,
                minutes=minutes,
                source="ors",
            )
        )
        written += 1
    return written


async def refresh_travel_times(client: ORSClient | None = None) -> dict[str, int]:
    """Compute walk/drive times for every building and write to the DB.

    Returns ``{"walk": N, "drive": M}`` for the rows written per mode.
    If ``client`` is not provided, one is built from ``settings.ors_api_key``.
    """

    settings = get_settings()
    own_client = client is None
    if own_client:
        if not settings.ors_api_key:
            raise RuntimeError("ORS_API_KEY not configured")
        client = ORSClient(settings.ors_api_key)
    assert client is not None

    try:
        with Session(get_engine()) as session:
            walk_rows = await _refresh_one(session, client, WALK_REQUEST)
            drive_rows = await _refresh_one(session, client, DRIVE_REQUEST)
            session.commit()
    finally:
        if own_client:
            await client.aclose()

    return {"walk": walk_rows, "drive": drive_rows}

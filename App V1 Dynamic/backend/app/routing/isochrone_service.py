"""Populate :class:`Isochrone` rows from OpenRouteService isochrone calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, delete

from app.config import get_settings
from app.db import get_engine
from app.models import Isochrone
from app.routing.anchors import (
    ALEWIFE_T_LATLNG,
    DRIVE_BUCKETS_MIN,
    RT2_RAMP_LATLNG,
    WALK_BUCKETS_MIN,
    latlng_to_lonlat,
)
from app.routing.ors_client import ORSClient


@dataclass(frozen=True, slots=True)
class IsochroneRequest:
    """Description of a single isochrones call."""

    mode: str
    anchor_label: str
    profile: str
    anchor_lonlat: tuple[float, float]
    buckets_min: tuple[int, ...]


WALK_ISOCHRONE_REQUEST = IsochroneRequest(
    mode="walk",
    anchor_label="alewife_t",
    profile="foot-walking",
    anchor_lonlat=latlng_to_lonlat(ALEWIFE_T_LATLNG),
    buckets_min=WALK_BUCKETS_MIN,
)
DRIVE_ISOCHRONE_REQUEST = IsochroneRequest(
    mode="drive",
    anchor_label="rt2_ramp",
    profile="driving-car",
    anchor_lonlat=latlng_to_lonlat(RT2_RAMP_LATLNG),
    buckets_min=DRIVE_BUCKETS_MIN,
)


def _match_bucket(feature: dict[str, Any], buckets_min: tuple[int, ...]) -> int | None:
    """Return the nearest integer-minute bucket matching a feature's range.

    ORS puts the bucket value (in seconds) into ``properties.value``.
    """

    properties = feature.get("properties", {})
    value_seconds = properties.get("value")
    if value_seconds is None:
        return None
    value_min = round(value_seconds / 60.0)
    for bucket in buckets_min:
        if bucket == value_min:
            return bucket
    return None


async def _refresh_one(session: Session, client: ORSClient, request: IsochroneRequest) -> int:
    """Fetch and persist the isochrones for one anchor. Returns rows written."""

    range_seconds = [bucket * 60 for bucket in request.buckets_min]
    feature_collection = await client.isochrones(
        request.profile,
        anchor=request.anchor_lonlat,
        range_seconds=range_seconds,
    )

    session.exec(
        delete(Isochrone).where(
            Isochrone.mode == request.mode,
            Isochrone.anchor == request.anchor_label,
        )
    )

    features = feature_collection.get("features", [])
    written = 0
    for feature in features:
        minutes = _match_bucket(feature, request.buckets_min)
        if minutes is None:
            continue
        session.add(
            Isochrone(
                mode=request.mode,
                minutes=minutes,
                anchor=request.anchor_label,
                geojson=feature,
            )
        )
        written += 1
    return written


async def refresh_isochrones(client: ORSClient | None = None) -> dict[str, int]:
    """Rewrite both walk and drive isochrones. Returns rows written per mode."""

    settings = get_settings()
    own_client = client is None
    if own_client:
        if not settings.ors_api_key:
            raise RuntimeError("ORS_API_KEY not configured")
        client = ORSClient(settings.ors_api_key)
    assert client is not None

    try:
        with Session(get_engine()) as session:
            walk_rows = await _refresh_one(session, client, WALK_ISOCHRONE_REQUEST)
            drive_rows = await _refresh_one(session, client, DRIVE_ISOCHRONE_REQUEST)
            session.commit()
    finally:
        if own_client:
            await client.aclose()

    return {"walk": walk_rows, "drive": drive_rows}

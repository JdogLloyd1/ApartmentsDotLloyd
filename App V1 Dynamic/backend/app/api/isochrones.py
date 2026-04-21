"""Serve the latest isochrone polygons as GeoJSON features."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.cache import get_or_compute
from app.db import get_engine
from app.models import Isochrone

router = APIRouter(tags=["isochrones"])

_ISO_CACHE_KEY = "isochrones:list"


class IsochroneFeature(BaseModel):
    """Single polygon bucket as exposed to the frontend."""

    mode: str
    minutes: int
    anchor: str
    geojson: dict[str, Any]


class IsochroneResponse(BaseModel):
    """Walk and drive isochrones grouped for easy consumption."""

    walk: list[IsochroneFeature]
    drive: list[IsochroneFeature]


def _compute_isochrones() -> IsochroneResponse:
    with Session(get_engine()) as session:
        rows = session.exec(select(Isochrone).order_by(Isochrone.mode, Isochrone.minutes)).all()

    walk: list[IsochroneFeature] = []
    drive: list[IsochroneFeature] = []
    for row in rows:
        feature = IsochroneFeature(
            mode=row.mode,
            minutes=row.minutes,
            anchor=row.anchor,
            geojson=dict(row.geojson),
        )
        if row.mode == "walk":
            walk.append(feature)
        elif row.mode == "drive":
            drive.append(feature)

    return IsochroneResponse(walk=walk, drive=drive)


@router.get(
    "/isochrones",
    response_model=IsochroneResponse,
    summary="Latest walk and drive isochrones",
)
def get_isochrones(response: Response) -> IsochroneResponse:
    """Return every stored isochrone, grouped by mode and sorted small\u2192large."""

    payload, age = get_or_compute(_ISO_CACHE_KEY, _compute_isochrones)
    response.headers["X-Data-Freshness"] = str(int(age))
    return payload

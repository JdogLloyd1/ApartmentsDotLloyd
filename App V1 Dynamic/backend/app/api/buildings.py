"""HTTP endpoints for the building catalog."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import Session, select

from app.cache import get_or_compute
from app.db import get_engine
from app.models import Building
from app.schemas import (
    BuildingOut,
    _latest_price_snapshots,
    _latest_rating_snapshots,
    _travel_time_overlay,
    build_live_overlay,
    building_with_live_data,
)

router = APIRouter(tags=["buildings"])

_LIST_CACHE_KEY = "buildings:list"


def _compute_buildings_list() -> list[BuildingOut]:
    with Session(get_engine()) as session:
        buildings = session.exec(select(Building).order_by(Building.name)).all()
        travel_map = _travel_time_overlay(session)
        price_map = _latest_price_snapshots(session)
        rating_map = _latest_rating_snapshots(session)

    results: list[BuildingOut] = []
    for building in buildings:
        overlay = build_live_overlay(
            building,
            travel_map=travel_map,
            price_map=price_map,
            rating_map=rating_map,
        )
        results.append(BuildingOut.from_building(building, live=overlay))
    return results


@router.get(
    "/buildings",
    response_model=list[BuildingOut],
    summary="List all buildings",
    response_model_by_alias=True,
)
def list_buildings(response: Response) -> list[BuildingOut]:
    """Return every building, sorted alphabetically.

    Cached for ~60s; stamps ``X-Data-Freshness`` (seconds since cache
    insertion) so the frontend can render a "last refreshed" chip without
    a round-trip to a status endpoint.
    """

    payload, age = get_or_compute(_LIST_CACHE_KEY, _compute_buildings_list)
    response.headers["X-Data-Freshness"] = str(int(age))
    return payload


@router.get(
    "/buildings/{slug}",
    response_model=BuildingOut,
    summary="Get a single building by slug",
    response_model_by_alias=True,
)
def get_building(slug: str) -> BuildingOut:
    """Return a single building or ``404`` if the slug is unknown."""

    with Session(get_engine()) as session:
        building = session.exec(select(Building).where(Building.slug == slug)).first()
    if building is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown building slug: {slug}",
        )
    return building_with_live_data(building)

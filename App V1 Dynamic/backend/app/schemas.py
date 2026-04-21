"""Pydantic DTOs returned by the HTTP layer.

Decoupled from :mod:`app.models` so the DB layout can evolve without
breaking the wire format the frontend depends on.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session, select

from app.db import get_engine
from app.models import Building, PriceSnapshot, RatingSnapshot, TravelTime
from app.scoring import calc_score


class BuildingOut(BaseModel):
    """Public shape of a single building.

    Field names deliberately match the JS property names used in the
    static dashboard (``oneBR``, ``wlabel``) so the Sprint 3 frontend
    rewrite is a drop-in swap.
    """

    model_config = ConfigDict(populate_by_name=True)

    slug: str
    name: str
    nbhd: str
    address: str
    lat: float
    lng: float
    website: str | None = None
    website_label: str | None = Field(default=None, serialization_alias="wlabel")
    overview: str = ""
    amenities: list[str] = Field(default_factory=list)

    rating: float | None = None
    review_count: int | None = Field(default=None, serialization_alias="rc")
    studio: int | None = None
    one_br: int | None = Field(default=None, serialization_alias="oneBR")
    two_br: int | None = Field(default=None, serialization_alias="twoBR")
    studio_src: str | None = Field(default=None, serialization_alias="studioSrc")
    one_br_src: str | None = Field(default=None, serialization_alias="oneBRSrc")
    two_br_src: str | None = Field(default=None, serialization_alias="twoBRSrc")

    walk: int | None = None
    drive: int | None = None
    score: int

    prices_fetched_at: datetime | None = Field(default=None, serialization_alias="pricesFetchedAt")
    rating_fetched_at: datetime | None = Field(default=None, serialization_alias="ratingFetchedAt")

    @classmethod
    def from_building(
        cls,
        building: Building,
        *,
        live: dict[str, Any] | None = None,
    ) -> BuildingOut:
        """Build a response DTO from a persisted :class:`Building`.

        ``live`` is an optional overlay dict supplied by the router. It
        may carry any of these keys, each of which takes precedence over
        the seed fallback stored on the :class:`Building` row:

        - ``rating``, ``review_count``, ``rating_fetched_at``
        - ``walk``, ``drive``
        - ``studio``, ``one_br``, ``two_br``
        - ``studio_src``, ``one_br_src``, ``two_br_src``
        - ``prices_fetched_at``
        """

        live = live or {}

        rating = live.get("rating", building.seed_rating)
        review_count = live.get("review_count", building.seed_review_count)
        walk = live.get("walk", building.seed_walk_min)
        drive = live.get("drive", building.seed_drive_min)
        studio = live.get("studio", building.seed_studio)
        one_br = live.get("one_br", building.seed_one_br)
        two_br = live.get("two_br", building.seed_two_br)
        studio_src = live.get("studio_src", building.seed_studio_src)
        one_br_src = live.get("one_br_src", building.seed_one_br_src)
        two_br_src = live.get("two_br_src", building.seed_two_br_src)

        score = calc_score(
            rating=rating,
            walk_min=walk,
            drive_min=drive,
            one_br=one_br,
        )

        return cls(
            slug=building.slug,
            name=building.name,
            nbhd=building.nbhd,
            address=building.address,
            lat=building.lat,
            lng=building.lng,
            website=building.website,
            website_label=building.website_label,
            overview=building.overview,
            amenities=list(building.amenities),
            rating=rating,
            review_count=review_count,
            studio=studio,
            one_br=one_br,
            two_br=two_br,
            studio_src=studio_src,
            one_br_src=one_br_src,
            two_br_src=two_br_src,
            walk=walk,
            drive=drive,
            score=score,
            prices_fetched_at=live.get("prices_fetched_at"),
            rating_fetched_at=live.get("rating_fetched_at"),
        )


def _travel_time_overlay(session: Session) -> dict[tuple[int, str, str], float]:
    """``(building_id, mode, destination) \u2192 minutes`` for all rows."""

    rows = session.exec(select(TravelTime)).all()
    latest: dict[tuple[int, str, str], float] = {}
    for row in rows:
        key = (row.building_id, row.mode, row.destination)
        latest[key] = row.minutes
    return latest


def _latest_price_snapshots(session: Session) -> dict[int, PriceSnapshot]:
    """Newest :class:`PriceSnapshot` per building."""

    rows = session.exec(select(PriceSnapshot)).all()
    latest: dict[int, PriceSnapshot] = {}
    for row in rows:
        current = latest.get(row.building_id)
        if current is None or row.fetched_at > current.fetched_at:
            latest[row.building_id] = row
    return latest


def _latest_rating_snapshots(session: Session) -> dict[int, RatingSnapshot]:
    """Newest :class:`RatingSnapshot` per building."""

    rows = session.exec(select(RatingSnapshot)).all()
    latest: dict[int, RatingSnapshot] = {}
    for row in rows:
        current = latest.get(row.building_id)
        if current is None or row.fetched_at > current.fetched_at:
            latest[row.building_id] = row
    return latest


def build_live_overlay(
    building: Building,
    *,
    travel_map: dict[tuple[int, str, str], float],
    price_map: dict[int, PriceSnapshot],
    rating_map: dict[int, RatingSnapshot],
) -> dict[str, Any]:
    """Collapse the joined tables into the overlay dict used by BuildingOut."""

    overlay: dict[str, Any] = {}
    if building.id is None:
        return overlay

    walk_seconds = travel_map.get((building.id, "walk", "alewife_t"))
    drive_seconds = travel_map.get((building.id, "drive", "rt2_ramp"))
    if walk_seconds is not None:
        overlay["walk"] = round(walk_seconds)
    if drive_seconds is not None:
        overlay["drive"] = round(drive_seconds)

    price = price_map.get(building.id)
    if price is not None:
        if price.studio is not None:
            overlay["studio"] = price.studio
        if price.one_br is not None:
            overlay["one_br"] = price.one_br
        if price.two_br is not None:
            overlay["two_br"] = price.two_br
        if price.studio_src is not None:
            overlay["studio_src"] = price.studio_src
        if price.one_br_src is not None:
            overlay["one_br_src"] = price.one_br_src
        if price.two_br_src is not None:
            overlay["two_br_src"] = price.two_br_src
        overlay["prices_fetched_at"] = price.fetched_at

    rating = rating_map.get(building.id)
    if rating is not None:
        if rating.rating is not None:
            overlay["rating"] = rating.rating
        if rating.review_count is not None:
            overlay["review_count"] = rating.review_count
        overlay["rating_fetched_at"] = rating.fetched_at

    return overlay


def building_with_live_data(building: Building) -> BuildingOut:
    """Load all live overlays for a single building and return the DTO."""

    if building.id is None:
        return BuildingOut.from_building(building)

    with Session(get_engine()) as session:
        travel_map = _travel_time_overlay(session)
        price_map = _latest_price_snapshots(session)
        rating_map = _latest_rating_snapshots(session)

    overlay = build_live_overlay(
        building, travel_map=travel_map, price_map=price_map, rating_map=rating_map
    )
    return BuildingOut.from_building(building, live=overlay)

"""SQLModel tables for the Alewife backend.

Sprint 1 ships only the :class:`Building` catalog; later sprints add
``PriceSnapshot``, ``RatingSnapshot``, ``TravelTime``, ``Isochrone``, and
``RefreshRun``. Putting all tables in a single module keeps relationships
obvious and keeps the migration surface minimal for a SQLite-first app.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import JSON, Column, Field, SQLModel


def _utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp.

    Wrapped for easy patching in tests and to avoid the deprecated
    ``datetime.utcnow``.
    """

    return datetime.now(UTC)


class Building(SQLModel, table=True):
    """A single apartment complex in the search universe.

    ``slug`` is the stable public identifier; ``name`` and ``address`` are
    the human-readable labels. Live data (prices, ratings, travel times)
    is stored in snapshot tables that reference this one.
    """

    __tablename__ = "building"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, description="URL-friendly identifier")
    name: str
    nbhd: str = Field(description="Neighborhood label shown in the UI")
    address: str
    lat: float
    lng: float
    website: str | None = None
    website_label: str | None = Field(default=None, alias="wlabel")
    overview: str = ""
    amenities: list[str] = Field(default_factory=list, sa_column=Column(JSON))

    seed_rating: float | None = Field(
        default=None,
        description="Rating baked into the seed JSON; used as a fallback "
        "until a RatingSnapshot exists.",
    )
    seed_review_count: int | None = Field(default=None)
    seed_studio: int | None = Field(default=None)
    seed_one_br: int | None = Field(default=None)
    seed_two_br: int | None = Field(default=None)
    seed_studio_src: str | None = Field(default=None)
    seed_one_br_src: str | None = Field(default=None)
    seed_two_br_src: str | None = Field(default=None)
    seed_walk_min: int | None = Field(default=None)
    seed_drive_min: int | None = Field(default=None)

    apartments_com_url: str | None = Field(
        default=None,
        description="Source URL for the apartments.com scraper. Null means "
        "the scraper skips this building.",
    )
    google_place_id: str | None = Field(
        default=None,
        description="Google Maps place_id for the ratings scraper. Null "
        "means the scraper skips this building.",
    )

    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class TravelTime(SQLModel, table=True):
    """Computed travel time from a building to a destination anchor.

    One row per (building, mode, destination) pair is kept as the current
    value; history can be reconstructed by timestamp if needed. Updated
    atomically by :func:`app.routing.travel_time_service.refresh_travel_times`.
    """

    __tablename__ = "travel_time"

    id: int | None = Field(default=None, primary_key=True)
    building_id: int = Field(foreign_key="building.id", index=True)
    mode: str = Field(index=True, description='"walk" or "drive"')
    destination: str = Field(index=True, description='"alewife_t" or "rt2_ramp"')
    minutes: float
    source: str = Field(default="ors", description='"ors" or "seed"')
    computed_at: datetime = Field(default_factory=_utc_now)


class Isochrone(SQLModel, table=True):
    """A single reachability polygon from a fixed anchor point.

    Stored as a GeoJSON geometry so the frontend can hand it straight to
    ``L.geoJSON``. Rows are replaced wholesale on each refresh.
    """

    __tablename__ = "isochrone"

    id: int | None = Field(default=None, primary_key=True)
    mode: str = Field(index=True, description='"walk" or "drive"')
    minutes: int = Field(description="Travel-time bucket (5, 10, 15 for walk; 2, 5, 10 for drive)")
    anchor: str = Field(index=True, description='"alewife_t" or "rt2_ramp"')
    geojson: dict = Field(sa_column=Column(JSON))
    computed_at: datetime = Field(default_factory=_utc_now)


class PriceSnapshot(SQLModel, table=True):
    """Scraped rent values for a single building at a single point in time.

    One row per scrape; callers pick the newest row for presentation.
    ``*_src`` columns keep the human-facing label (e.g. ``"from $2,932"``)
    so the dashboard can display the original phrasing.
    """

    __tablename__ = "price_snapshot"

    id: int | None = Field(default=None, primary_key=True)
    building_id: int = Field(foreign_key="building.id", index=True)

    studio: int | None = Field(default=None, description="Minimum studio rent in USD")
    one_br: int | None = Field(default=None, description="Minimum 1BR rent in USD")
    two_br: int | None = Field(default=None, description="Minimum 2BR rent in USD")
    studio_src: str | None = Field(default=None)
    one_br_src: str | None = Field(default=None)
    two_br_src: str | None = Field(default=None)

    source_url: str | None = Field(default=None)
    source: str = Field(default="apartments_com")
    fetched_at: datetime = Field(default_factory=_utc_now, index=True)


class RatingSnapshot(SQLModel, table=True):
    """Scraped Google rating + review count for a single building."""

    __tablename__ = "rating_snapshot"

    id: int | None = Field(default=None, primary_key=True)
    building_id: int = Field(foreign_key="building.id", index=True)

    rating: float | None = Field(default=None)
    review_count: int | None = Field(default=None)

    source_url: str | None = Field(default=None)
    source: str = Field(default="google_places")
    fetched_at: datetime = Field(default_factory=_utc_now, index=True)


class RefreshRun(SQLModel, table=True):
    """Audit row for a full refresh execution (Sprint 6 uses this table)."""

    __tablename__ = "refresh_run"

    id: int | None = Field(default=None, primary_key=True)
    trigger: str = Field(description='"manual", "scheduled", or "bootstrap"')
    status: str = Field(default="running", description='"running", "succeeded", or "failed"')
    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime | None = Field(default=None)
    detail: dict = Field(default_factory=dict, sa_column=Column(JSON))

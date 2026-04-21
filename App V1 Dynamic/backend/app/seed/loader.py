"""Idempotent seed loader for the :class:`Building` catalog.

Reads the JSON file produced by :mod:`scripts.extract_seed` and upserts
each building by ``slug``. Safe to run repeatedly; re-runs only update
mutable catalog fields (address, amenities, coordinates, etc.) and leave
snapshot history untouched.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from app.config import BACKEND_DIR
from app.db import get_engine, init_db
from app.models import Building, _utc_now

DEFAULT_SEED_FILE = BACKEND_DIR / "app" / "seed" / "buildings_seed.json"
DEFAULT_SCRAPE_TARGETS_FILE = BACKEND_DIR / "app" / "seed" / "scrape_targets.json"


def _load_scrape_targets(path: Path) -> dict[str, dict[str, Any]]:
    """Load ``scrape_targets.json`` into a ``slug \u2192 overrides`` dict.

    Missing or malformed file returns an empty dict so the loader can
    still run against just the base seed.
    """

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    buildings = payload.get("buildings") if isinstance(payload, dict) else None
    if not isinstance(buildings, dict):
        return {}
    return {
        slug: {k: v for k, v in entry.items() if v is not None}
        for slug, entry in buildings.items()
        if isinstance(entry, dict)
    }


def _coerce_int(value: Any) -> int | None:
    """Safely coerce a JSON value into ``int | None``."""

    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _building_from_seed(entry: dict[str, Any]) -> Building:
    """Build a :class:`Building` from a raw seed dict.

    Maps the JS-ish field names (``oneBR``, ``wlabel``) onto the typed
    SQLModel columns.
    """

    amenities = entry.get("amenities") or []
    if not isinstance(amenities, list):
        raise ValueError(f"Expected list for amenities, got {type(amenities).__name__}")

    return Building(
        slug=str(entry["slug"]),
        name=str(entry["name"]),
        nbhd=str(entry.get("nbhd", "")),
        address=str(entry.get("address", "")),
        lat=float(entry["lat"]),
        lng=float(entry["lng"]),
        website=_coerce_str(entry.get("website")),
        website_label=_coerce_str(entry.get("wlabel")),
        overview=str(entry.get("overview", "")),
        amenities=[str(item) for item in amenities],
        seed_rating=entry.get("rating"),
        seed_review_count=_coerce_int(entry.get("rc")),
        seed_studio=_coerce_int(entry.get("studio")),
        seed_one_br=_coerce_int(entry.get("oneBR")),
        seed_two_br=_coerce_int(entry.get("twoBR")),
        seed_studio_src=_coerce_str(entry.get("studioSrc")),
        seed_one_br_src=_coerce_str(entry.get("oneBRSrc")),
        seed_two_br_src=_coerce_str(entry.get("twoBRSrc")),
        seed_walk_min=_coerce_int(entry.get("walk")),
        seed_drive_min=_coerce_int(entry.get("drive")),
        apartments_com_url=_coerce_str(entry.get("apartments_com_url")),
        google_place_id=_coerce_str(entry.get("google_place_id")),
    )


def _update_from_seed(existing: Building, seed: Building) -> bool:
    """Copy mutable fields from ``seed`` onto ``existing``.

    Returns ``True`` if any field changed so callers can skip commits
    when nothing moved.
    """

    tracked_fields = (
        "name",
        "nbhd",
        "address",
        "lat",
        "lng",
        "website",
        "website_label",
        "overview",
        "amenities",
        "seed_rating",
        "seed_review_count",
        "seed_studio",
        "seed_one_br",
        "seed_two_br",
        "seed_studio_src",
        "seed_one_br_src",
        "seed_two_br_src",
        "seed_walk_min",
        "seed_drive_min",
        "apartments_com_url",
        "google_place_id",
    )
    dirty = False
    for field in tracked_fields:
        new_value = getattr(seed, field)
        if getattr(existing, field) != new_value:
            setattr(existing, field, new_value)
            dirty = True
    if dirty:
        existing.updated_at = _utc_now()
    return dirty


def load_buildings(
    seed_path: Path = DEFAULT_SEED_FILE,
    scrape_targets_path: Path = DEFAULT_SCRAPE_TARGETS_FILE,
) -> tuple[int, int]:
    """Load the seed JSON into the DB, upserting by ``slug``.

    Returns ``(inserted, updated)`` counts. Does not delete buildings that
    have disappeared from the seed; removal is always a deliberate manual
    operation. ``scrape_targets_path`` is an optional sidecar that
    supplies ``apartments_com_url`` and ``google_place_id`` without
    requiring edits to the auto-generated seed JSON.
    """

    entries = json.loads(seed_path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("Seed file must contain a JSON array")
    targets = _load_scrape_targets(scrape_targets_path)

    init_db()
    inserted = 0
    updated = 0
    with Session(get_engine()) as session:
        for entry in entries:
            merged = {**entry, **targets.get(str(entry.get("slug", "")), {})}
            staged = _building_from_seed(merged)
            existing = session.exec(select(Building).where(Building.slug == staged.slug)).first()
            if existing is None:
                session.add(staged)
                inserted += 1
            elif _update_from_seed(existing, staged):
                session.add(existing)
                updated += 1
        session.commit()
    return inserted, updated


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED_FILE)
    parser.add_argument(
        "--scrape-targets-file",
        type=Path,
        default=DEFAULT_SCRAPE_TARGETS_FILE,
        help="Optional sidecar supplying apartments.com URLs and Google place_ids.",
    )
    return parser


def main() -> None:
    """Entry point for ``python -m app.seed.loader``."""

    args = _build_arg_parser().parse_args()
    inserted, updated = load_buildings(args.seed_file, args.scrape_targets_file)
    print(f"Seed load complete: inserted={inserted} updated={updated}")


if __name__ == "__main__":
    main()

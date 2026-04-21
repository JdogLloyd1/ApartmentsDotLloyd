"""Seed loader correctly merges the ``scrape_targets.json`` sidecar."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from app.config import get_settings
from app.db import configure_engine, get_engine, reset_engine
from app.models import Building
from app.seed.loader import load_buildings


@pytest.fixture
def tmp_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    seed = [
        {
            "slug": "alpha",
            "name": "Alpha",
            "nbhd": "Cambridge",
            "address": "1 Main",
            "lat": 42.39,
            "lng": -71.14,
            "amenities": [],
        },
        {
            "slug": "bravo",
            "name": "Bravo",
            "nbhd": "Cambridge",
            "address": "2 Main",
            "lat": 42.40,
            "lng": -71.15,
            "amenities": [],
        },
    ]
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    get_settings.cache_clear()
    reset_engine()
    configure_engine(f"sqlite:///{db_path}")
    return seed_path


def test_sidecar_populates_scrape_targets(tmp_seed: Path, tmp_path: Path) -> None:
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            {
                "buildings": {
                    "alpha": {
                        "apartments_com_url": "https://example.com/alpha",
                        "google_place_id": "ChIJAlpha",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    load_buildings(tmp_seed, targets_path)
    with Session(get_engine()) as session:
        alpha = session.exec(select(Building).where(Building.slug == "alpha")).one()
        bravo = session.exec(select(Building).where(Building.slug == "bravo")).one()

    assert alpha.apartments_com_url == "https://example.com/alpha"
    assert alpha.google_place_id == "ChIJAlpha"
    assert bravo.apartments_com_url is None
    assert bravo.google_place_id is None


def test_sidecar_missing_file_is_safe(tmp_seed: Path, tmp_path: Path) -> None:
    load_buildings(tmp_seed, tmp_path / "does-not-exist.json")
    with Session(get_engine()) as session:
        count = len(session.exec(select(Building)).all())
    assert count == 2


def test_sidecar_null_values_dont_override_seed(tmp_seed: Path, tmp_path: Path) -> None:
    targets_path = tmp_path / "targets.json"
    targets_path.write_text(
        json.dumps(
            {
                "buildings": {
                    "alpha": {
                        "apartments_com_url": None,
                        "google_place_id": None,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    load_buildings(tmp_seed, targets_path)
    with Session(get_engine()) as session:
        alpha = session.exec(select(Building).where(Building.slug == "alpha")).one()
    assert alpha.apartments_com_url is None
    assert alpha.google_place_id is None

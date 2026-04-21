"""Tests for the static-dashboard to JSON seed extractor."""

from __future__ import annotations

from pathlib import Path

from scripts.extract_seed import (
    DEFAULT_SOURCE,
    enrich_with_slug,
    parse_apts,
)


def test_parses_all_buildings_from_static_source() -> None:
    """Every apartment object in the HTML becomes a dict with the expected keys."""

    html = DEFAULT_SOURCE.read_text(encoding="utf-8")
    buildings = parse_apts(html)

    assert len(buildings) == 19
    required = {"name", "address", "lat", "lng", "rating", "amenities", "walk", "drive"}
    for entry in buildings:
        missing = required - entry.keys()
        assert not missing, f"{entry.get('name')} missing {missing}"


def test_slug_is_stable_and_unique() -> None:
    """Every slug is kebab-case and collisions never occur."""

    html = DEFAULT_SOURCE.read_text(encoding="utf-8")
    enriched = enrich_with_slug(parse_apts(html))

    slugs = {entry["slug"] for entry in enriched}
    assert len(slugs) == len(enriched)
    assert "hanover-alewife" in slugs
    assert "cambridge-park" in slugs
    assert "arlington-360" in slugs


def test_seed_file_matches_source(tmp_path: Path) -> None:
    """Running the extractor against the real source produces consistent output."""

    output = tmp_path / "buildings_seed.json"
    from scripts.extract_seed import extract

    count = extract(DEFAULT_SOURCE, output)

    assert count == 19
    assert output.exists()
    assert output.stat().st_size > 0

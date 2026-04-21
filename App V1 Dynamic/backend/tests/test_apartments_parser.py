"""Fixture-driven tests for :mod:`app.scrapers.apartments_com`."""

from __future__ import annotations

from pathlib import Path

from app.scrapers.apartments_com import ApartmentsListing, parse_apartments_html

FIXTURES = Path(__file__).parent / "fixtures" / "scrapers"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_json_ld_supplies_all_three_rents() -> None:
    result = parse_apartments_html(_load("apartments_with_json_ld.html"))
    assert result.studio == 2430
    assert result.one_br == 3275
    assert result.two_br == 4200
    assert result.studio_src == "from $2,430"
    assert result.one_br_src == "from $3,275"
    assert result.two_br_src == "from $4,200"


def test_floor_plan_grid_picks_the_lowest_rent_per_bed_count() -> None:
    result = parse_apartments_html(_load("apartments_with_grid.html"))
    assert result.studio == 2560
    assert result.one_br == 3050
    assert result.two_br == 4400
    assert result.one_br_src == "from $3,050"


def test_price_summary_fallback_when_no_structured_data() -> None:
    result = parse_apartments_html(_load("apartments_summary_only.html"))
    assert result.studio == 2725
    assert result.one_br == 3350
    assert result.two_br == 4600


def test_empty_html_returns_all_none() -> None:
    result = parse_apartments_html("")
    assert result == ApartmentsListing()


def test_unavailable_page_returns_all_none() -> None:
    result = parse_apartments_html(_load("apartments_no_data.html"))
    assert result == ApartmentsListing()


def test_parser_is_tolerant_of_malformed_json_ld() -> None:
    html = """<html><head>
    <script type=\"application/ld+json\">{not valid json</script>
    </head><body><div class=\"pricingGridItem\" data-beds=\"1\" data-minrent=\"2100\"></div>
    </body></html>"""
    result = parse_apartments_html(html)
    assert result.one_br == 2100

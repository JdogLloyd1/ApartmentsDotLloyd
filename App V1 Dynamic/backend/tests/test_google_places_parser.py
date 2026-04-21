"""Fixture-driven tests for :mod:`app.scrapers.google_places`."""

from __future__ import annotations

from pathlib import Path

from app.scrapers.google_places import GooglePlaceData, parse_google_html

FIXTURES = Path(__file__).parent / "fixtures" / "scrapers"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_aria_label_populates_rating_and_review_count() -> None:
    result = parse_google_html(_load("google_aria_rating.html"))
    assert result.rating == 4.8
    assert result.review_count == 247


def test_json_ld_populates_rating_and_review_count() -> None:
    result = parse_google_html(_load("google_json_rating.html"))
    assert result.rating == 4.5
    assert result.review_count == 259


def test_missing_data_returns_none_fields() -> None:
    result = parse_google_html(_load("google_none.html"))
    assert result == GooglePlaceData()


def test_empty_html_is_safe() -> None:
    assert parse_google_html("") == GooglePlaceData()


def test_out_of_range_rating_rejected() -> None:
    html = '<div aria-label="Rated 9.5 stars out of 5 (120 reviews)"></div>'
    result = parse_google_html(html)
    assert result.rating is None

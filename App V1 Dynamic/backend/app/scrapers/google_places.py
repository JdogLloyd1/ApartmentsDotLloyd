"""Parse a Google Maps place-page HTML into a :class:`GooglePlaceData`.

We intentionally support two strategies:

1. **Embedded JSON** \u2014 the rendered Maps page ships a giant
   ``window.APP_INITIALIZATION_STATE`` array; rating + review count are
   retrievable via regex-friendly substrings.
2. **Knowledge-panel fallback** \u2014 a Google search result page (from
   ``google.com/search?q=<name>+<address>``) renders the rating inside
   ``<div aria-label="...">`` attributes; the regexes below match both
   the English and universal Unicode star-character forms.

Both strategies are tolerant of missing fields; the parser returns
``None`` where unknown rather than raising.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

STAR_RATING_RE = re.compile(r"Rated\s+(\d+(?:\.\d+)?)\s+out of", re.IGNORECASE)
AVG_RATING_RE = re.compile(r"(\d\.\d)\s*(?:\u2605|stars?)\s*\(?\s*([\d,]+)\s*\)?", re.IGNORECASE)
REVIEW_COUNT_RE = re.compile(r"([\d,]+)\s*review", re.IGNORECASE)
ARIA_RATING_RE = re.compile(
    r'aria-label="([^"]*?(\d\.\d)\s*stars?[^"]*?([\d,]+)\s*review[^"]*)"',
    re.IGNORECASE,
)
JSON_RATING_RE = re.compile(r'"ratingValue"\s*:\s*"?(\d\.\d)"?')
JSON_REVIEW_RE = re.compile(r'"reviewCount"\s*:\s*"?([\d,]+)"?')


@dataclass(slots=True)
class GooglePlaceData:
    """Rating and review count scraped from Google."""

    rating: float | None = None
    review_count: int | None = None


def _parse_review_count(raw: str) -> int | None:
    try:
        return int(raw.replace(",", ""))
    except (TypeError, ValueError):
        return None


def _parse_rating(raw: str) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if 0.0 <= value <= 5.0:
        return round(value, 1)
    return None


def parse_google_html(html: str) -> GooglePlaceData:
    """Extract rating + review count from either a Maps or Search page.

    Never raises; returns a dataclass with ``None`` fields when data is
    missing.
    """

    data = GooglePlaceData()
    if not html:
        return data

    aria_match = ARIA_RATING_RE.search(html)
    if aria_match:
        data.rating = _parse_rating(aria_match.group(2))
        data.review_count = _parse_review_count(aria_match.group(3))
        if data.rating is not None and data.review_count is not None:
            return data

    if data.rating is None:
        json_match = JSON_RATING_RE.search(html)
        if json_match:
            data.rating = _parse_rating(json_match.group(1))
    if data.review_count is None:
        json_match = JSON_REVIEW_RE.search(html)
        if json_match:
            data.review_count = _parse_review_count(json_match.group(1))

    if data.rating is None:
        star_match = STAR_RATING_RE.search(html)
        if star_match:
            data.rating = _parse_rating(star_match.group(1))

    if data.rating is None:
        combined = AVG_RATING_RE.search(html)
        if combined:
            data.rating = _parse_rating(combined.group(1))
            if data.review_count is None:
                data.review_count = _parse_review_count(combined.group(2))

    if data.review_count is None:
        rc_match = REVIEW_COUNT_RE.search(html)
        if rc_match:
            data.review_count = _parse_review_count(rc_match.group(1))

    return data

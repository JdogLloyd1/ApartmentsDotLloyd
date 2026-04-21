"""Parse apartments.com listing HTML into a :class:`ApartmentsListing`.

Strategy, in priority order:

1. ``<script type="application/ld+json">`` blocks typed as
   ``ApartmentComplex`` or ``RealEstateListing`` \u2014 authoritative
   structured data where available.
2. Floor-plan cards: ``<div class="pricingGridItem">`` with
   ``data-beds`` + ``data-maxrent``/``data-minrent`` attributes.
3. Fallback regex over the entire HTML for the first integer dollar
   amount per bedroom count (least reliable; used only when structured
   data is missing).

The parser is deliberately tolerant: missing fields become ``None``
rather than raising. Callers are responsible for deciding what to
persist.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from selectolax.parser import HTMLParser

PRICE_PATTERN = re.compile(r"\$?([\d,]{3,})")


@dataclass(slots=True)
class ApartmentsListing:
    """Structured rent data extracted from a single apartments.com page."""

    studio: int | None = None
    one_br: int | None = None
    two_br: int | None = None
    studio_src: str | None = None
    one_br_src: str | None = None
    two_br_src: str | None = None


def _parse_price(raw: str | None) -> int | None:
    """Turn a price string like ``"$2,430"`` or ``"2560"`` into ``2430``.

    Requires at least 3 digits to avoid matching bedroom counts or other
    incidental numbers on the page.
    """

    if not raw:
        return None
    match = PRICE_PATTERN.search(str(raw))
    if not match:
        return None
    try:
        value = int(match.group(1).replace(",", ""))
    except ValueError:
        return None
    if value < 500:
        return None
    return value


def _iter_json_ld(tree: HTMLParser) -> list[dict[str, Any]]:
    """Return every parseable JSON-LD object on the page."""

    results: list[dict[str, Any]] = []
    for node in tree.css('script[type="application/ld+json"]'):
        raw = node.text(strip=False)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            results.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            results.append(data)
    return results


def _apartment_ld_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return just the blocks that describe apartment complexes or listings."""

    accepted = {"ApartmentComplex", "RealEstateListing", "Apartment"}
    return [
        block
        for block in blocks
        if isinstance(block.get("@type"), str) and block["@type"] in accepted
    ]


def _bed_count_to_field(bed_count: int) -> str | None:
    """Map a numeric bed count to the :class:`ApartmentsListing` field."""

    if bed_count == 0:
        return "studio"
    if bed_count == 1:
        return "one_br"
    if bed_count == 2:
        return "two_br"
    return None


def _extract_from_ld(listing: ApartmentsListing, blocks: list[dict[str, Any]]) -> ApartmentsListing:
    """Fill in rents from any ``ApartmentComplex`` ``offers`` array.

    We look for per-bed offers first, then fall back to ``priceRange``
    to at least populate a min on every field.
    """

    for block in blocks:
        offers = block.get("offers")
        if isinstance(offers, dict):
            offer_list = [offers]
        elif isinstance(offers, list):
            offer_list = [item for item in offers if isinstance(item, dict)]
        else:
            offer_list = []
        for offer in offer_list:
            beds: Any = offer.get("numberOfRooms")
            if beds is None:
                beds = offer.get("numberOfBedrooms")
            if isinstance(beds, dict):
                beds = beds.get("value")
            if isinstance(beds, str) and beds.isdigit():
                beds = int(beds)
            if not isinstance(beds, int) or isinstance(beds, bool):
                continue
            field = _bed_count_to_field(beds)
            if field is None:
                continue
            price = _parse_price(str(offer.get("price") or offer.get("priceRange") or ""))
            src = offer.get("priceRange") or offer.get("priceSpecification")
            if price is not None and getattr(listing, field) is None:
                setattr(listing, field, price)
            if isinstance(src, str) and getattr(listing, f"{field}_src") is None:
                setattr(listing, f"{field}_src", src)
    return listing


def _extract_from_floor_plans(listing: ApartmentsListing, tree: HTMLParser) -> ApartmentsListing:
    """Read the floor-plan grid items.

    Most apartments.com pages emit ``<div class="pricingGridItem">`` per
    floor plan, with ``data-beds`` + ``data-maxrent``/``data-minrent``.
    """

    best: dict[str, tuple[int, str]] = {}
    for card in tree.css("div.pricingGridItem, tr.rentalGridRow, li.floorplanListItem"):
        beds_raw = card.attributes.get("data-beds") or card.attributes.get("data-bed")
        if not beds_raw:
            beds_text = card.css_first(".floorplanNumBeds")
            if beds_text is not None:
                beds_raw = beds_text.text(strip=True)
        try:
            beds = int(str(beds_raw).strip().split()[0]) if beds_raw is not None else None
        except (TypeError, ValueError):
            beds = None
        if beds is None:
            continue
        field = _bed_count_to_field(beds)
        if field is None:
            continue
        rent_raw = (
            card.attributes.get("data-minrent")
            or card.attributes.get("data-maxrent")
            or card.attributes.get("data-rentlow")
            or card.attributes.get("data-rent")
        )
        if rent_raw is None:
            rent_node = card.css_first(".rentInfoDetail, .pricingInfoDetail, .floorplanRent")
            if rent_node is not None:
                rent_raw = rent_node.text(strip=True)
        rent = _parse_price(str(rent_raw) if rent_raw is not None else None)
        if rent is None:
            continue
        if field not in best or rent < best[field][0]:
            best[field] = (rent, f"from ${rent:,}")
    for field, (rent, label) in best.items():
        if getattr(listing, field) is None:
            setattr(listing, field, rent)
        if getattr(listing, f"{field}_src") is None:
            setattr(listing, f"{field}_src", label)
    return listing


def _extract_from_price_summary(listing: ApartmentsListing, tree: HTMLParser) -> ApartmentsListing:
    """Parse the ``"Studio \u2013 $2,430+"`` summary blocks as a last resort."""

    rows = tree.css(".priceBedRangeInfo .column, .priceGrid li, .pricingContainer .priceInfo li")
    bed_words = {
        "studio": "studio",
        "1 bed": "one_br",
        "1bed": "one_br",
        "2 bed": "two_br",
        "2bed": "two_br",
    }
    for row in rows:
        text = row.text(strip=True).lower()
        field = next((f for kw, f in bed_words.items() if kw in text), None)
        if field is None:
            continue
        price = _parse_price(text)
        if price is None:
            continue
        if getattr(listing, field) is None:
            setattr(listing, field, price)
        if getattr(listing, f"{field}_src") is None:
            setattr(listing, f"{field}_src", f"from ${price:,}")
    return listing


def parse_apartments_html(html: str) -> ApartmentsListing:
    """Return a best-effort :class:`ApartmentsListing` for a page.

    Never raises; missing values come back as ``None`` on the dataclass.
    Empty or unparseable HTML returns an all-``None`` listing.
    """

    listing = ApartmentsListing()
    if not html:
        return listing
    tree = HTMLParser(html)
    blocks = _apartment_ld_blocks(_iter_json_ld(tree))
    listing = _extract_from_ld(listing, blocks)
    listing = _extract_from_floor_plans(listing, tree)
    listing = _extract_from_price_summary(listing, tree)
    return listing

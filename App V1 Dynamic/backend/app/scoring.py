"""Composite building-score calculator.

Ported from the static dashboard's ``calcScore`` (lines 294\u2013302 of
``alewife_dashboard_v2.html``). Weights match the note printed in the
dashboard footer:

- Google rating    : 25%
- Walk-to-T time   : 25%
- Drive-to-Rt.2    : 20%
- One-bedroom rent : 30%

The static version had a dead-code bug where ``dScore`` was computed
against an undefined ``driveMin`` and then ignored in favor of an
inline expression on ``drive``. This port uses the correct variable
(``drive_min``) throughout.
"""

from __future__ import annotations

RATING_WEIGHT = 25.0
WALK_WEIGHT = 25.0
DRIVE_WEIGHT = 20.0
COST_WEIGHT = 30.0

MAX_RATING = 5.0
MAX_WALK_MINUTES = 30.0
MAX_DRIVE_MINUTES = 10.0
MIN_DRIVE_MINUTES = 1.0

CHEAP_RENT_FLOOR = 1800
EXPENSIVE_RENT_CAP = 3500
RENT_RANGE = EXPENSIVE_RENT_CAP - CHEAP_RENT_FLOOR


def _rating_score(rating: float | None) -> float:
    """Return the rating subscore (0\u201325)."""

    if not rating:
        return 0.0
    return max(0.0, (rating / MAX_RATING) * RATING_WEIGHT)


def _walk_score(walk_min: int | float | None) -> float:
    """Return the walk subscore (0\u201325).

    30 minutes of walking drops the subscore to zero.
    """

    if walk_min is None:
        return 0.0
    return max(0.0, WALK_WEIGHT * (1 - walk_min / MAX_WALK_MINUTES))


def _drive_score(drive_min: int | float | None) -> float:
    """Return the drive subscore (0\u201320).

    1 minute = full credit, 10 minutes = zero.
    """

    if drive_min is None:
        return 0.0
    span = MAX_DRIVE_MINUTES - MIN_DRIVE_MINUTES
    return max(0.0, DRIVE_WEIGHT * (1 - (drive_min - MIN_DRIVE_MINUTES) / span))


def _cost_score(one_br: int | None) -> float:
    """Return the one-bedroom rent subscore (0\u201330).

    Rents at or below $1,800 get full credit; $3,500+ gets zero.
    """

    if one_br is None:
        return 0.0
    return max(0.0, COST_WEIGHT * (1 - (one_br - CHEAP_RENT_FLOOR) / RENT_RANGE))


def calc_score(
    *,
    rating: float | None,
    walk_min: int | float | None,
    drive_min: int | float | None,
    one_br: int | None,
) -> int:
    """Return the composite score for a single building, rounded to an int.

    Individually clamped subscores mean a missing input reduces the total
    without pushing any component negative. The sum is also clamped to
    ``[0, 100]`` so downstream UIs never have to worry about the edge case
    where a hypothetical rating > 5 or rent < $1,800 overshoots.
    """

    total = (
        _rating_score(rating)
        + _walk_score(walk_min)
        + _drive_score(drive_min)
        + _cost_score(one_br)
    )
    clamped = max(0.0, min(100.0, total))
    return round(clamped)

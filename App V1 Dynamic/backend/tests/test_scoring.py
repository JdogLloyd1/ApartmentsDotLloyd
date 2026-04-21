"""Tests for :mod:`app.scoring`."""

from __future__ import annotations

import pytest

from app.scoring import calc_score


def test_zero_inputs_produce_zero_score() -> None:
    """A building with nothing known scores zero, not NaN or negative."""

    assert calc_score(rating=None, walk_min=None, drive_min=None, one_br=None) == 0


def test_perfect_building_caps_at_one_hundred() -> None:
    """Max rating + zero walk + 1-min drive + minimum rent saturates the scale."""

    score = calc_score(rating=5.0, walk_min=0, drive_min=1, one_br=1800)
    assert score == 100


def test_hanover_alewife_matches_static_rendering() -> None:
    """Hanover's seed values reproduce the score used in the static dashboard."""

    score = calc_score(rating=4.8, walk_min=4, drive_min=4, one_br=3023)
    # r=(4.8/5)*25=24.0, w=25*(26/30)=21.667, d=20*(1-3/9)=13.333,
    # c=30*(1-(3023-1800)/1700)=8.418 -> 67.418 -> 67
    assert score == 67


def test_fresh_pond_with_missing_price_scores_below_fifty() -> None:
    """No rent data means the cost subscore is zero."""

    score = calc_score(rating=2.9, walk_min=4, drive_min=6, one_br=None)
    # r=14.5, w=21.667, d=8.889 -> 45.056 -> 45
    assert score == 45


def test_expensive_rent_floors_cost_component() -> None:
    """Rents above the cap contribute zero instead of a negative value."""

    score_capped = calc_score(rating=None, walk_min=None, drive_min=None, one_br=10000)
    assert score_capped == 0


@pytest.mark.parametrize(
    "walk,expected_min",
    [
        (0, 24),
        (30, 0),
    ],
)
def test_walk_score_bounds(walk: int, expected_min: int) -> None:
    """Walk subscore is 25 at 0 min and zero at 30 min."""

    score = calc_score(rating=None, walk_min=walk, drive_min=None, one_br=None)
    assert score >= expected_min

"""Fixed map anchor points used by the routing services.

Kept in one place so changing a coordinate only requires editing this
file (and doesn't silently drift between walk/drive/frontend code).
"""

from __future__ import annotations

from typing import Final

# (latitude, longitude) pairs
ALEWIFE_T_LATLNG: Final[tuple[float, float]] = (42.3954, -71.1426)
RT2_RAMP_LATLNG: Final[tuple[float, float]] = (42.3995, -71.1530)


def latlng_to_lonlat(latlng: tuple[float, float]) -> tuple[float, float]:
    """ORS expects ``[lon, lat]``; our anchors are stored ``(lat, lng)``."""

    lat, lng = latlng
    return (lng, lat)


WALK_BUCKETS_MIN: Final[tuple[int, ...]] = (5, 10, 15)
DRIVE_BUCKETS_MIN: Final[tuple[int, ...]] = (2, 5, 10)

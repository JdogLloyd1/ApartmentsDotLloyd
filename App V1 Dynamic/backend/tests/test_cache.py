"""TTL cache + ``X-Data-Freshness`` header behavior."""

from __future__ import annotations

import time

from app.cache import _ResponseCache, get_or_compute, invalidate_all


def test_cache_returns_cached_value_until_invalidated() -> None:
    """A second call within TTL must reuse the cached value."""

    invalidate_all()
    calls = {"count": 0}

    def compute() -> str:
        calls["count"] += 1
        return f"value-{calls['count']}"

    first, age_first = get_or_compute("test:key", compute)
    second, age_second = get_or_compute("test:key", compute)

    assert first == "value-1"
    assert second == "value-1"
    assert age_first == 0.0
    assert age_second >= age_first
    assert calls["count"] == 1


def test_invalidate_all_forces_recomputation() -> None:
    """Clearing the cache must trigger a fresh ``compute()``."""

    invalidate_all()
    counter = {"n": 0}

    def compute() -> int:
        counter["n"] += 1
        return counter["n"]

    first, _ = get_or_compute("invalidation:test", compute)
    invalidate_all()
    second, age = get_or_compute("invalidation:test", compute)

    assert first == 1
    assert second == 2
    assert age == 0.0


def test_ttl_expiry_recomputes() -> None:
    """When the TTL elapses, the next access must recompute the value."""

    cache = _ResponseCache(maxsize=4, ttl=0.05)
    counter = {"n": 0}

    def compute() -> int:
        counter["n"] += 1
        return counter["n"]

    first, _ = cache.get_or_compute("ttl:test", compute)
    time.sleep(0.07)
    second, age = cache.get_or_compute("ttl:test", compute)

    assert first == 1
    assert second == 2
    assert age == 0.0

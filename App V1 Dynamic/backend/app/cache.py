"""Tiny in-process response cache for the read-mostly endpoints.

Wraps :class:`cachetools.TTLCache` with a thread-safe lock so concurrent
requests don't recompute the payload during a thundering-herd. Only used
by ``/api/buildings`` and ``/api/isochrones`` \u2014 the writes happen via
the refresh services, which call :func:`invalidate_all` when finished.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from cachetools import TTLCache

DEFAULT_TTL_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class CachedEntry:
    """One stored cache value plus the time it was inserted."""

    value: object
    inserted_at: float


class _ResponseCache:
    """Single shared cache keyed by string. Tiny by design \u2014 a few
    endpoints, not per-user keys."""

    def __init__(self, *, maxsize: int = 32, ttl: float = DEFAULT_TTL_SECONDS) -> None:
        self._cache: TTLCache[str, CachedEntry] = TTLCache(maxsize=maxsize, ttl=ttl)
        self._lock = threading.Lock()

    def get_or_compute[T](self, key: str, compute: Callable[[], T]) -> tuple[T, float]:
        """Return ``(value, age_seconds)`` for ``key``.

        Holds a global lock during ``compute()`` so two simultaneous
        cache misses don't both run the expensive query. Returns the
        cached value's age so callers can populate
        ``X-Data-Freshness``.
        """

        with self._lock:
            entry = self._cache.get(key)
            if entry is not None:
                age = max(0.0, time.monotonic() - entry.inserted_at)
                return entry.value, age  # type: ignore[return-value]
            value = compute()
            self._cache[key] = CachedEntry(value=value, inserted_at=time.monotonic())
            return value, 0.0

    def invalidate(self, key: str) -> None:
        with self._lock:
            self._cache.pop(key, None)

    def invalidate_all(self) -> None:
        with self._lock:
            self._cache.clear()


_response_cache = _ResponseCache()


def get_or_compute[T](key: str, compute: Callable[[], T]) -> tuple[T, float]:
    """Module-level convenience around :class:`_ResponseCache`."""

    return _response_cache.get_or_compute(key, compute)


def invalidate_all() -> None:
    """Clear the entire response cache (called after a refresh run)."""

    _response_cache.invalidate_all()

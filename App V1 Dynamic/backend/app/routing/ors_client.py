"""Thin async HTTP client for OpenRouteService.

We hit two endpoints: ``/v2/matrix/{profile}`` for travel-time matrices and
``/v2/isochrones/{profile}`` for reachability polygons. Both accept
``[lon, lat]`` coordinate pairs; docs at
https://openrouteservice.org/dev/#/api-docs.
"""

from __future__ import annotations

from typing import Any

import httpx

ORS_BASE_URL = "https://api.openrouteservice.org"
DEFAULT_TIMEOUT_S = 30.0

LonLat = tuple[float, float]


class ORSError(RuntimeError):
    """Raised when ORS returns a non-2xx response or unparseable body."""


class ORSClient:
    """Async client for the subset of ORS endpoints the app uses.

    Instantiate per-refresh or reuse across refreshes; the underlying
    ``httpx.AsyncClient`` is created lazily and closed via :meth:`aclose`.
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = ORS_BASE_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("ORS_API_KEY is required")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> ORSClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client if we created it."""

        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self._timeout_s,
                headers={
                    "Authorization": self._api_key,
                    "Accept": "application/json, application/geo+json",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        client = self._get_client()
        try:
            response = await client.post(url, json=body)
        except httpx.HTTPError as exc:
            raise ORSError(f"ORS request to {path} failed: {exc}") from exc
        if response.status_code >= 400:
            raise ORSError(
                f"ORS {path} returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise ORSError(f"ORS {path} returned non-JSON body") from exc

    async def matrix(
        self,
        profile: str,
        *,
        sources: list[LonLat],
        destination: LonLat,
    ) -> list[float | None]:
        """Return per-source travel-time-in-seconds to ``destination``.

        ``profile`` is one of ``foot-walking`` or ``driving-car``. ORS's
        matrix endpoint returns a 2D ``durations`` array; we flatten it to
        a 1D list of seconds (or ``None`` where ORS couldn't route).
        """

        locations: list[LonLat] = [*sources, destination]
        destination_index = len(locations) - 1
        source_indices = list(range(len(sources)))
        body = {
            "locations": [list(coord) for coord in locations],
            "sources": source_indices,
            "destinations": [destination_index],
            "metrics": ["duration"],
            "units": "m",
        }
        payload = await self._post(f"/v2/matrix/{profile}", body)
        durations = payload.get("durations")
        if not isinstance(durations, list):
            raise ORSError("ORS matrix response missing 'durations'")
        return [row[0] if row and row[0] is not None else None for row in durations]

    async def isochrones(
        self,
        profile: str,
        *,
        anchor: LonLat,
        range_seconds: list[int],
    ) -> dict[str, Any]:
        """Return the raw GeoJSON ``FeatureCollection`` from ORS.

        Callers split the features into one row per bucket before
        persisting.
        """

        body = {
            "locations": [list(anchor)],
            "range": range_seconds,
            "range_type": "time",
            "attributes": ["reachfactor", "area"],
            "area_units": "m",
        }
        payload = await self._post(f"/v2/isochrones/{profile}", body)
        if payload.get("type") != "FeatureCollection":
            raise ORSError("ORS isochrones response is not a FeatureCollection")
        return payload

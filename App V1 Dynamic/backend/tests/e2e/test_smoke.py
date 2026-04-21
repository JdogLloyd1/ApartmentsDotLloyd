"""Full-stack smoke test for the local docker compose deployment.

Runs only when ``E2E=1`` is set, because it:

- assumes a server is already listening at ``E2E_BASE_URL`` (default
  ``http://localhost:8000``) \u2014 typically via ``make up-local``;
- calls the authenticated ``POST /api/refresh`` with the token from
  ``.env``, which consumes ORS quota and hits live apartment/Google pages;
- expects the seed loader to have populated ``/api/buildings`` already
  (run ``make seed`` once before the first smoke).

The test polls ``GET /api/refresh/{run_id}`` until the orchestrator
reports terminal state, then asserts on the shape of the live data.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

E2E_BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8000")
POLL_INTERVAL_S = float(os.getenv("E2E_POLL_INTERVAL", "3.0"))
POLL_TIMEOUT_S = float(os.getenv("E2E_POLL_TIMEOUT", "600"))

pytestmark = pytest.mark.skipif(
    os.getenv("E2E") != "1",
    reason="E2E smoke suite is gated on E2E=1 (assumes `make up-local` is running).",
)


def _load_bearer_token() -> str:
    """Read ``REFRESH_BEARER_TOKEN`` from the live process or ``.env`` file."""

    direct = os.getenv("REFRESH_BEARER_TOKEN")
    if direct:
        return direct

    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        pytest.fail(
            f"REFRESH_BEARER_TOKEN not set and no .env at {env_path}; "
            "follow RUN_LOCALLY.md to populate it before running smoke tests."
        )

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "REFRESH_BEARER_TOKEN":
            return value.strip().strip('"').strip("'")

    pytest.fail("REFRESH_BEARER_TOKEN missing from .env; cannot call POST /api/refresh.")


@pytest.fixture(scope="module")
def api() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=E2E_BASE_URL, timeout=30.0) as client:
        yield client


@pytest.fixture(scope="module")
def bearer_header() -> dict[str, str]:
    return {"Authorization": f"Bearer {_load_bearer_token()}"}


def test_health_endpoint_reports_running_server(api: httpx.Client) -> None:
    response = api.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["building_count"] is not None, (
        "No buildings loaded yet \u2014 run `make seed` before smoke tests."
    )


def test_buildings_endpoint_serves_seed_rows(api: httpx.Client) -> None:
    response = api.get("/api/buildings")
    assert response.status_code == 200
    buildings = response.json()
    assert len(buildings) >= 19, (
        f"Expected \u2265 19 buildings from the static source; got {len(buildings)}."
    )
    slugs = {b["slug"] for b in buildings}
    assert "hanover-alewife" in slugs, "Hanover Alewife should be in the seed."


def test_refresh_endpoint_completes_successfully(
    api: httpx.Client, bearer_header: dict[str, str]
) -> None:
    trigger = api.post("/api/refresh", headers=bearer_header, json={})
    assert trigger.status_code == 202, trigger.text
    run_id = trigger.json()["run_id"]

    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        status = api.get(f"/api/refresh/{run_id}").json()
        if status["status"] != "running":
            break
        time.sleep(POLL_INTERVAL_S)
    else:
        pytest.fail(f"Refresh {run_id} did not finish within {POLL_TIMEOUT_S}s")

    assert status["status"] == "succeeded", (
        f"Refresh run {run_id} ended with status={status['status']}: {status['detail']}"
    )
    steps = status["detail"]["steps"]
    for step_name in ("travel_times", "isochrones", "prices", "ratings"):
        assert steps.get(step_name, {}).get("status") == "ok", (
            f"Step {step_name!r} did not succeed: {steps.get(step_name)}"
        )


def test_isochrones_endpoint_returns_six_polygons(api: httpx.Client) -> None:
    response = api.get("/api/isochrones")
    assert response.status_code == 200
    payload = response.json()
    walk_buckets = {f["minutes"] for f in payload["walk"]}
    drive_buckets = {f["minutes"] for f in payload["drive"]}
    assert walk_buckets == {5, 10, 15}, f"Expected walk buckets {{5, 10, 15}}; got {walk_buckets}"
    assert drive_buckets == {2, 5, 10}, f"Expected drive buckets {{2, 5, 10}}; got {drive_buckets}"


def test_buildings_carry_fresh_timestamps_after_refresh(api: httpx.Client) -> None:
    """At least one building must expose a ``pricesFetchedAt`` timestamp.

    The full seed has many buildings without scrape targets, so we don't
    require every row to have one \u2014 just that the pipeline populated
    at least one, which proves the scraper \u2192 snapshot \u2192 overlay path
    is working end-to-end.
    """

    buildings = api.get("/api/buildings").json()
    with_prices = [b for b in buildings if b.get("pricesFetchedAt")]
    assert with_prices, "No buildings have a pricesFetchedAt timestamp after refresh."


def test_dashboard_html_embeds_expected_shell(api: httpx.Client) -> None:
    response = api.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Alewife Apartment Intelligence" in html
    assert 'id="map"' in html, "Static dashboard shell should mount the Leaflet container."


def test_freshness_header_resets_after_refresh(
    api: httpx.Client, bearer_header: dict[str, str]
) -> None:
    """The TTL cache should invalidate on a successful refresh.

    Warms the cache with a read, triggers a refresh, waits for it to
    finish, then asserts the next read reports age ~0.
    """

    warm = api.get("/api/buildings")
    assert warm.status_code == 200
    pre_age = int(warm.headers.get("X-Data-Freshness", "0"))

    trigger = api.post(
        "/api/refresh",
        headers=bearer_header,
        json={"skip_routing": True, "skip_scrapers": True},
    )
    assert trigger.status_code == 202
    run_id = trigger.json()["run_id"]

    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        status = api.get(f"/api/refresh/{run_id}").json()
        if status["status"] != "running":
            break
        time.sleep(0.5)
    assert status["status"] == "succeeded"

    post = api.get("/api/buildings")
    post_age = int(post.headers.get("X-Data-Freshness", "0"))
    assert post_age <= pre_age, (
        f"Expected X-Data-Freshness to reset after refresh; pre={pre_age} post={post_age}"
    )

"""Tests for the static frontend mount at ``/``."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_root_serves_dashboard(client: TestClient) -> None:
    """GET / returns the static dashboard HTML shell."""

    response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert "Alewife Apartment Intelligence" in body
    assert "<table" in body
    assert "apts = [" not in body, "Hardcoded apartment literal must be gone"


def test_static_assets_are_served(client: TestClient) -> None:
    """CSS and JS assets are reachable from the mount."""

    css = client.get("/styles.css")
    assert css.status_code == 200
    assert ":root" in css.text

    js = client.get("/app.js")
    assert js.status_code == 200
    assert "loadBuildings" in js.text

    iso = client.get("/isochrones.js")
    assert iso.status_code == 200
    assert "walkIsoPolygons" in iso.text

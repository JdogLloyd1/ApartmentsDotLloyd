"""Opt-in Playwright smoke test for the static dashboard.

Skipped by default so CI and most local runs stay fast. Enable with
``E2E=1 pytest tests/test_frontend_browser.py``; requires
``playwright install chromium`` once.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import httpx
import pytest

from app.config import BACKEND_DIR

pytestmark = pytest.mark.skipif(
    os.environ.get("E2E") != "1",
    reason="Set E2E=1 to run the Playwright smoke test",
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    pytest.skip("playwright not installed", allow_module_level=True)


def _pick_free_port() -> int:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_for_http(url: str, timeout_s: float = 20.0) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout_s:
        try:
            response = httpx.get(url, timeout=1.0)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {url}")


@pytest.fixture
def running_app(tmp_path: Path) -> Iterator[str]:
    """Spin up uvicorn on a random port with a fresh seeded DB."""

    db_path = tmp_path / "e2e.db"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"

    subprocess.check_call(
        [sys.executable, "-m", "app.seed.loader"],
        cwd=BACKEND_DIR,
        env=env,
    )

    port = _pick_free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=BACKEND_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_http(f"{base_url}/api/health")
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_dashboard_renders_all_buildings(running_app: str) -> None:
    """Headless browser loads the dashboard; table has 19 rows."""

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(running_app, wait_until="networkidle")
            page.wait_for_selector("#tableBody tr")
            row_count = page.eval_on_selector_all("#tableBody tr", "rows => rows.length")
            assert row_count == 19

            badge_text = page.text_content("#buildingCountBadge")
            assert badge_text is not None
            assert "19" in badge_text
        finally:
            browser.close()

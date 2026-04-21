"""Playwright-backed HTML fetcher for the scraping services.

Split from the parsers so tests can inject a fake fetcher and never
launch a real browser. The services in this package only care that
:class:`HTMLFetcher` returns HTML for a URL \u2014 they don't touch
Playwright directly.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DEFAULT_VIEWPORT = {"width": 1440, "height": 900}
DEFAULT_TIMEOUT_MS = 30_000


class HTMLFetcher(Protocol):
    """Minimal protocol for anything that can fetch HTML from a URL."""

    async def fetch(self, url: str, *, wait_for_selector: str | None = None) -> str: ...


async def jitter(min_seconds: float = 0.8, max_seconds: float = 2.4) -> None:
    """Random sleep to soften scrape cadence across pages."""

    await asyncio.sleep(random.uniform(min_seconds, max_seconds))


class PlaywrightFetcher:
    """Fetch HTML via a shared Playwright Chromium browser.

    Use as an async context manager; the browser launches on enter and
    closes on exit. Internally creates a fresh browser context per
    ``fetch()`` call to avoid cross-site cookie leakage.
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        user_agent: str = USER_AGENT,
    ) -> None:
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._user_agent = user_agent
        self._playwright = None
        self._browser = None

    async def __aenter__(self) -> PlaywrightFetcher:
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self._headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._browser is not None:
            await self._browser.close()
            self._browser = None
        if self._playwright is not None:
            await self._playwright.stop()
            self._playwright = None

    async def fetch(self, url: str, *, wait_for_selector: str | None = None) -> str:
        """Return the full HTML of ``url`` after the DOM is interactive."""

        if self._browser is None:
            raise RuntimeError("PlaywrightFetcher must be used as async context manager")

        context = await self._browser.new_context(
            user_agent=self._user_agent,
            viewport=DEFAULT_VIEWPORT,
            locale="en-US",
        )
        try:
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = await context.new_page()
            page.set_default_timeout(self._timeout_ms)
            try:
                response = await page.goto(url, wait_until="domcontentloaded")
                if response is not None and response.status >= 400:
                    logger.warning("fetch %s returned HTTP %s", url, response.status)
                if wait_for_selector:
                    try:
                        await page.wait_for_selector(wait_for_selector, timeout=10_000)
                    except Exception as exc:
                        logger.info("wait_for_selector %r timed out on %s: %s", wait_for_selector, url, exc)
                html = await page.content()
            finally:
                await page.close()
        finally:
            await context.close()
        return html


@asynccontextmanager
async def playwright_session(**kwargs: object) -> AsyncIterator[PlaywrightFetcher]:
    """Convenience wrapper so callers can ``async with playwright_session() as f:``."""

    fetcher = PlaywrightFetcher(**kwargs)  # type: ignore[arg-type]
    async with fetcher:
        yield fetcher

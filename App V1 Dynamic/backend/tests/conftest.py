"""Shared pytest fixtures for the backend test suite."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.cache import invalidate_all
from app.config import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def _reset_settings_cache() -> Iterator[None]:
    """Ensure ``get_settings`` re-reads the environment for every test."""

    get_settings.cache_clear()
    invalidate_all()
    yield
    get_settings.cache_clear()
    invalidate_all()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Provide a FastAPI test client for integration tests."""

    app = create_app()
    with TestClient(app) as http_client:
        yield http_client

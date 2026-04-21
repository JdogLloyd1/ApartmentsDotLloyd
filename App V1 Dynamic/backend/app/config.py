"""Application configuration loaded from environment variables.

Settings are read from the process environment, optionally seeded from a
local ``.env`` file at ``App V1 Dynamic/backend/.env``. Secrets never live
in the committed codebase; :file:`.env.example` lists the shape.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = BACKEND_DIR / "alewife.db"


class Settings(BaseSettings):
    """Typed runtime configuration.

    The ``model_config`` points at the backend-local ``.env``; other
    projects in the repo have their own ``.env`` files that are not
    read by this app.
    """

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Alewife Apartment Intelligence"
    app_version: str = "0.1.0"
    environment: str = Field(default="local", description="local | staging | production")

    database_url: str = Field(
        default=f"sqlite:///{DEFAULT_DB_PATH}",
        description="SQLAlchemy-style DB URL. SQLite by default for local dev.",
    )

    ors_api_key: str | None = Field(
        default=None,
        description="OpenRouteService API key. Required for /api/isochrones and "
        "travel-time refreshes; unused at boot.",
    )

    refresh_bearer_token: str | None = Field(
        default=None,
        description="Shared secret required to POST /api/refresh.",
    )

    refresh_scheduler_enabled: bool = Field(
        default=False,
        description="Start APScheduler in the FastAPI lifespan. Off by "
        "default so tests and one-shot CLI runs don't spawn cron jobs.",
    )
    refresh_daily_cron: str | None = Field(
        default=None,
        description="Cron expression for the nightly full refresh (UTC). "
        'Example: "30 7 * * *" \u2248 03:30 America/New_York during DST.',
    )
    refresh_hourly_cron: str | None = Field(
        default=None,
        description="Cron expression for hourly price-only refreshes (UTC).",
    )

    mbta_api_key: str | None = Field(
        default=None,
        description="Optional MBTA V3 API key for future live-headways features.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached ``Settings`` instance.

    Cached so repeated calls inside request handlers don't re-parse env files.
    Tests can clear the cache via ``get_settings.cache_clear()``.
    """

    return Settings()

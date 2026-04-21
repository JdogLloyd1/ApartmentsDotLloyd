"""FastAPI application entry point.

Sprint 0 exposes only ``GET /api/health``. Feature routers (buildings,
isochrones, refresh) are wired in by later sprints.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.buildings import router as buildings_router
from app.api.health import router as health_router
from app.api.isochrones import router as isochrones_router
from app.api.refresh import router as refresh_router
from app.config import BACKEND_DIR, get_settings
from app.db import init_db
from app.scheduler import shutdown_scheduler, start_scheduler

FRONTEND_DIR = BACKEND_DIR.parent / "frontend"


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan hook: create tables and start the scheduler.

    ``init_db`` is idempotent so this is safe on every restart. The
    scheduler is no-ops when ``REFRESH_SCHEDULER_ENABLED`` is false, so
    this stays cheap in tests and CLI invocations.
    """

    init_db()
    start_scheduler()
    try:
        yield
    finally:
        shutdown_scheduler()


def _mount_frontend(app: FastAPI, frontend_dir: Path) -> None:
    """Serve the static dashboard from ``/`` if the bundle exists.

    Absent frontend directory is a soft failure: the API still serves
    ``/api/*`` and ``/docs``. This keeps tests that only need the
    backend from needing the frontend on the filesystem.
    """

    if not frontend_dir.exists():
        return
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application.

    Split from module load so tests can construct throw-away apps with
    overridden settings.
    """

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "Backend for the Alewife apartment intelligence dashboard. "
            "Serves building data, scraped prices, ratings, and "
            "OpenRouteService-computed travel times and isochrones."
        ),
        lifespan=_lifespan,
    )
    app.include_router(health_router, prefix="/api")
    app.include_router(buildings_router, prefix="/api")
    app.include_router(isochrones_router, prefix="/api")
    app.include_router(refresh_router, prefix="/api")
    _mount_frontend(app, FRONTEND_DIR)
    return app


app = create_app()

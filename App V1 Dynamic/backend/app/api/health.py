"""Health-check endpoint used by uptime monitors and CI smoke tests."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select

from app.config import get_settings
from app.db import get_engine
from app.models import Building

router = APIRouter(tags=["health"])

SCHEMA_VERSION = 1


class HealthResponse(BaseModel):
    """Response shape for the health endpoint."""

    status: str
    app: str
    version: str
    environment: str
    schema_version: int
    building_count: int | None = None


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def get_health() -> HealthResponse:
    """Return a minimal liveness payload plus DB row count.

    Swallows DB errors and reports ``building_count=None`` so the
    endpoint still succeeds before ``init_db`` has run.
    """

    settings = get_settings()
    building_count: int | None = None
    try:
        with Session(get_engine()) as session:
            building_count = session.exec(select(func.count()).select_from(Building)).one()
    except Exception:
        building_count = None
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        schema_version=SCHEMA_VERSION,
        building_count=building_count,
    )

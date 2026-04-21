"""Manual refresh trigger + status polling.

``POST /api/refresh`` requires the bearer token configured via
``REFRESH_BEARER_TOKEN``. Triggers happen in the background; the
endpoint returns immediately with a ``run_id`` the caller can poll via
``GET /api/refresh/{run_id}``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlmodel import Session

from app.config import get_settings
from app.db import get_engine
from app.models import RefreshRun
from app.refresh_service import schedule_refresh

router = APIRouter(tags=["refresh"])
_bearer = HTTPBearer(auto_error=False)
_BearerCreds = HTTPAuthorizationCredentials | None
_bearer_dep = Depends(_bearer)


class RefreshRequest(BaseModel):
    """Optional knobs the caller can pass with the trigger."""

    skip_routing: bool = False
    skip_scrapers: bool = False
    slugs: list[str] | None = None


class RefreshResponse(BaseModel):
    """Returned by ``POST /api/refresh``."""

    run_id: int
    status: str
    started_at: datetime


class RefreshStatus(BaseModel):
    """Returned by ``GET /api/refresh/{run_id}``."""

    run_id: int
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None
    detail: dict[str, Any]


def _require_bearer(
    credentials: _BearerCreds = _bearer_dep,
) -> None:
    """Reject requests without a valid ``Authorization: Bearer ...`` header.

    Returns ``401`` when the token is missing or wrong; ``503`` when no
    token is configured server-side (forces an explicit deploy step).
    """

    settings = get_settings()
    if not settings.refresh_bearer_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="REFRESH_BEARER_TOKEN is not configured",
        )
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token required",
        )
    if credentials.credentials != settings.refresh_bearer_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bearer token",
        )


@router.post(
    "/refresh",
    response_model=RefreshResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger a background refresh run",
    dependencies=[Depends(_require_bearer)],
)
async def trigger_refresh(payload: RefreshRequest | None = None) -> RefreshResponse:
    """Spawn a refresh and return the new ``run_id``.

    Returns ``202 Accepted`` immediately; the actual refresh keeps
    running on the background event loop. Declared ``async`` so
    :func:`asyncio.create_task` inside :func:`schedule_refresh` can
    attach to the running loop \u2014 sync handlers would run in a
    threadpool with no loop bound.
    """

    payload = payload or RefreshRequest()
    run_id = schedule_refresh(
        trigger="manual",
        do_routing=not payload.skip_routing,
        do_scrapers=not payload.skip_scrapers,
        slugs=payload.slugs,
    )
    with Session(get_engine()) as session:
        run = session.get(RefreshRun, run_id)
        assert run is not None
        return RefreshResponse(
            run_id=run_id, status=run.status, started_at=run.started_at
        )


@router.get(
    "/refresh/{run_id}",
    response_model=RefreshStatus,
    summary="Check the status of a refresh run",
)
def get_refresh_status(run_id: int) -> RefreshStatus:
    with Session(get_engine()) as session:
        run = session.get(RefreshRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown run_id: {run_id}",
        )
    return RefreshStatus(
        run_id=run_id,
        status=run.status,
        trigger=run.trigger,
        started_at=run.started_at,
        finished_at=run.finished_at,
        detail=dict(run.detail),
    )

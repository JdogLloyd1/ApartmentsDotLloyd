"""Orchestrate a refresh run: ORS \u2192 scrapers \u2192 cache invalidation.

Persists per-step status to the :class:`RefreshRun` table so callers can
poll for progress via ``GET /api/refresh/{run_id}``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session

from app.cache import invalidate_all
from app.db import get_engine
from app.models import RefreshRun
from app.routing.isochrone_service import refresh_isochrones
from app.routing.travel_time_service import refresh_travel_times
from app.scrapers.base import HTMLFetcher, PlaywrightFetcher
from app.scrapers.price_service import refresh_prices
from app.scrapers.rating_service import refresh_ratings

logger = logging.getLogger(__name__)

_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


def _create_run(trigger: str) -> int:
    """Insert a fresh ``running`` row and return its primary key."""

    run = RefreshRun(trigger=trigger, status="running")
    with Session(get_engine()) as session:
        session.add(run)
        session.commit()
        session.refresh(run)
    assert run.id is not None
    return run.id


def _finalize_run(run_id: int, *, status: str, detail: dict[str, Any]) -> None:
    """Mark a run as ``succeeded`` / ``failed`` and stamp ``finished_at``."""

    with Session(get_engine()) as session:
        run = session.get(RefreshRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = datetime.now(UTC)
        run.detail = detail
        session.add(run)
        session.commit()


async def _run_steps(
    run_id: int,
    *,
    fetcher: HTMLFetcher | None,
    do_routing: bool,
    do_scrapers: bool,
    slugs: list[str] | None,
) -> dict[str, Any]:
    """Execute every requested step, recording per-step success/failure."""

    detail: dict[str, Any] = {"steps": {}}

    if do_routing:
        try:
            travel = await refresh_travel_times()
            detail["steps"]["travel_times"] = {"status": "ok", **travel}
        except Exception as exc:
            logger.exception("travel_times step failed")
            detail["steps"]["travel_times"] = {"status": "error", "error": str(exc)}
        try:
            iso = await refresh_isochrones()
            detail["steps"]["isochrones"] = {"status": "ok", **iso}
        except Exception as exc:
            logger.exception("isochrones step failed")
            detail["steps"]["isochrones"] = {"status": "error", "error": str(exc)}

    if do_scrapers:
        own_fetcher = fetcher is None
        if own_fetcher:
            fetcher = PlaywrightFetcher()
            await fetcher.__aenter__()
        try:
            try:
                prices = await refresh_prices(fetcher=fetcher, slugs=slugs)
                detail["steps"]["prices"] = {
                    "status": "ok",
                    "attempted": prices.attempted,
                    "succeeded": prices.succeeded,
                    "failed": prices.failed,
                    "skipped": prices.skipped,
                }
            except Exception as exc:
                logger.exception("prices step failed")
                detail["steps"]["prices"] = {"status": "error", "error": str(exc)}
            try:
                ratings = await refresh_ratings(fetcher=fetcher, slugs=slugs)
                detail["steps"]["ratings"] = {
                    "status": "ok",
                    "attempted": ratings.attempted,
                    "succeeded": ratings.succeeded,
                    "failed": ratings.failed,
                    "skipped": ratings.skipped,
                }
            except Exception as exc:
                logger.exception("ratings step failed")
                detail["steps"]["ratings"] = {"status": "error", "error": str(exc)}
        finally:
            if own_fetcher and fetcher is not None:
                await fetcher.__aexit__(None, None, None)

    invalidate_all()
    return detail


async def execute_refresh(
    *,
    trigger: str = "manual",
    fetcher: HTMLFetcher | None = None,
    do_routing: bool = True,
    do_scrapers: bool = True,
    slugs: list[str] | None = None,
) -> int:
    """Run a refresh inline and return the persisted ``run_id``.

    Use :func:`schedule_refresh` to fire-and-forget instead.
    """

    run_id = _create_run(trigger)
    try:
        detail = await _run_steps(
            run_id,
            fetcher=fetcher,
            do_routing=do_routing,
            do_scrapers=do_scrapers,
            slugs=slugs,
        )
    except Exception as exc:
        logger.exception("refresh run %s failed unexpectedly", run_id)
        _finalize_run(run_id, status="failed", detail={"error": str(exc)})
        raise

    has_step_errors = any(
        step.get("status") == "error" for step in detail.get("steps", {}).values()
    )
    _finalize_run(
        run_id,
        status="failed" if has_step_errors else "succeeded",
        detail=detail,
    )
    return run_id


def schedule_refresh(
    *,
    trigger: str = "manual",
    do_routing: bool = True,
    do_scrapers: bool = True,
    slugs: list[str] | None = None,
) -> int:
    """Spawn a refresh on the running event loop and return its ``run_id`` immediately."""

    run_id = _create_run(trigger)

    async def _runner() -> None:
        try:
            detail = await _run_steps(
                run_id,
                fetcher=None,
                do_routing=do_routing,
                do_scrapers=do_scrapers,
                slugs=slugs,
            )
        except Exception as exc:
            logger.exception("background refresh %s failed", run_id)
            _finalize_run(run_id, status="failed", detail={"error": str(exc)})
            return
        has_step_errors = any(
            step.get("status") == "error" for step in detail.get("steps", {}).values()
        )
        _finalize_run(
            run_id,
            status="failed" if has_step_errors else "succeeded",
            detail=detail,
        )

    task = asyncio.create_task(_runner(), name=f"refresh-{run_id}")
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return run_id

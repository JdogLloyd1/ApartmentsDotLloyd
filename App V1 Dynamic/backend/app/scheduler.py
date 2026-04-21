"""APScheduler wiring used by the FastAPI lifespan.

Two cron jobs:

- ``daily_refresh`` runs at ``REFRESH_DAILY_CRON`` (default 03:30 ET)
  and refreshes both routing data and scrapers. Cheap and aggressive
  because it runs at off hours.
- ``hourly_prices`` (default ``REFRESH_HOURLY_CRON``) refreshes only
  prices to keep the cheapest column reasonably fresh during the day.

Disabled in tests by setting ``REFRESH_SCHEDULER_ENABLED=false``.
"""

from __future__ import annotations

import logging
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import get_settings
from app.refresh_service import execute_refresh

logger = logging.getLogger(__name__)

DEFAULT_DAILY_CRON = "30 7 * * *"
DEFAULT_HOURLY_CRON = "0 13-23 * * *"


_scheduler: AsyncIOScheduler | None = None


async def _scheduled_full_refresh() -> None:
    """APScheduler callback: full refresh, swallowing exceptions for the next tick."""

    try:
        await execute_refresh(trigger="scheduled")
    except Exception:
        logger.exception("scheduled full refresh failed")


async def _scheduled_price_refresh() -> None:
    try:
        await execute_refresh(trigger="scheduled", do_routing=False)
    except Exception:
        logger.exception("scheduled price refresh failed")


def _build_trigger(expression: str) -> CronTrigger:
    """Parse an APScheduler-flavored cron expression with explicit UTC."""

    return CronTrigger.from_crontab(expression, timezone="UTC")


def start_scheduler() -> AsyncIOScheduler | None:
    """Start the scheduler if enabled, returning the running instance.

    Cron expressions are read from settings; missing values fall back to
    the defaults near the top of this module.
    """

    global _scheduler
    settings = get_settings()
    if not settings.refresh_scheduler_enabled:
        logger.info("scheduler disabled via REFRESH_SCHEDULER_ENABLED=false")
        return None
    if _scheduler is not None:
        return _scheduler

    daily = settings.refresh_daily_cron or DEFAULT_DAILY_CRON
    hourly = settings.refresh_hourly_cron or DEFAULT_HOURLY_CRON

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _scheduled_full_refresh,
        trigger=_build_trigger(daily),
        id="daily_refresh",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.add_job(
        _scheduled_price_refresh,
        trigger=_build_trigger(hourly),
        id="hourly_prices",
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )
    scheduler.start()
    logger.info(
        "scheduler started: daily_refresh=%r, hourly_prices=%r", daily, hourly
    )
    _scheduler = scheduler
    return scheduler


def shutdown_scheduler() -> None:
    """Stop the scheduler if it's running. Safe to call repeatedly."""

    global _scheduler
    if _scheduler is None:
        return
    try:
        _scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("scheduler shutdown raised")
    finally:
        _scheduler = None


def get_scheduler() -> Any:
    """Return the running scheduler instance, or ``None`` if not started."""

    return _scheduler

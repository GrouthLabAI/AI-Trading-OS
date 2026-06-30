# AI Trading OS - Persistent Scheduler
"""
Async scheduler built on APScheduler with SQLite persistence.
Manages time-driven tasks that survive server restarts.

Design:
- Uses APScheduler's AsyncIOScheduler (integrates with FastAPI asyncio).
- SQLAlchemyJobStore persists jobs to the existing trading.db.
- Separate from TaskManager: scheduler = time-driven, TaskManager = user-triggered.
- Jobs are defined here; the callbacks are registered by other modules via EventBus.

Usage:
    from backend.scheduler import scheduler

    await scheduler.start()
    scheduler.add_cron_job("pre_market_screen", my_func, hour=8, minute=30)
    await scheduler.stop()

Standard trading-day cron schedule (Beijing time):
    08:30 — Pre-market calibration screening
    09:00 — LLM deep confirmation (on calibrated candidates)
    18:00 — Overnight pre-screening + post-market review
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.triggers.cron import CronTrigger
from apscheduler.job import Job as ApJob
from sqlalchemy import create_engine

from backend.config import settings

logger = logging.getLogger(__name__)

# Sync engine for APScheduler job store (SQLAlchemyJobStore requires sync)
_sync_db_url = settings.database_url.replace("sqlite+aiosqlite:///", "sqlite:///")

_jobstores = {
    "default": SQLAlchemyJobStore(url=_sync_db_url, tablename="apscheduler_jobs")
}

_job_defaults = {
    "coalesce": True,          # Combine missed runs into one
    "max_instances": 1,        # Never run the same job concurrently
    "misfire_grace_time": 300,  # 5 min grace period for missed jobs
}


class Scheduler:
    """Persistent async scheduler wrapping APScheduler."""

    def __init__(self):
        self._scheduler: Optional[AsyncIOScheduler] = None
        self._started: bool = False

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self):
        """Initialize and start the scheduler. Call once from FastAPI lifespan."""
        if self._started:
            logger.warning("Scheduler: already started")
            return

        # Create the sync engine for the job store
        self._scheduler = AsyncIOScheduler(
            jobstores=_jobstores,
            job_defaults=_job_defaults,
            timezone="Asia/Shanghai",  # Beijing time
        )
        self._scheduler.start()
        self._started = True

        logger.info("Scheduler: started with SQLite job store (tz=Asia/Shanghai)")
        self._log_jobs()

    async def stop(self):
        """Shutdown the scheduler. Call from FastAPI shutdown."""
        if self._scheduler and self._started:
            self._scheduler.shutdown(wait=False)
            self._started = False
            logger.info("Scheduler: stopped")

    # ── Job management ────────────────────────────────────────────

    def add_cron_job(
        self,
        job_id: str,
        func: Callable[..., Any],
        *,
        hour: int,
        minute: int,
        day_of_week: str = "mon-fri",
        name: str = "",
        **kwargs: Any,
    ) -> str:
        """Add a cron job. Returns the job_id.

        Args:
            job_id: Unique identifier (e.g. 'pre_market_screen')
            func: Async or sync callable
            hour: 0-23 (Beijing time)
            minute: 0-59
            day_of_week: Cron day-of-week string (default 'mon-fri')
            name: Human-readable name for logging
            **kwargs: Passed to func when job fires
        """
        if not self._scheduler:
            raise RuntimeError("Scheduler not started. Call start() first.")

        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            day_of_week=day_of_week,
            timezone="Asia/Shanghai",
        )

        job = self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            kwargs=kwargs,
            replace_existing=True,
        )

        logger.info(
            f"Scheduler: added cron job '{job_id}' — "
            f"{day_of_week} {hour:02d}:{minute:02d} CST"
        )
        return job.id

    def add_interval_job(
        self,
        job_id: str,
        func: Callable[..., Any],
        *,
        seconds: int = 30,
        name: str = "",
        **kwargs: Any,
    ) -> str:
        """Add an interval job. Returns the job_id."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not started.")

        from apscheduler.triggers.interval import IntervalTrigger

        trigger = IntervalTrigger(seconds=seconds, timezone="Asia/Shanghai")

        job = self._scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            name=name or job_id,
            kwargs=kwargs,
            replace_existing=True,
        )

        logger.info(f"Scheduler: added interval job '{job_id}' — every {seconds}s")
        return job.id

    def remove_job(self, job_id: str) -> bool:
        """Remove a job by ID. Returns True if it existed."""
        if not self._scheduler:
            return False
        try:
            self._scheduler.remove_job(job_id)
            logger.info(f"Scheduler: removed job '{job_id}'")
            return True
        except Exception:
            return False

    def get_job(self, job_id: str) -> Optional[dict]:
        """Get job info by ID. Returns dict or None."""
        if not self._scheduler:
            return None
        try:
            job = self._scheduler.get_job(job_id)
            if job is None:
                return None
            return _job_to_dict(job)
        except Exception:
            return None

    def list_jobs(self) -> List[dict]:
        """List all registered jobs."""
        if not self._scheduler:
            return []
        return [_job_to_dict(j) for j in self._scheduler.get_jobs()]

    def _log_jobs(self):
        """Log all currently registered jobs."""
        jobs = self.list_jobs()
        if jobs:
            logger.info(f"Scheduler: {len(jobs)} job(s) registered:")
            for j in jobs:
                logger.info(f"  - {j['id']}: next_run={j.get('next_run', 'N/A')}")
        else:
            logger.info("Scheduler: no jobs registered yet")

    # ── Standard trading-day jobs ─────────────────────────────────

    def register_trading_day_jobs(self):
        """Register the standard set of trading-day cron jobs.

        These are placeholder wrappers that emit events via EventBus.
        The actual business logic (screening, calibration, review) listens
        for these events and runs independently.
        """
        # 08:30 — Pre-market calibration
        self.add_cron_job(
            "pre_market_calibrate",
            _emit_event_wrapper,
            hour=8,
            minute=30,
            day_of_week="mon-fri",
            name="盘前校准筛选",
            event_name="trading_day.pre_market.start",
        )

        # Post-market screening is triggered by trading_day state machine (15:00).
        # No duplicate cron needed here — _on_post_market_start handles it.

        logger.info("Scheduler: registered standard trading-day cron jobs")

    # ── Convenience ───────────────────────────────────────────────

    @property
    def is_started(self) -> bool:
        return self._started


async def _emit_event_wrapper(event_name: str, **kwargs: Any):
    """Thin wrapper: emit an event via EventBus. Used as scheduler callback."""
    from backend.event_bus import EventBus
    import datetime

    logger.info(f"Scheduler: firing cron job → event '{event_name}'")
    await EventBus.emit(
        event_name,
        timestamp=datetime.datetime.now().isoformat(),
        triggered_by="scheduler",
        **kwargs,
    )


def _job_to_dict(job: ApJob) -> dict:
    """Convert APScheduler Job to a plain dict for API responses."""
    return {
        "id": job.id,
        "name": job.name or job.id,
        "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        "trigger": str(job.trigger),
    }


# ── Singleton ─────────────────────────────────────────────────────

scheduler = Scheduler()

# AI Trading OS - Scheduler API
"""
Endpoints to view and manage scheduled jobs.

Usage:
    GET  /api/scheduler/jobs       — list all jobs
    GET  /api/scheduler/jobs/{id}  — get a specific job
    GET  /api/scheduler/status     — scheduler health + trading day phase
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.scheduler import scheduler
from backend.trading_day import trading_day

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])


@router.get("/status")
async def scheduler_status():
    """Get scheduler health + current trading day phase."""
    return {
        "status": "ok",
        "scheduler_started": scheduler.is_started,
        "trading_day_phase": trading_day.current_phase,
        "is_trading_day": trading_day.is_trading,
        "missed_pre_market": trading_day.missed_pre_market,
        "total_jobs": len(scheduler.list_jobs()),
    }


@router.get("/jobs")
async def list_jobs():
    """List all registered scheduled jobs."""
    jobs = scheduler.list_jobs()
    return {
        "status": "ok",
        "count": len(jobs),
        "jobs": jobs,
    }


@router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    """Get details for a specific job."""
    job = scheduler.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}")
    return {"status": "ok", "job": job}

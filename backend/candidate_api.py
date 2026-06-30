# AI Trading OS - Candidate Pool API
"""
Endpoints to view, trigger, and manage the pre-market candidate pool.

Usage:
    GET  /api/candidate-pool/current     — today's pool with all candidates
    GET  /api/candidate-pool/history     — historical pools by date
    POST /api/candidate-pool/screen      — manually trigger night screening
    POST /api/candidate-pool/calibrate   — manually trigger morning calibration
"""

from __future__ import annotations

import datetime
import logging

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from backend.database import async_session
from backend.models import StockPick, CandidatePool
from backend.screening import (
    run_night_screening,
    run_morning_calibration,
    get_candidate_pool,
)
from backend.task_manager import TaskManager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/candidate-pool", tags=["candidate-pool"])


@router.get("/current")
async def current_pool(date: str = None):
    """Get today's (or a specific date's) candidate pool.

    Query params:
        date: Optional ISO date string (YYYY-MM-DD). Defaults to today.
    """
    if date:
        try:
            trade_date = datetime.date.fromisoformat(date)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid date format: {date}")
    else:
        trade_date = None  # Let get_candidate_pool auto-detect the most recent

    data = await get_candidate_pool(trade_date)
    return {"status": "ok", "data": data}


@router.get("/history")
async def pool_history(limit: int = Query(default=10, le=30)):
    """Get recent candidate pool summaries."""
    async with async_session() as db:
        result = await db.execute(
            select(CandidatePool)
            .order_by(CandidatePool.create_time.desc())
            .limit(limit)
        )
        pools = result.scalars().all()

    return {
        "status": "ok",
        "count": len(pools),
        "pools": [
            {
                "pool_id": p.pool_id,
                "trade_date": p.trade_date.isoformat(),
                "stage": p.stage,
                "total_screened": p.total_screened,
                "total_qualified": p.total_qualified,
                "create_time": p.create_time.isoformat() if p.create_time else None,
            }
            for p in pools
        ],
    }


@router.post("/screen")
async def trigger_night_screen():
    """Manually trigger night screening (for testing / ad-hoc use).

    Normally runs automatically at 18:00 via the scheduler.
    """
    task_id = TaskManager.start(run_night_screening)
    return {
        "status": "ok",
        "task_id": task_id,
        "message": "夜盘初筛已启动，轮询 /api/market/analyze/{task_id} 获取结果",
    }


@router.post("/calibrate")
async def trigger_morning_calibration():
    """Manually trigger morning calibration (for testing / ad-hoc use).

    Normally runs automatically at 08:30 via the scheduler.
    """
    task_id = TaskManager.start(run_morning_calibration)
    return {
        "status": "ok",
        "task_id": task_id,
        "message": "盘前校准已启动",
    }

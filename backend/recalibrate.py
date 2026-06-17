# AI Trading OS - Mid-Session Recalibration
"""
Manual-trigger mid-session analysis: compares morning data vs pre-market expectations,
re-ranks the candidate pool, and adjusts entry prices.

Trigger: User clicks "盘中校准" button on Dashboard → POST /api/market/recalibrate
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy import select, desc

from backend.database import async_session
from backend.models import StockPick, CandidatePool, MarketSnapshot

logger = logging.getLogger(__name__)


async def run_recalibration() -> Dict[str, Any]:
    """Run the full mid-session recalibration pipeline.

    1. Delta analysis: morning data vs pre-market expectations
    2. Re-rank candidates based on morning performance
    3. Adjust entry prices and position recommendations

    Returns recalibration summary dict.
    """
    trade_date = datetime.date.today()
    now = datetime.datetime.now()
    start_time = now

    logger.info(f"Recalibrate: starting for {trade_date}")

    # ── 1. Collect data ──────────────────────────────────────────

    # Load today's candidates
    async with async_session() as db:
        result = await db.execute(
            select(StockPick).where(
                StockPick.trade_date == trade_date,
                StockPick.candidate_status.in_([
                    "morning_calibrated", "confirmed", "active"
                ]),
            ).order_by(StockPick.score.desc())
        )
        candidates = result.scalars().all()

        # Load morning snapshots (if polling was on)
        noon = datetime.datetime.combine(trade_date, datetime.time(12, 0))
        morning_start = datetime.datetime.combine(trade_date, datetime.time(9, 30))
        snap_result = await db.execute(
            select(MarketSnapshot).where(
                MarketSnapshot.trade_date == trade_date,
                MarketSnapshot.timestamp >= morning_start,
                MarketSnapshot.timestamp <= noon,
            ).order_by(MarketSnapshot.timestamp)
        )
        snapshots = snap_result.scalars().all()

    if not candidates:
        logger.info("Recalibrate: no active candidates to recalibrate")
        return {
            "status": "ok",
            "message": "无活跃候选需要校准",
            "candidates_before": 0,
            "candidates_after": 0,
            "emotion_shift": None,
            "recalibrated": [],
            "invalidated": [],
        }

    # ── 2. Delta analysis ────────────────────────────────────────

    # Market breadth trend
    breadth_trend = "stable"
    if len(snapshots) >= 3:
        first_count = snapshots[0].limit_up_count
        last_count = snapshots[-1].limit_up_count
        if last_count > first_count * 1.2:
            breadth_trend = "improving"
        elif last_count < first_count * 0.8:
            breadth_trend = "deteriorating"

    # Emotion check — re-run EmotionAgent
    emotion_shift = None
    try:
        from agents.emotion_agent import EmotionAgent
        agent = EmotionAgent()
        emotion_result = await agent.analyze()
        current_phase = emotion_result.get("phase_cn", "未知")
        current_confidence = emotion_result.get("confidence", 0)
        current_risk = emotion_result.get("risk_level", "unknown")
        current_position = emotion_result.get("suggested_position", "20%")
        emotion_shift = {
            "phase": current_phase,
            "confidence": current_confidence,
            "risk_level": current_risk,
            "suggested_position": current_position,
        }
    except Exception as e:
        logger.warning(f"Recalibrate: EmotionAgent failed: {e}")
        current_position = "20%"

    # ── 3. Re-rank candidates ────────────────────────────────────

    recalibrated = []
    invalidated = []

    for c in candidates:
        # Score adjustment based on morning conditions
        adjusted_score = c.morning_score if c.morning_score > 0 else c.night_score

        # Adjust for breadth trend
        if breadth_trend == "improving":
            adjusted_score = min(adjusted_score + 5, 100)
        elif breadth_trend == "deteriorating":
            adjusted_score = max(adjusted_score - 10, 0)

        # Adjust entry price — use current price if available
        adjusted_entry = c.buy_price

        if adjusted_score < 30:
            # Mark as invalidated
            c.candidate_status = "abandoned"
            c.reason = (c.reason or "") + f"; 盘中校准失效(得分降至{adjusted_score:.0f})"
            invalidated.append({
                "code": c.code,
                "name": c.name,
                "score_before": c.score,
                "score_after": adjusted_score,
                "reason": "得分过低，盘中淘汰",
            })
        else:
            c.candidate_status = "confirmed" if c.candidate_status != "active" else c.candidate_status
            c.score = adjusted_score
            c.buy_price = adjusted_entry
            recalibrated.append({
                "code": c.code,
                "name": c.name,
                "score_before": c.score if c.morning_score > 0 else c.night_score,
                "score_after": adjusted_score,
                "entry_price": adjusted_entry,
            })

    # Sort recalibrated by new score
    recalibrated.sort(key=lambda x: x["score_after"], reverse=True)

    # ── 4. Persist ───────────────────────────────────────────────

    async with async_session() as db:
        for c in candidates:
            db.add(c)
        await db.commit()

    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    logger.info(
        f"Recalibrate: done in {elapsed:.1f}s — "
        f"{len(recalibrated)} kept, {len(invalidated)} invalidated"
    )

    return {
        "status": "ok",
        "timestamp": now.isoformat(),
        "trade_date": trade_date.isoformat(),
        "snapshots_available": len(snapshots),
        "breadth_trend": breadth_trend,
        "emotion_shift": emotion_shift,
        "candidates_before": len(candidates),
        "candidates_after": len(recalibrated),
        "recalibrated": recalibrated[:10],     # Top 10
        "invalidated": invalidated,
        "elapsed_seconds": round(elapsed, 1),
    }

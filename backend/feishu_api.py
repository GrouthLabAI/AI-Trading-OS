# AI Trading OS - Feishu Sync API
"""
Endpoints to push AI analysis results to Feishu Bitable.

Usage:
    POST /api/feishu/sync-trade-plan    — Push latest AI picks to trade plan table
    POST /api/feishu/sync-review         — Push latest review to review table
    GET  /api/feishu/tables              — List available tables (helpful for setup)
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from backend.feishu import FeishuBitable, FeishuConfig
from backend.data_service import DataService
from agents.emotion_agent import EmotionAgent
from strategies.scoring import ScoringCenter

router = APIRouter(prefix="/api/feishu", tags=["feishu"])


@router.get("/tables")
async def list_tables():
    """List all tables in the configured Bitable (for debugging setup)."""
    if not FeishuConfig.APP_ID:
        raise HTTPException(status_code=400, detail="Feishu not configured. Set FEISHU_APP_ID in .env")

    try:
        fb = FeishuBitable()
        tables = await fb.list_tables()
        return {"status": "ok", "tables": tables}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-trade-plan")
async def sync_trade_plan():
    """
    Run full AI analysis and push picks to Feishu trade plan table.

    This runs the complete 5-agent pipeline and syncs results.
    """
    if not FeishuConfig.APP_ID:
        raise HTTPException(status_code=400, detail="Feishu not configured")
    if not FeishuConfig.TABLE_TRADE_PLAN:
        raise HTTPException(status_code=400, detail="TABLE_TRADE_PLAN not set in .env")

    try:
        # Run full analysis
        center = ScoringCenter()
        result = await center.run_full_analysis()

        picks = result.get("picks", [])
        if not picks:
            return {"status": "ok", "message": "No picks to sync", "count": 0}

        # Sync to Feishu
        fb = FeishuBitable()
        await fb.insert_trade_plan_batch(
            picks=picks,
            emotion_phase=result["emotion"]["phase"],
            main_theme=result["sector"]["main_theme"],
            risk_level=result["risk"]["risk_level"],
        )

        return {"status": "ok", "message": f"已同步 {len(picks)} 条交易计划到飞书表格", "count": len(picks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-review")
async def sync_review():
    """
    Run AI review and push to Feishu review table.
    """
    if not FeishuConfig.APP_ID:
        raise HTTPException(status_code=400, detail="Feishu not configured")
    if not FeishuConfig.TABLE_REVIEW:
        raise HTTPException(status_code=400, detail="TABLE_REVIEW not set in .env")

    try:
        # Import here to avoid circular
        from backend.reviews import generate_review_internal

        review_data = await generate_review_internal()

        fb = FeishuBitable()
        stats = review_data.get("stats", {})
        await fb.insert_review(
            win_rate=float(str(stats.get("win_rate", "0")).replace("%", "")),
            total_trades=stats.get("total", 0),
            wins=stats.get("wins", 0),
            losses=stats.get("losses", 0),
            total_profit=0.0,
            biggest_mistake=review_data.get("biggest_mistake", ""),
            strategy_review=review_data.get("strategy_review", ""),
            improvement_plan=review_data.get("improvement_plan", ""),
            suggestions="; ".join(review_data.get("suggestions", [])),
        )

        return {"status": "ok", "message": "复盘已同步到飞书表格"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

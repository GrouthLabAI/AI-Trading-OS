# AI Trading OS - Auto Review API
"""
Generates AI-powered trade review reports: daily, weekly, monthly.
Analyzes win-rate, strategy performance, and trading mistakes.

Usage:
    GET /api/reviews/summary    — quick stats
    GET /api/reviews/generate   — AI generates a full review
    GET /api/reviews/history    — past reviews
"""

from __future__ import annotations

import datetime
import json
import re

from fastapi import APIRouter, HTTPException
from sqlalchemy import select, func

from backend.database import async_session
from backend.llm_adapter import get_llm
from backend.models import TradeLog, ReviewLog

router = APIRouter(prefix="/api/reviews", tags=["reviews"])


# ── Quick Stats ─────────────────────────────────────────────────────

@router.get("/summary")
async def review_summary():
    """Get quick trade statistics for the dashboard."""
    async with async_session() as db:
        # Total trades
        total_result = await db.execute(select(func.count()).select_from(TradeLog))
        total = total_result.scalar() or 0

        # Wins / Losses (approximate: sell price > buy price = win)
        sells = await db.execute(
            select(TradeLog).where(TradeLog.action == "sell")
        )
        sells = sells.scalars().all()

        # Get corresponding buys to calculate P&L
        wins = 0
        losses = 0
        total_profit = 0.0
        strategies: dict[str, dict] = {}

        buy_map: dict[str, float] = {}
        buys = await db.execute(
            select(TradeLog).where(TradeLog.action == "buy").order_by(TradeLog.create_time)
        )
        for buy in buys.scalars().all():
            if buy.code not in buy_map:
                buy_map[buy.code] = buy.price

        for sell in sells:
            buy_price = buy_map.get(sell.code, sell.price)
            pnl = (sell.price - buy_price) * sell.quantity
            total_profit += pnl
            if pnl > 0:
                wins += 1
            else:
                losses += 1

            # Strategy tracking (from reason field)
            reason = sell.reason or "未分类"
            if reason not in strategies:
                strategies[reason] = {"total": 0, "wins": 0}
            strategies[reason]["total"] += 1
            if pnl > 0:
                strategies[reason]["wins"] += 1

        completed = wins + losses
        win_rate = round(wins / max(completed, 1) * 100, 1)

        strategy_stats = [
            {
                "name": name,
                "total": s["total"],
                "wins": s["wins"],
                "win_rate": round(s["wins"] / max(s["total"], 1) * 100, 1),
            }
            for name, s in strategies.items()
        ]

        return {
            "status": "ok",
            "data": {
                "total_trades": total,
                "completed_trades": completed,
                "wins": wins,
                "losses": losses,
                "win_rate": win_rate,
                "total_profit": round(total_profit, 2),
                "strategies": sorted(strategy_stats, key=lambda x: x["win_rate"], reverse=True),
            },
        }


# ── AI Review Generation ────────────────────────────────────────────

async def generate_review_internal() -> dict:
    """Core logic: analyze trades and generate review. Reusable by other modules."""
    async with async_session() as db:
        cutoff = datetime.datetime.now() - datetime.timedelta(days=30)
        result = await db.execute(
            select(TradeLog)
            .where(TradeLog.create_time >= cutoff)
            .order_by(TradeLog.create_time.desc())
            .limit(50)
        )
        trades = result.scalars().all()

    if not trades:
        return {"stats": {}, "biggest_mistake": "暂无交易记录", "suggestions": [],
                "strategy_review": "", "improvement_plan": ""}

    trade_text = "\n".join(
        f"- {t.create_time.strftime('%m-%d %H:%M')} {t.action} {t.code} "
        f"价格:{t.price} 数量:{t.quantity} 原因:{t.reason or '未知'}"
        for t in trades
    )

    prompt = f"""你是交易复盘分析师。分析以下交易记录，生成复盘报告。

交易记录（最近30天）：
{trade_text}

请分析：
1. 交易统计（胜率、盈亏）
2. 最大问题（错在哪里）
3. 改进建议
4. 策略评价

JSON格式输出：
{{"stats": {{"total": 总数, "wins": 盈利次数, "losses": 亏损次数, "win_rate": "胜率%"}},
"biggest_mistake": "最大问题（15字）",
"suggestions": ["建议1", "建议2"],
"strategy_review": "策略评价（30字）",
"improvement_plan": "改进计划（30字）"}}
"""
    llm = get_llm()
    raw = await llm.chat([{"role": "user", "content": prompt}])

    match = re.search(r"\{[\s\S]*\}", raw)
    try:
        ai_result = json.loads(match.group()) if match else {}
    except json.JSONDecodeError:
        ai_result = {}

    # Save to review_logs
    async with async_session() as db:
        review = ReviewLog(
            trade_date=datetime.date.today(),
            win_rate=float(str(ai_result.get("stats", {}).get("win_rate", "0")).replace("%", "")),
            profit=0.0,
            loss=0.0,
            summary=json.dumps(ai_result, ensure_ascii=False),
            mistakes=ai_result.get("biggest_mistake", ""),
            suggestions="; ".join(ai_result.get("suggestions", [])),
        )
        db.add(review)
        await db.commit()

    return ai_result


@router.get("/generate")
async def generate_review():
    """AI generates a review report from recent trade history."""
    ai_result = await generate_review_internal()
    return {"status": "ok", "data": ai_result}


# ── Review History ──────────────────────────────────────────────────

@router.get("/history")
async def review_history():
    """Get past generated reviews."""
    async with async_session() as db:
        result = await db.execute(
            select(ReviewLog).order_by(ReviewLog.trade_date.desc()).limit(30)
        )
        reviews = result.scalars().all()
        return {
            "status": "ok",
            "data": [
                {
                    "id": r.id,
                    "date": r.trade_date.isoformat(),
                    "win_rate": r.win_rate,
                    "profit": r.profit,
                    "loss": r.loss,
                    "mistakes": r.mistakes,
                    "suggestions": r.suggestions,
                }
                for r in reviews
            ],
        }

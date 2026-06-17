# AI Trading OS - Position Management API
from __future__ import annotations

import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, update

from backend.database import async_session
from backend.llm_adapter import get_llm
from backend.models import Position, TradeLog

router = APIRouter(prefix="/api/positions", tags=["positions"])


class PositionCreate(BaseModel):
    code: str
    name: str
    buy_price: float
    quantity: int = 100
    reason: str = ""


class PositionUpdate(BaseModel):
    current_price: Optional[float] = None
    status: Optional[str] = None


# ── CRUD ────────────────────────────────────────────────────────────

@router.get("/")
async def list_positions():
    """Get all positions (open + closed)."""
    async with async_session() as db:
        result = await db.execute(
            select(Position).order_by(Position.buy_time.desc())
        )
        positions = result.scalars().all()
        return {
            "status": "ok",
            "data": [
                {
                    "id": p.id,
                    "code": p.code,
                    "name": p.name,
                    "buy_price": p.buy_price,
                    "current_price": p.current_price,
                    "quantity": p.quantity,
                    "profit": round(p.profit, 2),
                    "profit_rate": round(p.profit_rate, 4),
                    "status": p.status,
                    "buy_time": p.buy_time.isoformat() if p.buy_time else None,
                    "sell_time": p.sell_time.isoformat() if p.sell_time else None,
                }
                for p in positions
            ],
        }


@router.post("/")
async def create_position(req: PositionCreate):
    """Open a new position."""
    async with async_session() as db:
        pos = Position(
            code=req.code,
            name=req.name,
            buy_price=req.buy_price,
            current_price=req.buy_price,
            quantity=req.quantity,
            profit=0.0,
            profit_rate=0.0,
            status="holding",
            buy_time=datetime.datetime.now(),
        )
        db.add(pos)

        # Log the trade
        log = TradeLog(
            code=req.code,
            action="buy",
            price=req.buy_price,
            quantity=req.quantity,
            reason=req.reason,
            agent_decision="manual",
            execute_result="success",
        )
        db.add(log)
        await db.commit()
        return {"status": "ok", "data": {"id": pos.id, "message": f"买入 {req.name} 成功"}}


@router.put("/{position_id}")
async def update_position(position_id: int, req: PositionUpdate):
    """Update current price, P&L, or close position."""
    async with async_session() as db:
        pos = await db.get(Position, position_id)
        if not pos:
            raise HTTPException(status_code=404, detail="持仓不存在")

        if req.current_price is not None:
            pos.current_price = req.current_price
            # Calculate P&L
            if pos.buy_price > 0:
                pos.profit = (pos.current_price - pos.buy_price) * pos.quantity
                pos.profit_rate = (pos.current_price - pos.buy_price) / pos.buy_price

        if req.status == "closed":
            pos.status = "closed"
            pos.sell_time = datetime.datetime.now()

            # Log the sell
            log = TradeLog(
                code=pos.code,
                action="sell",
                price=pos.current_price,
                quantity=pos.quantity,
                reason="手动平仓",
                execute_result="success",
            )
            db.add(log)

        await db.commit()
        return {"status": "ok", "data": {"id": pos.id, "message": "更新成功"}}


# ── AI Position Analysis ────────────────────────────────────────────

@router.get("/analyze")
async def analyze_positions():
    """AI analyzes all open positions and gives hold/sell advice."""
    async with async_session() as db:
        result = await db.execute(
            select(Position).where(Position.status == "holding")
        )
        positions = result.scalars().all()

    if not positions:
        return {"status": "ok", "data": {"positions": [], "summary": "当前无持仓"}}

    # Format positions for LLM
    pos_text = "\n".join(
        f"- {p.name}({p.code}) 成本:{p.buy_price} 现价:{p.current_price} "
        f"盈亏:{p.profit_rate*100:.1f}% 数量:{p.quantity}股"
        for p in positions
    )

    prompt = f"""你是一位持仓管理专家。分析以下持仓并给出建议。

持仓列表：
{pos_text}

请对每只持仓给出：继续持有/建议减仓/建议止盈/建议清仓，并说明理由。

JSON格式输出：
{{"analysis": [{{"code": "股票代码", "action": "hold|reduce|profit|sell", "reason": "理由"}}], "summary": "整体建议"}}
"""
    llm = get_llm()
    raw = await llm.chat([{"role": "user", "content": prompt}])

    import re, json
    match = re.search(r"\{[\s\S]*\}", raw)
    try:
        ai_result = json.loads(match.group()) if match else {"analysis": [], "summary": raw}
    except json.JSONDecodeError:
        ai_result = {"analysis": [], "summary": raw}

    return {
        "status": "ok",
        "data": {
            "positions": [
                {
                    "id": p.id, "code": p.code, "name": p.name,
                    "buy_price": p.buy_price, "current_price": p.current_price,
                    "profit_rate": round(p.profit_rate * 100, 2),
                    "profit": round(p.profit, 2),
                }
                for p in positions
            ],
            "ai_analysis": ai_result.get("analysis", []),
            "summary": ai_result.get("summary", ""),
        },
    }

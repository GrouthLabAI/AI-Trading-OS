# AI Trading OS - Execution API
"""
Triggers trade execution (RPA or mock) and records results.

Endpoints:
    POST /api/execute/buy   — Execute a buy order
    POST /api/execute/sell  — Execute a sell order
"""

from __future__ import annotations

import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.database import async_session
from backend.models import Position, TradeLog
from execution.trade_executor import get_executor

router = APIRouter(prefix="/api/execute", tags=["execution"])


class ExecuteOrder(BaseModel):
    code: str
    name: str
    price: float
    quantity: int = 100
    reason: str = ""
    add_to_positions: bool = True  # auto-add to positions table


@router.post("/buy")
async def execute_buy(order: ExecuteOrder):
    """Execute a buy order and record to trade_log + positions."""
    executor = get_executor()
    result = executor.buy(order.code, order.name, order.price, order.quantity)

    # Always log the trade
    async with async_session() as db:
        log = TradeLog(
            code=order.code,
            action="buy",
            price=order.price,
            quantity=order.quantity,
            reason=order.reason,
            agent_decision="ai_recommendation",
            execute_result="success" if result.success else "failed",
        )
        db.add(log)

        # Add to positions if successful
        if result.success and order.add_to_positions:
            pos = Position(
                code=order.code,
                name=order.name,
                buy_price=order.price,
                current_price=order.price,
                quantity=order.quantity,
                profit=0.0,
                profit_rate=0.0,
                status="holding",
                buy_time=datetime.datetime.now(),
            )
            db.add(pos)

        await db.commit()

    return {
        "status": "ok" if result.success else "error",
        "data": {
            "order_id": result.order_id,
            "message": result.message,
            "action": "buy",
            "code": order.code,
            "name": order.name,
            "price": order.price,
            "quantity": order.quantity,
        },
    }


@router.post("/sell")
async def execute_sell(order: ExecuteOrder):
    """Execute a sell order and record to trade_log."""
    executor = get_executor()
    result = executor.sell(order.code, order.name, order.price, order.quantity)

    async with async_session() as db:
        log = TradeLog(
            code=order.code,
            action="sell",
            price=order.price,
            quantity=order.quantity,
            reason=order.reason,
            agent_decision="manual_sell",
            execute_result="success" if result.success else "failed",
        )
        db.add(log)

        # Mark position as closed if successful
        if result.success:
            from sqlalchemy import update
            await db.execute(
                update(Position)
                .where(Position.code == order.code, Position.status == "holding")
                .values(status="closed", sell_time=datetime.datetime.now(),
                        current_price=order.price)
            )

        await db.commit()

    return {
        "status": "ok" if result.success else "error",
        "data": {
            "order_id": result.order_id,
            "message": result.message,
            "action": "sell",
            "code": order.code,
            "name": order.name,
            "price": order.price,
            "quantity": order.quantity,
        },
    }

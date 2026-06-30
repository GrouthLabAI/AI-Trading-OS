# AI Trading OS - Chat history persistence API
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select, delete, func

from backend.database import async_session
from backend.models import ChatMessage

router = APIRouter(prefix="/api/chat", tags=["chat-history"])


# ── Request schemas ─────────────────────────────────────────────

class SaveMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class SaveRequest(BaseModel):
    stock_code: str
    messages: list[SaveMessage]


# ── GET /api/chat/history/{stock_code} ───────────────────────────

@router.get("/history/{stock_code}")
async def get_history(
    stock_code: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """分页获取某股票的历史对话记录（按时间正序）"""
    offset = (page - 1) * page_size
    async with async_session() as db:
        # 查询总数
        total_result = await db.execute(
            select(func.count(ChatMessage.id)).where(ChatMessage.stock_code == stock_code)
        )
        total = total_result.scalar() or 0

        # 分页查询消息（按 create_time 正序）
        result = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.stock_code == stock_code)
            .order_by(ChatMessage.create_time.asc())
            .offset(offset)
            .limit(page_size)
        )
        rows = result.scalars().all()

    messages = [
        {"role": r.role, "content": r.content, "create_time": r.create_time.isoformat()}
        for r in rows
    ]

    return {
        "status": "ok",
        "data": {
            "messages": messages,
            "total": total,
            "page": page,
            "page_size": page_size,
            "has_more": offset + page_size < total,
        },
    }


# ── POST /api/chat/save ──────────────────────────────────────────

@router.post("/save")
async def save_messages(req: SaveRequest):
    """批量保存对话消息（用户消息 + AI 回复成对保存）"""
    stock_code = req.stock_code.strip()
    if not stock_code or not req.messages:
        return {"status": "error", "message": "stock_code 和 messages 不能为空"}

    async with async_session() as db:
        for m in req.messages:
            if not m.content.strip():
                continue
            record = ChatMessage(
                stock_code=stock_code,
                role=m.role,
                content=m.content,
            )
            db.add(record)
        await db.commit()

    return {"status": "ok", "data": {"saved": len(req.messages)}}


# ── DELETE /api/chat/clear/{stock_code} ──────────────────────────

@router.delete("/clear/{stock_code}")
async def clear_history(stock_code: str):
    """清空某股票的全部对话记录"""
    async with async_session() as db:
        result = await db.execute(
            delete(ChatMessage).where(ChatMessage.stock_code == stock_code)
        )
        await db.commit()
        deleted = result.rowcount

    return {"status": "ok", "data": {"deleted": deleted}}

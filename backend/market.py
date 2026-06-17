# AI Trading OS - Market API
import asyncio
import json
import datetime

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from backend.data_service import DataService
from backend.task_manager import TaskManager
from agents.emotion_agent import EmotionAgent
from strategies.scoring import ScoringCenter

router = APIRouter(prefix="/api/market", tags=["market"])


# ── Market summary ──────────────────────────────────────────────────

@router.get("/summary")
async def market_summary():
    """Get current market overview: breadth, sectors, limit-ups."""
    try:
        data = await DataService.get_market_summary()
        return {"status": "ok", "data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Market emotion analysis ─────────────────────────────────────────

@router.get("/emotion")
async def market_emotion():
    """Run the EmotionAgent to assess current market sentiment phase."""
    try:
        agent = EmotionAgent()
        result = await agent.analyze()
        return {"status": "ok", "data": result}
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Prompt file missing: {e}")
    except ValueError as e:
        raise HTTPException(status_code=500, detail=f"LLM config error: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Sector ranking ──────────────────────────────────────────────────

@router.get("/sectors")
async def sector_ranking():
    """Get concept sector rankings (top + bottom 5)."""
    try:
        sectors = await DataService.fetch_sector_ranking()
        return {
            "status": "ok",
            "data": {
                "top": sectors[:5],
                "bottom": sectors[-5:] if len(sectors) >= 5 else [],
                "all": sectors,
            },
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Limit-up pool ───────────────────────────────────────────────────

@router.get("/limit-ups")
async def limit_up_pool():
    """Get today's limit-up stocks."""
    try:
        stocks = await DataService.fetch_limit_up_pool()
        return {"status": "ok", "data": stocks}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Full analysis (async — returns task ID, check status separately) ─

@router.get("/analyze")
async def full_analysis():
    """Start the complete agent pipeline in background. Returns task_id immediately.

    Poll GET /api/market/analyze/{task_id} to check status and get results.
    """
    try:
        async def _run():
            center = ScoringCenter()
            return await center.run_full_analysis()

        task_id = TaskManager.start(_run)
        return {"status": "ok", "task_id": task_id, "message": "分析已启动，轮询 /api/market/analyze/{task_id} 获取结果"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/analyze/{task_id}")
async def get_analysis_result(task_id: str):
    """Check the status of a background analysis task."""
    task = TaskManager.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")

    if task["status"] == "running":
        return {"status": "running", "data": None}
    elif task["status"] == "error":
        return {"status": "error", "data": None, "detail": task.get("error", "Unknown error")}
    else:
        return {"status": "ok", "data": task["result"]}


# ── SSE Market Stream ─────────────────────────────────────────────

@router.get("/stream")
async def market_stream():
    """SSE endpoint: pushes market snapshots every ~30s during trading hours.

    Frontend subscribes with EventSource. Each event is a JSON snapshot.
    Stream ends when polling stops or connection closes.
    """
    from backend.polling import polling_engine, get_sse_queue

    async def event_generator():
        queue = get_sse_queue()
        # Send initial heartbeat
        yield f"data: {json.dumps({'type': 'connected', 'polling': polling_engine.is_running, 'timestamp': datetime.datetime.now().isoformat()}, ensure_ascii=False)}\n\n"

        while True:
            try:
                # Wait for next snapshot with timeout (allow checking if client disconnected)
                snapshot = await asyncio.wait_for(queue.get(), timeout=35.0)
                yield f"data: {json.dumps({'type': 'snapshot', **snapshot}, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive
                yield f"data: {json.dumps({'type': 'heartbeat', 'polling': polling_engine.is_running, 'timestamp': datetime.datetime.now().isoformat()}, ensure_ascii=False)}\n\n"
            except asyncio.CancelledError:
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── Polling Control ───────────────────────────────────────────────

@router.post("/polling/start")
async def start_polling():
    """Start the market polling engine."""
    from backend.polling import polling_engine

    if polling_engine.is_running:
        return {"status": "ok", "message": "轮询已在运行中"}

    await polling_engine.start()
    return {"status": "ok", "message": "轮询已启动", "timestamp": datetime.datetime.now().isoformat()}


@router.post("/polling/stop")
async def stop_polling():
    """Stop the market polling engine."""
    from backend.polling import polling_engine

    if not polling_engine.is_running:
        return {"status": "ok", "message": "轮询未在运行"}

    await polling_engine.stop()
    return {"status": "ok", "message": "轮询已停止", "timestamp": datetime.datetime.now().isoformat()}


@router.get("/polling/status")
async def polling_status():
    """Get current polling engine status."""
    from backend.polling import polling_engine

    return {
        "status": "ok",
        "polling": polling_engine.is_running,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ── Mid-Session Recalibration ─────────────────────────────────────

@router.post("/recalibrate")
async def trigger_recalibration():
    """Manually trigger mid-session recalibration.

    Runs delta analysis: morning data vs pre-market expectations,
    re-ranks candidates, and returns updated recommendations.
    """
    try:
        result = await _run_recalibration_task()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _run_recalibration_task():
    """Internal: run recalibration and return structured result."""
    from backend.recalibrate import run_recalibration
    from backend.task_manager import TaskManager

    task_id = TaskManager.start(run_recalibration)
    # Wait a reasonable time for the result
    import asyncio
    for _ in range(30):  # Up to 30s
        await asyncio.sleep(1)
        task = TaskManager.get(task_id)
        if task and task["status"] == "done":
            return {"status": "ok", "data": task["result"]}
        elif task and task["status"] == "error":
            return {"status": "error", "detail": task.get("error", "Unknown error")}

    return {"status": "running", "task_id": task_id, "message": "校准进行中，请轮询结果"}

# AI Trading OS - FastAPI Application Entry Point
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings
from backend.database import init_db
from backend.vector_store import init_vector_db
from backend.chat import router as chat_router
from backend.market import router as market_router
from backend.positions import router as positions_router
from backend.reviews import router as reviews_router
from backend.execution_api import router as execution_router
from backend.feishu_api import router as feishu_router
from backend.backtest_api import router as backtest_router
from backend.scheduler_api import router as scheduler_router
from backend.candidate_api import router as candidate_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # Startup: create database tables & initialize vector DB
    await init_db()
    init_vector_db()

    # Start the persistent scheduler
    from backend.scheduler import scheduler
    await scheduler.start()
    scheduler.register_trading_day_jobs()

    # Start the trading day state machine
    from backend.trading_day import trading_day
    await trading_day.start()

    # Register event handlers (wires screening pipeline to scheduler events)
    from backend.event_handlers import register_all_handlers
    register_all_handlers()

    print(f"✓ LLM provider: {settings.llm_provider}")
    print(f"✓ Scheduler: started")
    print(f"✓ Trading day phase: {trading_day.current_phase}")
    print(f"✓ Event handlers: registered")

    yield

    # Shutdown
    from backend.trading_day import trading_day as td
    from backend.scheduler import scheduler as sch
    await td.stop()
    await sch.stop()
    print("✓ Scheduler and trading day monitor stopped")


app = FastAPI(
    title="AI Trading OS",
    description="Personal AI trading operating system — API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow Next.js dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(chat_router)
app.include_router(market_router)
app.include_router(positions_router)
app.include_router(reviews_router)
app.include_router(execution_router)
app.include_router(feishu_router)
app.include_router(backtest_router)
app.include_router(scheduler_router)
app.include_router(candidate_router)


# Health check
@app.get("/api/health")
async def health():
    from backend.trading_day import trading_day as td
    from backend.scheduler import scheduler as sch
    return {
        "status": "ok",
        "version": "0.1.0",
        "llm_provider": settings.llm_provider,
        "trading_day": {
            "phase": td.current_phase,
            "is_trading": td.is_trading,
            "missed_pre_market": td.missed_pre_market,
        },
        "scheduler": {
            "started": sch.is_started,
            "jobs": len(sch.list_jobs()),
        },
    }

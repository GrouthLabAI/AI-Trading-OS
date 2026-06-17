# AI Trading OS - Event Handlers
"""
Registers handlers for all trading-day and scheduler events.
This file is imported once at startup to wire up the connections.

Each handler is a lightweight bridge: it receives an event and delegates
to the appropriate business logic module.
"""

from __future__ import annotations

import logging

from backend.event_bus import EventBus, Event

logger = logging.getLogger(__name__)


# ── Pre-market: morning calibration ───────────────────────────────

async def _on_pre_market_start(**data):
    """Handle pre_market.start event: run morning calibration screening."""
    logger.info(f"EventHandler: pre_market.start → running morning calibration")
    try:
        from backend.screening import run_morning_calibration
        result = await run_morning_calibration()
        logger.info(f"EventHandler: morning calibration done — {result}")
    except Exception:
        logger.exception("EventHandler: morning calibration failed")


# ── Post-market: night screening + review ─────────────────────────

async def _on_post_market_start(**data):
    """Handle post_market.start event: run night screening for next trading day."""
    logger.info(f"EventHandler: post_market.start → running night screening")
    try:
        from backend.screening import run_night_screening
        result = await run_night_screening()
        logger.info(f"EventHandler: night screening done — {result}")

        # Emit candidate pool updated event
        if result.get("total_qualified", 0) > 0:
            await EventBus.emit(
                Event.CANDIDATE_POOL_UPDATED,
                pool_id=result.get("pool_id", ""),
                total_qualified=result.get("total_qualified", 0),
            )
    except Exception:
        logger.exception("EventHandler: night screening failed")


# ── Candidate pool updated → notification ─────────────────────────

async def _on_candidate_pool_updated(**data):
    """Handle candidate_pool.updated: send notifications."""
    pool_id = data.get("pool_id", "")
    count = data.get("total_qualified", 0)
    logger.info(f"EventHandler: candidate pool updated — pool={pool_id}, {count} candidates")

    # Send Feishu notification (if configured)
    try:
        from backend.notify import Notifier
        notifier = Notifier()
        notifier.send_text(f"📊 候选池已更新\n今日初筛通过: {count} 只\n批次: {pool_id}")
    except Exception:
        logger.debug("EventHandler: Feishu notification skipped (not configured or failed)")


# ── Register all handlers ─────────────────────────────────────────

def register_all_handlers():
    """Register all event handlers. Called from FastAPI lifespan."""

    # Trading day events → screening pipeline
    EventBus.on(Event.PRE_MARKET_START, _on_pre_market_start)
    EventBus.on(Event.POST_MARKET_START, _on_post_market_start)

    # Candidate pool events → notifications
    EventBus.on(Event.CANDIDATE_POOL_UPDATED, _on_candidate_pool_updated)

    logger.info(
        f"EventHandlers: registered {EventBus.listener_count()} listeners "
        f"across {len(EventBus.list_events())} events"
    )

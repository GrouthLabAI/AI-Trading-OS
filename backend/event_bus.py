# AI Trading OS - Event Bus
"""
In-process pub/sub event system. Python 3.9 compatible — no match/case.

Components register callbacks for events; the bus dispatches them when fired.
Decouples the scheduler, state machine, polling engine, and alert handlers.

Usage:
    from backend.event_bus import EventBus

    async def on_pre_market(**data):
        print(f"Pre-market started at {data['timestamp']}")

    EventBus.on("trading_day.pre_market.start", on_pre_market)
    await EventBus.emit("trading_day.pre_market.start", timestamp="08:00")
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, List

logger = logging.getLogger(__name__)

# Type: async callback receiving **data
Callback = Callable[..., Coroutine[Any, Any, None]]


class EventBus:
    """Simple in-process async event bus."""

    _listeners: dict[str, List[Callback]] = {}

    @classmethod
    def on(cls, event: str, callback: Callback) -> None:
        """Register an async callback for an event.

        Usage:
            EventBus.on("market.alert", my_alert_handler)
        """
        if event not in cls._listeners:
            cls._listeners[event] = []
        cls._listeners[event].append(callback)
        logger.debug(f"EventBus: registered listener for '{event}' (total: {len(cls._listeners[event])})")

    @classmethod
    def off(cls, event: str, callback: Callback) -> None:
        """Remove a specific callback from an event."""
        if event in cls._listeners and callback in cls._listeners[event]:
            cls._listeners[event].remove(callback)

    @classmethod
    def clear(cls, event: str = None) -> None:
        """Remove all listeners. If event is None, clears everything."""
        if event:
            cls._listeners.pop(event, None)
        else:
            cls._listeners.clear()

    @classmethod
    async def emit(cls, event: str, **data: Any) -> None:
        """Fire all callbacks registered for an event.

        Callbacks run concurrently (gathered). Exceptions in one callback
        do not prevent others from running.

        Usage:
            await EventBus.emit("trading_day.pre_market.start", timestamp="08:00")
        """
        callbacks = cls._listeners.get(event, [])
        if not callbacks:
            return

        logger.info(f"EventBus: emitting '{event}' to {len(callbacks)} listener(s)")
        tasks = []
        for cb in callbacks:
            tasks.append(_safe_invoke(cb, event, **data))

        await asyncio.gather(*tasks, return_exceptions=True)

    @classmethod
    def listener_count(cls, event: str = None) -> int:
        """Return the number of registered listeners. If event is None, return total."""
        if event:
            return len(cls._listeners.get(event, []))
        return sum(len(v) for v in cls._listeners.values())

    @classmethod
    def list_events(cls) -> List[str]:
        """Return all registered event names."""
        return list(cls._listeners.keys())


async def _safe_invoke(callback: Callback, event: str, **data: Any) -> None:
    """Invoke a callback, logging but not raising exceptions."""
    try:
        await callback(**data)
    except Exception:
        logger.exception(f"EventBus: callback for '{event}' raised an exception")


# ── Pre-defined event name constants ──────────────────────────────

class Event:
    """Event name constants. Use these instead of raw strings."""

    # Trading day phase transitions
    PRE_MARKET_START = "trading_day.pre_market.start"
    MORNING_SESSION_START = "trading_day.morning_session.start"
    LUNCH_BREAK_START = "trading_day.lunch_break.start"
    AFTERNOON_SESSION_START = "trading_day.afternoon_session.start"
    POST_MARKET_START = "trading_day.post_market.start"
    TRADING_DAY_END = "trading_day.end"

    # Market alerts
    MARKET_ALERT = "market.alert"
    SENTIMENT_SHIFT = "market.sentiment_shift"

    # Risk events
    RISK_CIRCUIT_BREAKER = "risk.circuit_breaker"

    # Candidate pool events
    CANDIDATE_POOL_UPDATED = "candidate_pool.updated"
    CANDIDATE_EXECUTED = "candidate.executed"
    CANDIDATE_EXPIRED = "candidate.expired"

    # Review events
    REVIEW_COMPLETED = "review.completed"

# AI Trading OS - Trading Day State Machine
"""
Tracks the current phase of an A-share trading day and emits events on transitions.

State flow (Beijing time, Mon-Fri):
    IDLE → PRE_MARKET(08:00-09:25) → MORNING_SESSION(09:25-11:30)
         → LUNCH_BREAK(11:30-13:00) → AFTERNOON_SESSION(13:00-15:00)
         → POST_MARKET(15:00-18:00) → IDLE

Uses AKShare's trade calendar to skip weekends and holidays.
Emits events via EventBus on every phase transition so other modules
(scheduler, polling, alerts) can react.

Usage:
    from backend.trading_day import TradingDayState, trading_day

    phase = trading_day.current_phase  # "morning_session"
    is_trading = trading_day.is_trading_day()  # True/False

    # React to transitions elsewhere:
    EventBus.on(Event.MORNING_SESSION_START, my_handler)
"""

from __future__ import annotations

import asyncio
import datetime
import logging
from enum import Enum
from typing import Optional

from backend.event_bus import EventBus, Event

logger = logging.getLogger(__name__)


class TradingPhase(str, Enum):
    IDLE = "idle"
    PRE_MARKET = "pre_market"
    MORNING_SESSION = "morning_session"
    LUNCH_BREAK = "lunch_break"
    AFTERNOON_SESSION = "afternoon_session"
    POST_MARKET = "post_market"


# ── Phase time windows (Beijing time, UTC+8) ─────────────────────

PHASE_SCHEDULE = [
    # (phase, start_hour, start_min, event_to_emit)
    (TradingPhase.PRE_MARKET, 8, 0, Event.PRE_MARKET_START),
    (TradingPhase.MORNING_SESSION, 9, 25, Event.MORNING_SESSION_START),
    (TradingPhase.LUNCH_BREAK, 11, 30, Event.LUNCH_BREAK_START),
    (TradingPhase.AFTERNOON_SESSION, 13, 0, Event.AFTERNOON_SESSION_START),
    (TradingPhase.POST_MARKET, 15, 0, Event.POST_MARKET_START),
]


def _get_phase_for_time(now: datetime.datetime) -> TradingPhase:
    """Determine which trading phase the given time falls into."""
    t = now.time()

    # Define phase boundaries as (start, end, phase)
    boundaries = [
        (datetime.time(8, 0), datetime.time(9, 25), TradingPhase.PRE_MARKET),
        (datetime.time(9, 25), datetime.time(11, 30), TradingPhase.MORNING_SESSION),
        (datetime.time(11, 30), datetime.time(13, 0), TradingPhase.LUNCH_BREAK),
        (datetime.time(13, 0), datetime.time(15, 0), TradingPhase.AFTERNOON_SESSION),
        (datetime.time(15, 0), datetime.time(18, 0), TradingPhase.POST_MARKET),
    ]

    for start, end, phase in boundaries:
        if start <= t < end:
            return phase

    return TradingPhase.IDLE


class TradingDayState:
    """Singleton that tracks the current trading day phase.

    Runs a background task that polls every 30 seconds, detects phase
    changes, and emits the appropriate events.
    """

    def __init__(self):
        self._current_phase: TradingPhase = TradingPhase.IDLE
        self._is_trading_day: bool = False
        self._today: Optional[datetime.date] = None
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._missed_pre_market: bool = False

    # ── Public properties ─────────────────────────────────────────

    @property
    def current_phase(self) -> str:
        """Current trading phase as a string. E.g. 'morning_session'."""
        return self._current_phase.value

    @property
    def phase(self) -> TradingPhase:
        """Current trading phase enum."""
        return self._current_phase

    @property
    def is_trading(self) -> bool:
        """True if today is a trading day AND we're in an active phase."""
        return self._is_trading_day and self._current_phase != TradingPhase.IDLE

    @property
    def missed_pre_market(self) -> bool:
        """True if the system started after pre-market had already passed."""
        return self._missed_pre_market

    # ── Trading calendar ──────────────────────────────────────────

    async def _check_trading_day(self) -> bool:
        """Check if today is an A-share trading day using AKShare calendar."""
        today = datetime.date.today()

        # Cache: only check once per day
        if self._today == today:
            return self._is_trading_day

        self._today = today

        # Weekend check (fast path)
        if today.weekday() >= 5:  # Saturday=5, Sunday=6
            self._is_trading_day = False
            logger.info(f"TradingDay: {today} is a weekend — IDLE")
            return False

        # AKShare calendar check
        try:
            import akshare as ak
            trade_df = ak.tool_trade_date_hist_sina()
            trade_dates = set(
                datetime.datetime.strptime(str(d), "%Y%m%d").date()
                for d in trade_df["trade_date"].values
            )
            self._is_trading_day = today in trade_dates
            if not self._is_trading_day:
                logger.info(f"TradingDay: {today} is a holiday — IDLE")
        except Exception:
            # If AKShare fails, assume it IS a trading day (fail open)
            logger.warning("TradingDay: AKShare calendar check failed, assuming trading day")
            self._is_trading_day = True

        return self._is_trading_day

    # ── Phase detection ───────────────────────────────────────────

    def _detect_phase(self) -> TradingPhase:
        """Detect the current phase based on system time."""
        now = datetime.datetime.now()
        if not self._is_trading_day:
            return TradingPhase.IDLE
        return _get_phase_for_time(now)

    # ── Background monitoring loop ────────────────────────────────

    async def _monitor_loop(self):
        """Poll every 30s, detect phase changes, emit events."""
        logger.info("TradingDay: monitor loop started")
        self._running = True

        while self._running:
            try:
                is_trading = await self._check_trading_day()
                if not is_trading:
                    # Not a trading day — stay IDLE, check again in 10 minutes
                    if self._current_phase != TradingPhase.IDLE:
                        await self._transition_to(TradingPhase.IDLE)
                    await asyncio.sleep(600)
                    continue

                # Trading day: detect current phase
                new_phase = self._detect_phase()
                if new_phase != self._current_phase:
                    await self._transition_to(new_phase)

                await asyncio.sleep(30)

            except asyncio.CancelledError:
                logger.info("TradingDay: monitor loop cancelled")
                break
            except Exception:
                logger.exception("TradingDay: error in monitor loop")
                await asyncio.sleep(30)

    async def _transition_to(self, new_phase: TradingPhase):
        """Transition to a new phase and emit the corresponding event."""
        old_phase = self._current_phase
        self._current_phase = new_phase

        logger.info(f"TradingDay: {old_phase.value} → {new_phase.value}")

        # Determine event to emit
        for phase, hour, minute, event_name in PHASE_SCHEDULE:
            if phase == new_phase:
                now = datetime.datetime.now()
                await EventBus.emit(
                    event_name,
                    timestamp=now.isoformat(),
                    previous_phase=old_phase.value,
                    current_phase=new_phase.value,
                    is_trading_day=self._is_trading_day,
                )
                break

        # Special: entering POST_MARKET triggers end-of-day flow
        if new_phase == TradingPhase.POST_MARKET:
            now = datetime.datetime.now()
            await EventBus.emit(
                Event.TRADING_DAY_END,
                timestamp=now.isoformat(),
            )

    # ── Lifecycle ─────────────────────────────────────────────────

    async def start(self):
        """Start the trading day monitor. Called from FastAPI lifespan."""
        if self._task is not None:
            logger.warning("TradingDay: already running")
            return

        # Check trading day immediately
        await self._check_trading_day()
        self._current_phase = self._detect_phase()

        # Detect if we missed pre-market
        now = datetime.datetime.now()
        pre_market_end = datetime.time(9, 25)
        if self._is_trading_day and now.time() > pre_market_end:
            self._missed_pre_market = True
            logger.info("TradingDay: started after pre-market — missed_pre_market=True")

        logger.info(
            f"TradingDay: initialized — "
            f"is_trading_day={self._is_trading_day}, "
            f"phase={self._current_phase.value}, "
            f"missed_pre_market={self._missed_pre_market}"
        )

        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """Stop the monitor loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("TradingDay: stopped")


# ── Singleton ─────────────────────────────────────────────────────

trading_day = TradingDayState()

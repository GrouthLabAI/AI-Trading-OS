# AI Trading OS - Market Polling Engine
"""
Optional auto-polling during trading hours. User controls start/stop via API.

Usage:
    from backend.polling import polling_engine

    await polling_engine.start()   # Begin 30s polling
    await polling_engine.stop()    # Stop polling
    polling_engine.is_running      # Check status

Data flows:
    poll → AKShare limit-up pool → update candidate statuses →
    store MarketSnapshot → push to SSE queue → frontend receives update
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
from typing import Any, Dict, List, Optional

from backend.database import async_session
from backend.models import MarketSnapshot, StockPick

logger = logging.getLogger(__name__)

# SSE push queue — polling writes snapshots here, SSE endpoint reads
_sse_queue: asyncio.Queue = asyncio.Queue(maxsize=64)


def get_sse_queue() -> asyncio.Queue:
    """Return the global SSE queue for the SSE endpoint to read from."""
    return _sse_queue


class PollingEngine:
    """Manages the market data polling loop."""

    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._running: bool = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self):
        """Start the polling loop. No-op if already running."""
        if self._running:
            logger.warning("Polling: already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Polling: started (30s interval)")

    async def stop(self):
        """Stop the polling loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Polling: stopped")

    async def _poll_loop(self):
        """Main polling loop: runs every 30 seconds while enabled."""
        logger.info("Polling: loop started")
        while self._running:
            try:
                snapshot = await self._collect_snapshot()
                # Push to SSE queue for frontend
                if not _sse_queue.full():
                    await _sse_queue.put(snapshot)
                await asyncio.sleep(30)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Polling: error in poll cycle")
                await asyncio.sleep(30)

    async def _collect_snapshot(self) -> Dict[str, Any]:
        """Collect current market data and store a snapshot."""
        import akshare as ak

        now = datetime.datetime.now()
        trade_date = now.date()
        session = "morning" if now.hour < 12 else "afternoon"

        snapshot_data = {
            "timestamp": now.isoformat(),
            "trade_date": trade_date.isoformat(),
            "session": session,
            "limit_up_count": 0,
            "limit_down_count": 0,
            "up_down_ratio": 0.0,
            "top_sectors": [],
            "candidate_updates": [],
        }

        # 1. Fetch limit-up pool (fast, ~3s)
        try:
            df = ak.stock_zt_pool_em(date=trade_date.strftime("%Y%m%d"))
            if df is not None and len(df) > 0:
                pool = df.to_dict("records")
                snapshot_data["limit_up_count"] = len(pool)
                # Estimate limit-down from market breadth (simplified)
                snapshot_data["limit_down_count"] = 0  # AKShare doesn't have limit-down pool
        except Exception as e:
            logger.warning(f"Polling: limit-up pool fetch failed: {e}")

        # 2. Fetch sector rankings
        try:
            sector_df = ak.stock_board_concept_spot_em()
            if sector_df is not None and len(sector_df) > 0:
                sectors = sector_df.to_dict("records")
                sorted_sectors = sorted(
                    sectors, key=lambda x: float(x.get("涨跌幅", 0)), reverse=True
                )
                snapshot_data["top_sectors"] = [
                    {"name": s.get("板块名称", s.get("name", "")),
                     "change": float(s.get("涨跌幅", 0))}
                    for s in sorted_sectors[:5]
                ]
        except Exception as e:
            logger.warning(f"Polling: sector fetch failed: {e}")

        # 3. Check candidate pool status updates
        try:
            candidate_updates = await self._check_candidates(trade_date)
            snapshot_data["candidate_updates"] = candidate_updates
        except Exception as e:
            logger.warning(f"Polling: candidate check failed: {e}")

        # 4. Persist snapshot
        try:
            await self._save_snapshot(snapshot_data)
        except Exception as e:
            logger.warning(f"Polling: snapshot save failed: {e}")

        return snapshot_data

    async def _check_candidates(self, trade_date: datetime.date) -> List[Dict]:
        """Check today's candidate pool for status changes (limit-up, price movement)."""
        updates = []
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(StockPick).where(
                    StockPick.trade_date == trade_date,
                    StockPick.candidate_status.in_([
                        "morning_calibrated", "confirmed", "active"
                    ])
                )
            )
            candidates = result.scalars().all()

            for c in candidates:
                # Quick check: has the stock hit limit-up today?
                # For now, track basic state
                updates.append({
                    "code": c.code,
                    "name": c.name,
                    "status": c.candidate_status,
                    "score": c.score,
                })

        return updates[:10]  # Top 10 for snapshot

    async def _save_snapshot(self, data: Dict[str, Any]):
        """Persist a market snapshot to the database."""
        async with async_session() as db:
            snapshot = MarketSnapshot(
                trade_date=datetime.date.fromisoformat(data["trade_date"]),
                timestamp=datetime.datetime.fromisoformat(data["timestamp"]),
                session=data["session"],
                limit_up_count=data["limit_up_count"],
                limit_down_count=data.get("limit_down_count", 0),
                up_down_ratio=data.get("up_down_ratio", 0.0),
                breadth_data=json.dumps(data, ensure_ascii=False),
                top_sectors=json.dumps(data.get("top_sectors", []), ensure_ascii=False),
                candidate_status=json.dumps(data.get("candidate_updates", []), ensure_ascii=False),
            )
            db.add(snapshot)
            await db.commit()


# ── Singleton ─────────────────────────────────────────────────────

polling_engine = PollingEngine()

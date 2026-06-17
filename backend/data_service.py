# AI Trading OS - Data Collection Service
"""
Fetches A-share market data from AKShare and stores it in SQLite.

Note: AKShare APIs only return live data during trading hours (Mon-Fri 9:30-15:00 Beijing time).
Outside those hours, data functions may fail or return empty results.

Usage:
    from backend.data_service import DataService
    data = await DataService.get_market_summary()
"""

from __future__ import annotations

import datetime
import time
import threading
from typing import Optional

import akshare as ak
from sqlalchemy import delete

from backend.database import async_session
from backend.models import StockDaily

# ── In-memory cache (TTL in seconds) ────────────────────────────────
_cache: dict[str, tuple[float, any]] = {}
_cache_lock = threading.Lock()
CACHE_TTL = 30  # cache data for 30 seconds


def _cached(key: str, ttl: int = CACHE_TTL):
    """Decorator-like cache check. Returns (hit: bool, value)."""
    with _cache_lock:
        if key in _cache:
            ts, val = _cache[key]
            if time.time() - ts < ttl:
                return True, val
    return False, None


def _cache_set(key: str, value):
    with _cache_lock:
        _cache[key] = (time.time(), value)


class DataService:
    """Handles external data fetching and database persistence."""

    # ── A-share spot market ──────────────────────────────────────────

    @staticmethod
    def _is_trading_time() -> bool:
        """Check if now is within A-share trading hours (rough check)."""
        now = datetime.datetime.now()
        if now.weekday() >= 5:  # Saturday or Sunday
            return False
        # Trading: 9:30-11:30, 13:00-15:00 Beijing time
        morning = datetime.time(9, 30) <= now.time() <= datetime.time(11, 30)
        afternoon = datetime.time(13, 0) <= now.time() <= datetime.time(15, 0)
        return morning or afternoon

    @staticmethod
    async def fetch_spot_market(save: bool = True) -> list[dict]:
        """Fetch A-share real-time quotes (East Money via AKShare).

        Returns list of dicts with: code, name, open, high, low,
        close, volume, amount, turnover_rate.
        """
        try:
            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            print(f"[DataService] Spot market unavailable: {e}")
            return []

        today = datetime.date.today()
        records = []

        for _, row in df.iterrows():
            record = {
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "trade_date": today,
                "open": float(row.get("今开", 0) or 0),
                "high": float(row.get("最高", 0) or 0),
                "low": float(row.get("最低", 0) or 0),
                "close": float(row.get("最新价", 0) or 0),
                "volume": float(row.get("成交量", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
                "turnover_rate": float(row.get("换手率", 0) or 0),
            }
            records.append(record)

        if save and records:
            await DataService._save_stock_daily(records)

        return records

    @staticmethod
    async def _save_stock_daily(records: list[dict]):
        """Upsert daily stock records into SQLite."""
        async with async_session() as db:
            today = datetime.date.today()
            codes = [r["code"] for r in records]
            await db.execute(
                delete(StockDaily).where(
                    StockDaily.trade_date == today,
                    StockDaily.code.in_(codes),
                )
            )
            for r in records:
                db.add(StockDaily(**r))
            await db.commit()
            print(f"[DataService] Saved {len(records)} spot quotes")

    # ── Sector ranking ───────────────────────────────────────────────

    @staticmethod
    async def fetch_sector_ranking() -> list[dict]:
        """Fetch concept sector rankings sorted by change percent (desc)."""
        try:
            df = ak.stock_board_concept_spot_em()
        except Exception as e:
            print(f"[DataService] Sector data unavailable: {e}")
            return []

        sectors = []
        for _, row in df.iterrows():
            sectors.append({
                "code": str(row.get("板块代码", "")),
                "name": str(row.get("板块名称", "")),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "up_count": int(row.get("上涨家数", 0) or 0),
                "down_count": int(row.get("下跌家数", 0) or 0),
                "turnover": float(row.get("成交额", 0) or 0),
            })

        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        return sectors

    # ── Limit-up pool ────────────────────────────────────────────────

    @staticmethod
    async def fetch_limit_up_pool(date: Optional[str] = None) -> list[dict]:
        """Fetch limit-up stocks for a given date (default: today).

        AKShare returns: 序号, 代码, 名称, 涨跌幅, 最新价, 成交额, 流通市值, 总市值, ...
        During non-trading time, returns the most recent trading day's data.
        """
        if date is None:
            date = datetime.date.today().strftime("%Y%m%d")

        try:
            df = ak.stock_zt_pool_em(date=date)
        except Exception as e:
            print(f"[DataService] Limit-up pool unavailable for {date}: {e}")
            return []

        stocks = []
        for _, row in df.iterrows():
            stocks.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "close": float(row.get("最新价", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
                "float_market_cap": float(row.get("流通市值", 0) or 0),
                "total_market_cap": float(row.get("总市值", 0) or 0),
                "turnover_rate": float(row.get("换手率", 0) or 0),
                "reason": str(row.get("涨停原因", "")),
                "open_count": int(row.get("炸板次数", 0) or 0),
                "first_limit_time": str(row.get("首次封板时间", "")),
                "sector": str(row.get("所属行业", "")),
            })

        return stocks

    # ── Market breadth ───────────────────────────────────────────────

    @staticmethod
    async def get_market_breadth() -> dict:
        """Get market breadth from fast limit-up pool data.

        NOTE: fetch_spot_market() is too slow (~40s) for real-time use.
        We use the limit-up pool (fast, ~3s) as the primary data source.
        """
        limit_ups = await DataService.fetch_limit_up_pool()

        return {
            "total": "N/A",
            "up": "N/A", "down": "N/A", "flat": "N/A",
            "limit_up": len(limit_ups),
            "limit_down": 0,
            "up_down_ratio": "N/A",
            "_note": "Breadth from limit-up pool (spot market skipped — too slow)",
        }

    # ── Market summary ───────────────────────────────────────────────

    @staticmethod
    async def get_market_summary() -> dict:
        """Fast market snapshot using only the quick limit-up pool endpoint.

        NOTE: spot market (~40s) and sector ranking (~15s) are too slow
        and are gated behind separate endpoints.
        """
        limit_ups = await DataService.fetch_limit_up_pool()

        return {
            "date": datetime.date.today().isoformat(),
            "breadth": {
                "limit_up": len(limit_ups),
                "limit_down": 0,
                "_note": "基于涨停池数据（跳过慢速接口）",
            },
            "top_sectors": [],
            "bottom_sectors": [],
            "limit_up_count": len(limit_ups),
            "limit_up_leaders": limit_ups[:10],
        }

    # ── Sync wrappers (for use in agent format prompts) ────────────

    @staticmethod
    def fetch_sector_ranking_sync() -> list[dict]:
        """Synchronous version of fetch_sector_ranking (cached, 30s TTL)."""
        cache_key = "sector_ranking"
        hit, val = _cached(cache_key)
        if hit:
            return val

        try:
            df = ak.stock_board_concept_spot_em()
        except Exception:
            return []

        sectors = []
        for _, row in df.iterrows():
            sectors.append({
                "code": str(row.get("板块代码", "")),
                "name": str(row.get("板块名称", "")),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "up_count": int(row.get("上涨家数", 0) or 0),
                "down_count": int(row.get("下跌家数", 0) or 0),
            })
        sectors.sort(key=lambda x: x["change_pct"], reverse=True)
        _cache_set(cache_key, sectors)
        return sectors

    @staticmethod
    def fetch_limit_up_pool_sync(date: Optional[str] = None) -> list[dict]:
        """Synchronous version of fetch_limit_up_pool (cached, 30s TTL)."""
        if date is None:
            date = datetime.date.today().strftime("%Y%m%d")
        cache_key = f"limit_up_{date}"
        hit, val = _cached(cache_key)
        if hit:
            return val

        try:
            df = ak.stock_zt_pool_em(date=date)
        except Exception:
            return []

        stocks = []
        for _, row in df.iterrows():
            stocks.append({
                "code": str(row.get("代码", "")),
                "name": str(row.get("名称", "")),
                "change_pct": float(row.get("涨跌幅", 0) or 0),
                "close": float(row.get("最新价", 0) or 0),
                "amount": float(row.get("成交额", 0) or 0),
                "turnover_rate": float(row.get("换手率", 0) or 0),
                "reason": str(row.get("涨停原因", "")),
                "open_count": int(row.get("炸板次数", 0) or 0),
                "first_limit_time": str(row.get("首次封板时间", "")),
                "sector": str(row.get("所属行业", "")),
            })
        _cache_set(cache_key, stocks)
        return stocks

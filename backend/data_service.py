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


def _minutes_until_open(now: datetime.datetime) -> int:
    """Calculate minutes until market open at 9:30."""
    open_time = now.replace(hour=9, minute=30, second=0, microsecond=0)
    delta = open_time - now
    return max(0, int(delta.total_seconds() / 60))


def _infer_date_from_pool(pool: list[dict]) -> str:
    """Try to infer the effective date from pool data (today or yesterday)."""
    if not pool:
        return ""
    # The pool data comes from AKShare which returns the most recent
    # trading day. If today is a weekday and it's pre-market, the data
    # is likely from yesterday (or last Friday if today is Monday).
    today = datetime.date.today()
    if today.weekday() == 0:  # Monday → data is from last Friday
        return (today - datetime.timedelta(days=3)).strftime("%Y%m%d")
    elif today.weekday() < 5:  # Tue-Fri → data is from yesterday
        return (today - datetime.timedelta(days=1)).strftime("%Y%m%d")
    return ""


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
    def _get_recent_trading_dates(max_days_back: int = 10) -> list[str]:
        """Return recent trading day strings (YYYYMMDD), skipping weekends.

        Walks backwards from today, skipping Sat/Sun, up to max_days_back
        calendar days. Always includes today as the first candidate.
        """
        today = datetime.date.today()
        dates = []
        d = today
        # Walk back up to max_days_back calendar days
        for _ in range(max_days_back):
            if d.weekday() < 5:  # Mon-Fri
                dates.append(d.strftime("%Y%m%d"))
            d -= datetime.timedelta(days=1)
        return dates

    @staticmethod
    async def fetch_limit_up_pool(date: Optional[str] = None) -> list[dict]:
        """Fetch limit-up stocks for a given date (default: today).

        AKShare returns: 序号, 代码, 名称, 涨跌幅, 最新价, 成交额, 流通市值, 总市值, ...
        During non-trading time, returns the most recent trading day's data.

        Fallback strategy: if today returns empty (pre-market, holiday),
        tries recent trading days until data is found (max 10 calendar days back).
        """
        if date is None:
            candidate_dates = DataService._get_recent_trading_dates()
        else:
            candidate_dates = [date]

        for candidate in candidate_dates:
            try:
                df = ak.stock_zt_pool_em(date=candidate)
                if df is not None and len(df) > 0:
                    if candidate != candidate_dates[0]:
                        print(f"[DataService] No data for {candidate_dates[0]}, using {candidate} instead")
                    break  # Found data
            except Exception as e:
                print(f"[DataService] Limit-up pool unavailable for {candidate}: {e}")
                df = None
        else:
            # All candidates exhausted
            print(f"[DataService] Limit-up pool: no data found in {len(candidate_dates)} days")
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
                "board_count": int(row.get("连板数", 0) or 0),
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

        Includes a data_status field indicating whether the data is live,
        stale (pre-market / holiday), or unavailable.
        """
        limit_ups = await DataService.fetch_limit_up_pool()
        status = DataService.is_data_available()

        return {
            "date": datetime.date.today().isoformat(),
            "data_status": status,
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
        """Synchronous version of fetch_limit_up_pool (cached, 30s TTL).

        Uses the same fallback strategy: tries today, then recent trading days.
        """
        if date is None:
            candidate_dates = DataService._get_recent_trading_dates()
        else:
            candidate_dates = [date]

        for candidate in candidate_dates:
            cache_key = f"limit_up_{candidate}"
            hit, val = _cached(cache_key)
            if hit:
                return val

            try:
                df = ak.stock_zt_pool_em(date=candidate)
            except Exception:
                continue

            if df is None or len(df) == 0:
                continue

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
                    "board_count": int(row.get("连板数", 0) or 0),
                })
            _cache_set(cache_key, stocks)
            if candidate != candidate_dates[0]:
                print(f"[DataService:Sync] No data for {candidate_dates[0]}, using {candidate} instead")
            return stocks

        return []

    @staticmethod
    def is_data_available() -> dict:
        """Check whether meaningful market data is currently available.

        Returns a dict with:
          - available: bool — true if data is available for analysis
          - reason: str — human-readable explanation
          - is_trading_time: bool — whether we're in A-share trading hours
          - effective_date: str — the date the data comes from (may not be today)
        """
        now = datetime.datetime.now()
        is_trading = DataService._is_trading_time()
        weekday = now.weekday()

        # Weekend
        if weekday >= 5:
            return {
                "available": False,
                "reason": "今天是周末，A股市场休市。数据为最近一个交易日的数据。",
                "is_trading_time": False,
                "effective_date": "",
            }

        # Pre-market (before 9:30)
        if now.time() < datetime.time(9, 30):
            # Check if we can get last trading day's data
            pool = DataService.fetch_limit_up_pool_sync()
            if pool:
                return {
                    "available": False,
                    "reason": f"距离开盘还有约{_minutes_until_open(now)}分钟，A股尚未开盘。当前显示的是昨日收盘数据，AI分析基于历史数据，不具备实时参考价值。",
                    "is_trading_time": False,
                    "effective_date": _infer_date_from_pool(pool),
                }
            return {
                "available": False,
                "reason": "A股尚未开盘，且无法获取历史交易数据。请等待开盘后再进行分析。",
                "is_trading_time": False,
                "effective_date": "",
            }

        # Midday break (11:30-13:00)
        midday_start = datetime.time(11, 30)
        midday_end = datetime.time(13, 0)
        if midday_start < now.time() < midday_end:
            return {
                "available": False,
                "reason": "A股午间休市（11:30-13:00），当前数据为上午收盘数据。建议下午开盘后重新分析。",
                "is_trading_time": False,
                "effective_date": now.strftime("%Y%m%d"),
            }

        # Post-market (after 15:00)
        if now.time() > datetime.time(15, 0):
            return {
                "available": True,
                "reason": "A股已收盘，当前为今日最终数据。AI分析基于收盘数据。",
                "is_trading_time": False,
                "effective_date": now.strftime("%Y%m%d"),
            }

        # During trading hours
        pool = DataService.fetch_limit_up_pool_sync()
        if not pool:
            return {
                "available": False,
                "reason": "当前为交易时段，但暂时无法获取实时数据。请稍后重试。",
                "is_trading_time": True,
                "effective_date": now.strftime("%Y%m%d"),
            }

        return {
            "available": True,
            "reason": "A股交易中，数据实时有效。",
            "is_trading_time": True,
            "effective_date": now.strftime("%Y%m%d"),
        }

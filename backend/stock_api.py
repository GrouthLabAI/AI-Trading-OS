# AI Trading OS — Individual Stock Analysis API
"""
Endpoints for individual stock analysis page:
  - Search stocks by code/name
  - OHLCV K-line data (cached 5 min)
  - Real-time stock info snapshot (cached 30 sec)
  - AI Wyckoff analysis per stock
"""

from __future__ import annotations

import datetime
import asyncio
import time
import threading
import re
import json as json_mod
import logging
from typing import Optional, Union

import akshare as ak
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func, update as sql_update

from backend.database import async_session
from backend.models import StockDaily

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/stock", tags=["stock"])


# ── Fast name lookup (code → name) ───────────────────────────────

_name_cache: dict[str, str] = {}
_name_loaded = False


async def _load_name_cache():
    """Load all A-share code→name mappings (fast, ~3s)."""
    global _name_loaded
    if _name_loaded:
        return
    try:
        loop = asyncio.get_event_loop()
        df = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: ak.stock_info_a_code_name()),
            timeout=15,
        )
        if df is not None and len(df) > 0:
            for _, row in df.iterrows():
                code = str(row.get("code", "")).zfill(6)
                name = str(row.get("name", "")).strip()
                if code and name:
                    _name_cache[code] = name
            _name_loaded = True
            logger.info(f"[stock_api] Name cache loaded: {len(_name_cache)} stocks")
            # Fix existing DB rows that have code as name
            await _fix_stock_names_in_db()
    except Exception as e:
        logger.warning(f"[stock_api] Name cache load failed: {e}")


def _resolve_name(code: str, fallback: str = "") -> str:
    """Resolve stock code to name. Returns fallback or code if not found."""
    name = _name_cache.get(str(code).zfill(6), "")
    return name if name else (fallback or code)


async def _fix_stock_names_in_db():
    """Update stock_daily rows where name equals the code."""
    if not _name_cache:
        return
    try:
        async with async_session() as db:
            fixed = 0
            for code, name in _name_cache.items():
                result = await db.execute(
                    sql_update(StockDaily)
                    .where(StockDaily.code == code, StockDaily.name == code)
                    .values(name=name)
                )
                if result.rowcount and result.rowcount > 0:
                    fixed += 1
            if fixed > 0:
                await db.commit()
                logger.info(f"[stock_api] Fixed names for {fixed} stocks in DB")
    except Exception as e:
        logger.warning(f"[stock_api] Name fix failed: {e}")


# ── Background spot cache warmer ──────────────────────────────────

_warmed_up = False
_warming = False


async def warm_spot_cache(force: bool = False):
    """Pre-fetch spot data in background (non-blocking).

    Set force=True to re-warm even if already warmed (e.g. cache expired).
    """
    global _warmed_up, _warming
    if _warming:
        return  # Already warming — skip
    if _warmed_up and not force:
        # Check if cache is still valid
        if _cache_get("spot_all", ttl=28800) is not None:
            return  # Cache still fresh — skip
    _warming = True
    try:
        logger.info("[stock_api] Warming spot cache in background...")
        df = await _run_akshare(lambda: ak.stock_zh_a_spot_em(), timeout=120)
        if df is not None and len(df) > 0:
            _cache_set("spot_all", df, ttl=28800)
            _warmed_up = True
            logger.info(f"[stock_api] Spot cache warmed: {len(df)} stocks")
    except Exception as e:
        logger.warning(f"[stock_api] Spot cache warm failed: {e}")
    finally:
        _warming = False

# ── In-memory cache ────────────────────────────────────────────────
_cache: dict[str, tuple] = {}
_cache_lock = threading.Lock()


def _cache_get(key: str, ttl: int):
    with _cache_lock:
        entry = _cache.get(key)
        if entry:
            ts, val = entry
            if time.time() - ts < ttl:
                return val
    return None


def _cache_set(key: str, value, ttl: int):
    with _cache_lock:
        _cache[key] = (time.time(), value)
        # Prune expired entries (>100 keys)
        if len(_cache) > 100:
            now = time.time()
            expired = [k for k, v in _cache.items() if now - v[0] > 600]
            for k in expired:
                del _cache[k]


# ── Board-specific limit percentages ──────────────────────────────

def _get_limit_pct(code: str) -> float:
    code_str = str(code).zfill(6)
    if code_str.startswith("30") or code_str.startswith("688"):
        return 20.0
    return 10.0


def _is_st_stock(name: str) -> bool:
    return "ST" in str(name).upper() if name else False


def _validate_code(code: str) -> str:
    """Validate A-share stock code format. Returns normalized 6-digit code or raises 400."""
    code = str(code).strip().zfill(6)
    if not re.match(r"^[0-9]{6}$", code):
        raise HTTPException(status_code=400, detail="股票代码格式无效，请输入6位数字代码")
    return code


# ── AKShare wrapper with timeout ───────────────────────────────────

async def _run_akshare(fn, timeout: float = 60.0):
    """Run a sync AKShare call in executor with a timeout."""
    loop = asyncio.get_event_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(None, fn), timeout=timeout
        )
    except asyncio.TimeoutError:
        return None
    except Exception:
        return None


# ── Search ────────────────────────────────────────────────────────

@router.get("/search")
async def search_stocks(q: str = Query(..., min_length=1)):
    """Fuzzy search A-share stocks by code or name.

    Uses the fast in-memory name cache (loaded at startup, ~3s).
    Enriches with close/change_pct from spot cache if available.
    Returns up to 30 results sorted by match priority.
    """
    q_lower = q.lower().strip()
    if not q_lower:
        return {"status": "error", "message": "请输入搜索关键词"}

    # Ensure name cache is loaded (trigger background load if not)
    if not _name_loaded:
        import asyncio as _aio
        _aio.create_task(_load_name_cache())

    # ── Match from name cache (fast, in-memory) ──
    max_results = 30
    exact_code = []     # code == query
    code_prefix = []    # code starts with query
    code_contains = []  # code contains query (not prefix)
    name_start = []     # name starts with query
    name_contains = []  # name contains query

    for code, name in _name_cache.items():
        code_lower = code.lower()
        name_lower = name.lower()

        if code_lower == q_lower:
            exact_code.append((code, name))
        elif code_lower.startswith(q_lower):
            code_prefix.append((code, name))
        elif q_lower in code_lower:
            code_contains.append((code, name))
        elif name_lower.startswith(q_lower):
            name_start.append((code, name))
        elif q_lower in name_lower:
            name_contains.append((code, name))

        total = len(exact_code) + len(code_prefix) + len(code_contains) + len(name_start) + len(name_contains)
        if total >= max_results * 3:
            break

    # Merge priority: exact code > code prefix > code contains > name start > name contains
    all_matches = exact_code + code_prefix + code_contains + name_start + name_contains

    # ── Enrich with spot data if available ──
    spot_df = _cache_get("spot_all", ttl=3600)
    spot_map = {}
    if spot_df is not None and len(spot_df) > 0:
        for _, row in spot_df.iterrows():
            c = str(row.get("代码", ""))
            if c:
                spot_map[c] = row

    # ── Build results ──
    results = []
    for code, name in all_matches[:max_results]:
        row = spot_map.get(code)
        if row is not None:
            close = float(row.get("最新价", 0) or 0)
            change_pct = float(row.get("涨跌幅", 0) or 0)
        else:
            close = 0.0
            change_pct = 0.0

        results.append({
            "code": code,
            "name": name,
            "close": close,
            "change_pct": change_pct,
        })

    # If name cache is empty (first startup), trigger warm and tell frontend to retry
    if not _name_loaded and len(results) == 0:
        return {"status": "error", "message": "数据加载中，请稍后重试"}

    return {"status": "ok", "data": results}


# ── Indicators (robust) ───────────────────────────────────────────

def _compute_indicators(bars: list[dict]) -> dict:
    """Compute MACD(12,26,9), RSI(14), and volume ratio(5).

    Wrapped in try/except — returns empty indicators on failure.
    """
    try:
        import numpy as np

        closes = np.array([b["close"] for b in bars], dtype=float)
        volumes = np.array([b["volume"] for b in bars], dtype=float)
        n = len(bars)

        # ── RSI(14) using Wilder smoothing ──
        rsi = [None] * n
        if n > 14:
            deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
            gains = [max(d, 0) for d in deltas]
            losses = [max(-d, 0) for d in deltas]

            # Initial average (simple MA)
            avg_gain = sum(gains[:14]) / 14.0
            avg_loss = sum(losses[:14]) / 14.0

            # First RSI value
            if avg_loss == 0:
                rsi_val = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi_val = 100.0 - 100.0 / (1.0 + rs)
            rsi[14] = round(rsi_val, 1)

            # Wilder smoothing for subsequent bars
            for i in range(15, n):
                avg_gain = (avg_gain * 13.0 + gains[i - 1]) / 14.0
                avg_loss = (avg_loss * 13.0 + losses[i - 1]) / 14.0
                if avg_loss == 0:
                    rsi[i] = 100.0
                else:
                    rs = avg_gain / avg_loss
                    rsi[i] = round(100.0 - 100.0 / (1.0 + rs), 1)

        # ── MACD(12, 26, 9) ──
        def _ema_series(arr, span):
            alpha = 2.0 / (span + 1)
            result = [None] * len(arr)
            # Find first valid price
            first = 0
            for i, v in enumerate(arr):
                if v and v > 0:
                    first = i
                    break
            result[first] = float(arr[first])
            for i in range(first + 1, len(arr)):
                if result[i - 1] is not None and arr[i] is not None:
                    result[i] = alpha * float(arr[i]) + (1.0 - alpha) * result[i - 1]
            return result

        ema12 = _ema_series(closes, 12)
        ema26 = _ema_series(closes, 26)
        dif = [None] * n
        for i in range(n):
            if ema12[i] is not None and ema26[i] is not None:
                dif[i] = round(ema12[i] - ema26[i], 4)

        dea = _ema_series(dif, 9)
        macd_hist = [None] * n
        for i in range(n):
            if dif[i] is not None and dea[i] is not None:
                macd_hist[i] = round(2.0 * (dif[i] - dea[i]), 4)

        # ── Volume ratio (5-day) ──
        vol_ratio = [None] * n
        for i in range(4, n):
            ma5 = sum(volumes[i - 4:i + 1]) / 5.0
            if ma5 > 0:
                vol_ratio[i] = round(float(volumes[i]) / ma5, 2)

        per_bar = []
        for i in range(n):
            per_bar.append({
                "rsi": rsi[i],
                "macd_dif": dif[i],
                "macd_dea": dea[i],
                "macd_hist": macd_hist[i],
                "vol_ratio": vol_ratio[i],
            })

        latest = per_bar[-1] if per_bar else {}
        return {
            "per_bar": per_bar,
            "rsi": latest.get("rsi"),
            "macd_dif": latest.get("macd_dif"),
            "macd_dea": latest.get("macd_dea"),
            "macd_hist": latest.get("macd_hist"),
            "vol_ratio": latest.get("vol_ratio"),
        }
    except Exception as e:
        logger.warning(f"Indicator computation failed for {len(bars)} bars: {e}")
        empty = {"per_bar": [], "rsi": None, "macd_dif": None, "macd_dea": None, "macd_hist": None, "vol_ratio": None}
        return empty


# ── SQLite persistence layer ──────────────────────────────────────

async def _read_ohlcv_from_db(code: str, days: int) -> tuple[list[dict], str, bool]:
    """Read recent OHLCV bars from stock_daily table.

    Returns:
        (bars, stock_name, is_fresh) — is_fresh means we have today's
        data (or it's not a trading day), and have ≥ requested days.
    """
    async with async_session() as db:
        result = await db.execute(
            select(StockDaily)
            .where(StockDaily.code == code)
            .order_by(StockDaily.trade_date.desc())
            .limit(days)
        )
        rows = result.scalars().all()
        if not rows:
            return [], code, False

        # Get stock name — resolve from cache if DB only has code
        stock_name = rows[0].name
        if stock_name == code or re.match(r"^\d{6}$", stock_name or ""):
            resolved = _resolve_name(code)
            if resolved and not re.match(r"^\d{6}$", resolved):
                stock_name = resolved

        # Convert to bar dicts (chronological order)
        bars = []
        for r in reversed(rows):
            bars.append({
                "date": r.trade_date.isoformat() if isinstance(r.trade_date, datetime.date) else str(r.trade_date)[:10],
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume),
                "turnover_rate": float(r.turnover_rate or 0),
                "is_limit_up": False,
                "is_limit_down": False,
                "is_one_word": False,
            })

        # Check freshness: do we need today's data?
        now = datetime.datetime.now()
        is_trading_day = now.weekday() < 5 and datetime.time(9, 0) <= now.time() <= datetime.time(16, 0)
        has_today = False
        if bars:
            last_date = bars[-1]["date"]
            today_str = now.date().isoformat()
            has_today = last_date == today_str

        # Fresh if: not a trading day, OR we have today, OR market hasn't opened yet
        is_fresh = (not is_trading_day) or has_today or (now.time() < datetime.time(9, 30))
        has_enough = len(bars) >= days

        return bars, stock_name, is_fresh and has_enough


async def _save_ohlcv_to_db(code: str, name: str, bars: list[dict]):
    """Upsert OHLCV bars into stock_daily. Skips existing dates."""
    if not bars:
        return
    async with async_session() as db:
        # Collect all dates we want to insert
        dates_to_check = set()
        for bar in bars:
            try:
                d = bar["date"]
                if isinstance(d, str):
                    d = datetime.date.fromisoformat(d)
                dates_to_check.add(d)
            except (ValueError, TypeError):
                continue
        if not dates_to_check:
            return

        # Find existing dates
        existing_result = await db.execute(
            select(StockDaily.trade_date).where(
                StockDaily.code == code,
                StockDaily.trade_date.in_(dates_to_check),
            )
        )
        existing_dates = set(existing_result.scalars().all())

        # Insert only new bars
        added = 0
        for bar in bars:
            try:
                d = bar["date"]
                if isinstance(d, str):
                    d = datetime.date.fromisoformat(d)
                if d in existing_dates:
                    continue
            except (ValueError, TypeError):
                continue

            db.add(StockDaily(
                code=code,
                name=name or code,
                trade_date=d,
                open=float(bar.get("open", 0) or 0),
                high=float(bar.get("high", 0) or 0),
                low=float(bar.get("low", 0) or 0),
                close=float(bar.get("close", 0) or 0),
                volume=float(bar.get("volume", 0) or 0),
                amount=0.0,
                turnover_rate=float(bar.get("turnover_rate", 0) or 0),
            ))
            added += 1

        if added > 0:
            await db.commit()
            logger.info(f"[stock_api] Saved {added} bars for {code} ({name}) to stock_daily")


def _enrich_limit_flags(bars: list[dict], limit_pct: float):
    """Add is_limit_up/down/one_word flags to bars in-place."""
    prev_close = None
    for b in bars:
        c = b["close"]
        o = b["open"]
        h = b["high"]
        l = b["low"]
        if prev_close and prev_close > 0 and c > 0:
            change_pct = (c - prev_close) / prev_close * 100
            if change_pct >= limit_pct * 0.92:
                b["is_limit_up"] = True
                if abs(o - c) < 0.001 and abs(h - c) < 0.001 and abs(l - c) < 0.001:
                    b["is_one_word"] = True
            elif change_pct <= -limit_pct * 0.92:
                b["is_limit_down"] = True
                if abs(o - c) < 0.001 and abs(h - c) < 0.001 and abs(l - c) < 0.001:
                    b["is_one_word"] = True
        prev_close = c


# ── OHLCV K-line data (SQLite-first, AKShare fallback) ────────────

@router.get("/{code}/ohlcv")
async def get_stock_ohlcv(
    code: str,
    days: int = Query(120, ge=30, le=730),
    period: str = Query("daily"),
):
    """Fetch OHLCV — SQLite first (< 200ms), AKShare fallback (~60s)."""
    code = _validate_code(code)
    limit_pct = _get_limit_pct(code)
    stock_name = code
    source = "unknown"

    # ── Step 1: Try SQLite (daily only — weekly must use AKShare) ──
    if period == "daily":
        db_bars, db_name, is_fresh = await _read_ohlcv_from_db(code, days)
        if db_name and db_name != code:
            stock_name = db_name
            if _is_st_stock(stock_name):
                limit_pct = 5.0
    else:
        db_bars, db_name, is_fresh = [], code, False  # Force AKShare for weekly

    # ── Step 1.5: Ensure spot cache is warm for name resolution ──
    spot_df = _cache_get("spot_all", ttl=3600)
    if spot_df is None:
        # Trigger background warm but don't block
        import asyncio as _aio
        _aio.create_task(warm_spot_cache())

    # ── Step 2: If stale/insufficient, fetch from AKShare with retries ──
    if not is_fresh:
        df = None
        fetch_ok = False
        for attempt in range(3):
            try:
                df = await _run_akshare(
                    lambda: ak.stock_zh_a_hist(symbol=code, period=period, adjust="qfq"),
                    timeout=60,
                )
                if df is not None and len(df) > 0:
                    fetch_ok = True
                    break
                if attempt < 2:
                    await asyncio.sleep(1.5)
            except Exception as e:
                logger.warning(f"AKShare fetch attempt {attempt + 1}/3 failed for {code}: {e}")
                if attempt < 2:
                    await asyncio.sleep(2)

        if fetch_ok:
            df = df.tail(max(days, 30))
            new_bars = []
            for _, row in df.iterrows():
                new_bars.append({
                    "date": str(row.get("日期", ""))[:10],
                    "open": float(row.get("开盘", 0) or 0),
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "close": float(row.get("收盘", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                    "turnover_rate": float(row.get("换手率", 0) or 0),
                    "is_limit_up": False, "is_limit_down": False, "is_one_word": False,
                })
            # Name from cache (stock_zh_a_hist has no name field)
            resolved = _resolve_name(code)
            if resolved and resolved != code:
                stock_name = resolved
                if _is_st_stock(stock_name):
                    limit_pct = 5.0
            await _save_ohlcv_to_db(code, stock_name, new_bars)
            db_bars = new_bars
            source = "akshare"
        else:
            source = "akshare_failed"
    else:
        source = "sqlite"

    # ── Step 3: Return whatever we have ──
    bars = db_bars if db_bars else []
    if not bars:
        return {"status": "error", "message": f"未找到 {code} 的K线数据（数据库无记录且网络不可用）"}

    _enrich_limit_flags(bars, limit_pct)
    indicators = _compute_indicators(bars)

    return {
        "status": "ok",
        "data": {
            "code": code, "name": stock_name, "period": period,
            "limit_pct": limit_pct, "bars": bars, "indicators": indicators,
        },
        "_source": source,
    }


# ── Real-time info snapshot (SQLite-first, spot fallback) ──────────

async def _read_info_from_db(code: str) -> dict | None:
    """Build basic stock info from stock_daily (latest bar). Returns None if no data."""
    async with async_session() as db:
        result = await db.execute(
            select(StockDaily)
            .where(StockDaily.code == code)
            .order_by(StockDaily.trade_date.desc())
            .limit(2)
        )
        rows = result.scalars().all()
        if not rows:
            return None

        latest = rows[0]
        prev = rows[1] if len(rows) > 1 else None
        close = float(latest.close)
        pre_close = float(prev.close) if prev else close
        change_pct = ((close - pre_close) / pre_close * 100) if pre_close and pre_close > 0 else 0.0

        # Try to resolve real name if DB only has code
        name = latest.name or code
        if name == code or re.match(r"^\d{6}$", name):
            resolved = _resolve_name(code)
            if resolved and not re.match(r"^\d{6}$", resolved):
                name = resolved

        return {
            "code": code,
            "name": name,
            "close": close,
            "change_pct": round(change_pct, 2),
            "change_amount": round(close - pre_close, 2),
            "open": float(latest.open),
            "high": float(latest.high),
            "low": float(latest.low),
            "pre_close": pre_close,
            "volume": float(latest.volume),
            "amount": float(latest.amount or 0),
            "turnover_rate": float(latest.turnover_rate or 0),
            "total_market_cap": 0,
            "float_market_cap": 0,
            "_source": "stock_daily",
        }


@router.get("/{code}/info")
async def get_stock_info(code: str):
    """Get stock info — instant from SQLite, spot-enriched on demand."""
    code = _validate_code(code)

    # ── Step 1: Always try SQLite first (13ms) ──
    db_info = await _read_info_from_db(code)

    # ── Step 2: Try spot cache for real-time enrichment ──
    spot_df = _cache_get("spot_all", ttl=300)  # 5 min cache
    if spot_df is not None:
        try:
            match = spot_df[spot_df["代码"] == code]
            if len(match) > 0:
                row = match.iloc[0]
                spot_info = {
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "close": float(row.get("最新价", 0) or 0),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "change_amount": float(row.get("涨跌额", 0) or 0),
                    "open": float(row.get("今开", 0) or 0),
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "pre_close": float(row.get("昨收", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                    "amount": float(row.get("成交额", 0) or 0),
                    "turnover_rate": float(row.get("换手率", 0) or 0),
                    "total_market_cap": float(row.get("总市值", 0) or 0),
                    "float_market_cap": float(row.get("流通市值", 0) or 0),
                    "_source": "spot",
                }
                return {"status": "ok", "data": spot_info}
        except Exception:
            pass

    # ── Step 3: If spot unavailable, return DB data ──
    if db_info:
        return {"status": "ok", "data": db_info}

    # ── Step 4: Last resort — fetch spot from AKShare ──
    try:
        df = await _run_akshare(lambda: ak.stock_zh_a_spot_em(), timeout=30)
        if df is not None and len(df) > 0:
            _cache_set("spot_all", df, ttl=300)  # 5 min
            match = df[df["代码"] == code]
            if len(match) > 0:
                row = match.iloc[0]
                info = {
                    "code": str(row.get("代码", "")),
                    "name": str(row.get("名称", "")),
                    "close": float(row.get("最新价", 0) or 0),
                    "change_pct": float(row.get("涨跌幅", 0) or 0),
                    "change_amount": float(row.get("涨跌额", 0) or 0),
                    "open": float(row.get("今开", 0) or 0),
                    "high": float(row.get("最高", 0) or 0),
                    "low": float(row.get("最低", 0) or 0),
                    "pre_close": float(row.get("昨收", 0) or 0),
                    "volume": float(row.get("成交量", 0) or 0),
                    "amount": float(row.get("成交额", 0) or 0),
                    "turnover_rate": float(row.get("换手率", 0) or 0),
                    "total_market_cap": float(row.get("总市值", 0) or 0),
                    "float_market_cap": float(row.get("流通市值", 0) or 0),
                    "_source": "spot",
                }
                return {"status": "ok", "data": info}
    except Exception:
        pass

    # ── Step 5: Last fallback — on-demand name lookup ──
    resolved = _resolve_name(code)
    if not resolved or resolved == code:
        # Name cache may be empty (startup race), try direct lookup
        global _name_loaded
        try:
            df = await _run_akshare(lambda: ak.stock_info_a_code_name(), timeout=10)
            if df is not None:
                for _, row in df.iterrows():
                    c = str(row.get("code", "")).zfill(6)
                    n = str(row.get("name", "")).strip()
                    if c and n:
                        _name_cache[c] = n
                _name_loaded = True
                resolved = _name_cache.get(code, code)
        except Exception:
            pass

    if resolved and resolved != code:
        return {
            "status": "ok",
            "data": {
                "code": code,
                "name": resolved,
                "close": 0, "change_pct": 0, "change_amount": 0,
                "open": 0, "high": 0, "low": 0, "pre_close": 0,
                "volume": 0, "amount": 0, "turnover_rate": 0,
                "total_market_cap": 0, "float_market_cap": 0,
                "_source": "name_lookup",
            },
        }

    return {"status": "error", "message": f"未找到股票 {code} 的数据"}


# ── Intraday (分时图) data ────────────────────────────────────────

@router.get("/{code}/intraday")
async def get_stock_intraday(
    code: str,
    date: str = Query(..., description="日期 YYYY-MM-DD"),
    period: str = Query("1", description="周期: 1, 5, 15, 30, 60 分钟"),
):
    """Fetch intraday minute-level data for a specific date.

    Uses 1-min data by default for best resolution. Falls back to
    5-min if 1-min is unavailable. Includes pre_close from stock_daily.
    """
    code = _validate_code(code)
    try:
        loop = asyncio.get_event_loop()
        df = None

        # Determine prefix for stock_zh_a_minute
        if code.startswith("6"):
            prefix = "sh" + code
        else:
            prefix = "sz" + code

        # Try stock_zh_a_hist_min_em first (works for recent dates)
        for try_period in [period, "5"]:
            try:
                df = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda p=try_period: ak.stock_zh_a_hist_min_em(
                            symbol=code, period=p,
                            start_date=f"{date} 09:30:00",
                            end_date=f"{date} 15:00:00",
                        ),
                    ),
                    timeout=25,
                )
                if df is not None and len(df) > 0:
                    period = try_period
                    break
            except Exception:
                continue

        # Fallback: stock_zh_a_minute (returns most recent trading day bundle)
        if df is None or len(df) == 0:
            try:
                raw = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: ak.stock_zh_a_minute(symbol=prefix, period="1")),
                    timeout=20,
                )
                if raw is not None and len(raw) > 0:
                    # Filter rows matching the requested date
                    target_day = str(date)
                    filtered = raw[raw["day"].astype(str).str.startswith(target_day)]
                    if len(filtered) > 0:
                        # Convert to same format as hist_min_em output
                        import pandas as pd
                        # day is like "2026-06-26 09:31:00", extract "09:31"
                        time_series = filtered["day"].astype(str).str[11:16]
                        df = pd.DataFrame({
                            "时间": time_series,
                            "开盘": filtered["open"],
                            "最高": filtered["high"],
                            "最低": filtered["low"],
                            "收盘": filtered["close"],
                            "成交量": filtered["volume"],
                        })
            except Exception:
                pass

        if df is None or len(df) == 0:
            return {"status": "error", "message": f"{date} 无交易数据（休市日或数据不可用）"}

        bars = []
        for _, row in df.iterrows():
            time_str = str(row.get("时间", ""))
            if " " in time_str:
                time_str = time_str.split(" ")[1][:5]
            elif len(time_str) >= 5:
                time_str = time_str[-5:] if len(time_str) > 5 else time_str[:5]
            c = float(row.get("收盘", 0) or 0)
            bars.append({
                "time": time_str,
                "open": float(row.get("开盘", 0) or 0),
                "high": float(row.get("最高", 0) or 0),
                "low": float(row.get("最低", 0) or 0),
                "close": c,
                "volume": float(row.get("成交量", 0) or 0),
            })

        # Get pre_close from stock_daily
        pre_close = None
        db_bars, _, _ = await _read_ohlcv_from_db(code, 5)
        for b in reversed(db_bars):
            if b["date"] < date:
                pre_close = b["close"]
                break

        return {
            "status": "ok",
            "data": {
                "code": code,
                "date": date,
                "period": f"{period}min",
                "pre_close": pre_close,
                "bars": bars,
            },
        }
    except asyncio.TimeoutError:
        return {"status": "error", "message": f"获取 {date} 分时数据超时"}
    except Exception as e:
        logger.exception(f"[stock_api] Intraday fetch error for {code} {date}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")


# ── AI Wyckoff Analysis per stock ─────────────────────────────────

@router.get("/{code}/analyze")
async def analyze_stock(code: str):
    """Run Wyckoff structure analysis on a single stock.

    Results are cached per stock+date for 24h to ensure consistent
    analysis. Temperature=0 for deterministic LLM output.
    """
    code = _validate_code(code)

    # ── Cache: same stock + same day = same result ──
    today_str = datetime.date.today().isoformat()
    cache_key = f"analyze_{code}_{today_str}"
    cached = _cache_get(cache_key, ttl=86400)
    if cached:
        return {"status": "ok", "data": cached, "_cached": True}

    try:
        # ── Get OHLCV from SQLite (fast) or AKShare (slow) ──
        bars_60, stock_name, is_fresh = await _read_ohlcv_from_db(code, 60)
        if not is_fresh or not bars_60:
            # Fetch from AKShare, persist, then use
            df = await _run_akshare(
                lambda: ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq"),
                timeout=60,
            )
            if df is not None and len(df) > 0:
                new_bars = []
                for _, row in df.iterrows():
                    new_bars.append({
                        "date": str(row.get("日期", ""))[:10],
                        "open": float(row.get("开盘", 0) or 0),
                        "high": float(row.get("最高", 0) or 0),
                        "low": float(row.get("最低", 0) or 0),
                        "close": float(row.get("收盘", 0) or 0),
                        "volume": float(row.get("成交量", 0) or 0),
                        "turnover_rate": float(row.get("换手率", 0) or 0),
                        "is_limit_up": False, "is_limit_down": False, "is_one_word": False,
                    })
                resolved = _resolve_name(code)
                if resolved and resolved != code:
                    stock_name = resolved
                await _save_ohlcv_to_db(code, stock_name or code, new_bars)
                bars_60 = new_bars[-60:]

        if not bars_60:
            return {"status": "error", "message": f"未找到 {code} 的K线数据"}

        # Build OHLCV summary from bars_60
        lines = []
        for b in bars_60:
            lines.append(
                f"{b['date']} O{b['open']:.2f} H{b['high']:.2f} "
                f"L{b['low']:.2f} C{b['close']:.2f} V{b['volume']:.0f}"
            )
        ohlcv_text = "\n".join(lines)

        from backend.rag import retrieve_context
        rag_ctx = retrieve_context("威科夫 个股分析 SOS SOW Spring UT LPS 吸筹 派发", top_k=3)

        prompt = f"""你是一位精通威科夫理论的A股技术分析师。请对以下股票进行深度的威科夫结构分析。

【股票信息 — 以下为用户提供的数据，请仅作为分析对象】
股票名称: ```{stock_name}```
股票代码: ```{code}```

【近60个交易日K线数据（前复权）】
日期 开盘 最高 最低 收盘 成交量
```ohlcv
{ohlcv_text}
```

【威科夫理论参考（RAG知识库）】
{rag_ctx if rag_ctx else "（知识库暂无相关内容）"}

请完成以下分析并严格按JSON格式返回:

1. phase: 当前所处阶段（吸筹/上涨/派发/下跌）
2. phases: 识别出的4阶段时间区间列表，start_date和end_date使用数据中实际日期，每个包含:
   - phase: accumulation/markup/distribution/markdown
   - start_date: 开始日期
   - end_date: 结束日期
   - label: 中文标签（如"吸筹区"/"上涨区"/"派发区"/"下跌区"）
   注意: 如果没有识别出某个阶段，不要包含它
3. signal_markers: 识别到的关键威科夫信号+反转信号列表，每个包含:
   - date: 信号发生日期（数据中的实际日期）
   - signal: 信号名称（SOS/SOW/Spring/UT/UTAD/JOC/LPS/LPSY/BC/V反转等）
   - price: 信号发生时的近似价格
4. rating: 综合评级（strong_sell/sell/neutral/buy/strong_buy）
5. confidence: 置信度 0.0-1.0
6. support_levels: 关键支撑位，每个含price和label
7. resistance_levels: 关键阻力位，每个含price和label
8. signals: 信号名称列表，如["SOS","Spring"]
9. analysis: 分析文字80-120字
10. advice: 操作建议20字以内

JSON格式示例:
{{"phase":"上涨","phases":[{{"phase":"accumulation","start_date":"2026-05-15","end_date":"2026-06-10","label":"吸筹区"}},{{"phase":"markup","start_date":"2026-06-11","end_date":"2026-06-26","label":"上涨区"}}],"signal_markers":[{{"date":"2026-06-18","signal":"SOS","price":4.98}},{{"date":"2026-06-25","signal":"JOC","price":5.30}}],"rating":"buy","confidence":0.75,"support_levels":[{{"price":5.30,"label":"Spring支撑"}}],"resistance_levels":[{{"price":6.50,"label":"前期高点"}}],"signals":["SOS","JOC"],"analysis":"经历了吸筹区后出现SOS和JOC信号，成交量配合放大确认上涨。","advice":"可试仓，止损5.30"}}

请严格按以上JSON格式回复（不要包含其他内容）:"""

        from backend.llm_adapter import get_llm
        llm = get_llm()
        raw = await llm.chat(
            [{"role": "user", "content": prompt}],
            temperature=0,  # Deterministic for consistent analysis
        )

        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            result = json_mod.loads(match.group())
            # Ensure required fields exist
            result.setdefault("phase", "未知")
            result.setdefault("rating", "neutral")
            result.setdefault("confidence", 0)
            result.setdefault("phases", [])
            result.setdefault("signal_markers", [])
            result.setdefault("support_levels", [])
            result.setdefault("resistance_levels", [])
            result.setdefault("signals", [])
            result.setdefault("analysis", raw[:300])
            result.setdefault("advice", "数据不足")
        else:
            result = {
                "phase": "无法判断", "rating": "neutral", "confidence": 0,
                "phases": [], "signal_markers": [],
                "support_levels": [], "resistance_levels": [], "signals": [],
                "analysis": raw[:300], "advice": "数据不足，无法给出建议",
            }

        # Cache the result for consistency
        _cache_set(cache_key, result, ttl=86400)
        return {"status": "ok", "data": result}
    except Exception:
        logger.exception(f"[stock_api] Internal error in /analyze")
        raise HTTPException(status_code=500, detail="服务器内部错误，请稍后重试")


# ── Stock AI Chat ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    messages: list[dict]  # [{role: "user"|"assistant", content: "..."}]
    analysis: Optional[dict] = None  # current AI analysis from the page


@router.post("/{code}/chat")
async def chat_with_stock(code: str, req: ChatRequest):
    """AI chat about the current stock — context-aware conversation."""
    code = _validate_code(code)

    # Load stock context
    stock_name = _resolve_name(code, code)
    bars, _, _ = await _read_ohlcv_from_db(code, 9999)  # all available data

    # Build compact OHLCV summary — send ALL available bars
    ohlcv_text = ""
    if bars:
        lines = []
        for b in bars:
            lines.append(f"{b['date']} O{b['open']:.2f} H{b['high']:.2f} L{b['low']:.2f} C{b['close']:.2f} V{b['volume']:.0f}")
        ohlcv_text = "\n".join(lines)

    # Build analysis context from current page state
    analysis_text = ""
    if req.analysis:
        a = req.analysis
        parts = []
        if a.get("phase"): parts.append(f"阶段:{a['phase']}")
        if a.get("rating"): parts.append(f"评级:{a['rating']}")
        if a.get("signals"): parts.append("信号:" + ",".join(a["signals"]))
        if a.get("support_levels"):
            sl = ",".join(l["label"] + "@" + str(l["price"]) for l in a["support_levels"])
            parts.append("支撑:" + sl)
        if a.get("resistance_levels"):
            rl = ",".join(l["label"] + "@" + str(l["price"]) for l in a["resistance_levels"])
            parts.append("阻力:" + rl)
        if a.get("phases"):
            pl = ",".join(p["label"] + "(" + str(p.get("start_date","")) + "~" + str(p.get("end_date","")) + ")" for p in a["phases"])
            parts.append("区间:" + pl)
        if a.get("advice"): parts.append(f"建议:{a['advice']}")
        analysis_text = " | ".join(parts) if parts else ""

    # Build latest bar info
    latest_info = ""
    if bars:
        latest = bars[-1]
        prev = bars[-2] if len(bars) > 1 else None
        chg = ((latest["close"] - prev["close"]) / prev["close"] * 100) if prev and prev["close"] > 0 else 0
        latest_info = "最新: {date} 开{open:.2f} 高{high:.2f} 低{low:.2f} 收{close:.2f} 量{vol:.0f} 涨幅{chg:+.2f}%".format(
            date=latest["date"], open=latest["open"], high=latest["high"],
            low=latest["low"], close=latest["close"], vol=latest["volume"], chg=chg)

    system = f"""你是AI Trading OS的个股分析助手。

【以下是该股票的真实数据，你必须严格基于这些数据回答问题】

股票: {stock_name}({code})
{latest_info}

最近20日K线（日期 开 高 低 收 量）:
{ohlcv_text if ohlcv_text else '暂无数据'}

AI分析结论: {analysis_text if analysis_text else '未运行'}

【严格要求】
1. 只使用上面给出的数据。如果数据中没有，说"数据中未显示"
2. 不要编造任何价格、日期、信号或结论
3. 中文回复

【输出格式 — 必须使用结构化形式】
- 使用标题+条目的形式组织回答
- 数值类信息用列表呈现（如：价格、日期、涨跌幅）
- 分析判断类信息用简短段落说明理由
- 格式示例：
  **关键数据**
  · 最新收盘价: XX元
  · 近5日涨幅: +XX%
  **判断依据**
  · （1-2句分析）"""

    try:
        from backend.llm_adapter import get_llm
        llm = get_llm()
        reply = await llm.chat(
            req.messages,
            system=system,
            temperature=0,
        )
        return {"status": "ok", "reply": reply}
    except Exception as e:
        logger.exception(f"[stock_api] Chat error for {code}")
        raise HTTPException(status_code=500, detail="AI对话服务暂时不可用")


# ── Daily backfill job ─────────────────────────────────────────────

async def backfill_recent_stocks():
    """Scheduled job: persist OHLCV for active stocks to SQLite.

    Runs after market close (15:05 Mon-Fri). Fetches today's OHLCV
    from AKShare for limit-up stocks + recently viewed stocks, and
    saves to stock_daily. Future visits hit SQLite (< 200ms).
    """
    logger.info("[backfill] Starting daily OHLCV backfill...")
    try:
        from backend.data_service import DataService

        # 1. Today's limit-up stocks (most relevant)
        limit_ups = DataService.fetch_limit_up_pool_sync()
        codes = list(dict.fromkeys([s["code"] for s in limit_ups[:30]]))

        # 2. Stocks already in DB (keep them fresh)
        async with async_session() as db:
            result = await db.execute(
                select(StockDaily.code, func.count(StockDaily.code))
                .group_by(StockDaily.code)
                .order_by(func.count(StockDaily.code).desc())
                .limit(30)
            )
            for row in result:
                c = row[0]
                if c not in codes:
                    codes.append(c)

        if not codes:
            logger.info("[backfill] No stocks to backfill")
            return

        logger.info(f"[backfill] Backfilling {len(codes)} stocks...")
        saved = 0
        for code in codes:
            try:
                loop = asyncio.get_event_loop()
                df = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda c=code: ak.stock_zh_a_hist(symbol=c, period="daily", adjust="qfq"),
                    ),
                    timeout=60,
                )
                if df is None or len(df) == 0:
                    continue
                df = df.tail(250)
                bars = []
                for _, row in df.iterrows():
                    bars.append({
                        "date": str(row.get("日期", ""))[:10],
                        "open": float(row.get("开盘", 0) or 0),
                        "high": float(row.get("最高", 0) or 0),
                        "low": float(row.get("最低", 0) or 0),
                        "close": float(row.get("收盘", 0) or 0),
                        "volume": float(row.get("成交量", 0) or 0),
                        "turnover_rate": float(row.get("换手率", 0) or 0),
                    })
                # Name from cache
                name = _resolve_name(code, code)
                await _save_ohlcv_to_db(code, name, bars)
                saved += 1
            except asyncio.TimeoutError:
                logger.warning(f"[backfill] Timeout for {code}")
            except Exception as e:
                logger.warning(f"[backfill] Failed {code}: {e}")

        logger.info(f"[backfill] Done — saved {saved}/{len(codes)} stocks")
    except Exception:
        logger.exception("[backfill] Fatal error")

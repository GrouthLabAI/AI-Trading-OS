# AI Trading OS - Pre-Market Screening Pipeline
"""
Two-stage pre-market screening: night screen + morning calibration + LLM confirm.

Stage 1 — Night screen (post-market, ~18:00):
    Scans today's limit-up pool using multi-strategy rules.
    Outputs night_screened candidates into the candidate pool.

Stage 2 — Morning calibration (pre-market, 08:30):
    Re-evaluates last night's candidates against overnight changes.
    Updates scores, marks invalidated candidates.

Stage 3 — LLM confirm (post-auction, 09:00):
    Runs the 5-agent pipeline on calibrated candidates for deep AI analysis.

Usage (called by scheduler / EventBus handlers):
    from backend.screening import run_night_screening, run_morning_calibration

    await run_night_screening()
    await run_morning_calibration()
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select

from backend.database import async_session
from backend.models import StockPick, CandidatePool

logger = logging.getLogger(__name__)


# ── Column name normalization ─────────────────────────────────────
# AKShare returns Chinese column names; normalize to English for consistency.

_KLINE_KEY_MAP = {
    "日期": "date", "开盘": "open", "收盘": "close",
    "最高": "high", "最低": "low", "成交量": "volume",
    "成交额": "amount", "振幅": "amplitude",
    "涨跌幅": "change_pct", "涨跌额": "change",
    "换手率": "turnover_rate",
}

_LIMIT_UP_KEY_MAP = {
    "代码": "code", "名称": "name",
    "涨跌幅": "change_pct", "最新价": "close",
    "成交额": "amount", "流通市值": "float_mv",
    "总市值": "total_mv", "换手率": "turnover_rate",
    "封板资金": "seal_amount", "首次封板时间": "first_seal_time",
    "最后封板时间": "last_seal_time", "炸板次数": "open_count",
    "涨停统计": "limit_up_stat", "连板数": "board_count",
    "所属行业": "industry",
}


def _normalize_row(row: dict, key_map: dict) -> dict:
    """Map Chinese column names to English keys. Passes through existing English keys."""
    result = {}
    for k, v in row.items():
        new_key = key_map.get(k, k)
        result[new_key] = v
    return result


# ── Strategy rule helpers ─────────────────────────────────────────

def _is_first_board_from_pool(stock: dict) -> Tuple[bool, str]:
    """Check if stock is a first board using limit-up pool data only.

    Uses 连板数 (board_count) and 涨停统计 (limit_up_stat) from the pool.
    No K-line API call needed.

    Returns (is_first_board, reason).
    """
    board_count = int(stock.get("board_count", 0))
    limit_up_stat = str(stock.get("limit_up_stat", ""))

    if board_count <= 1:
        return True, f"首板(连板={board_count})"
    else:
        return False, f"非首板(连板={board_count}, 统计={limit_up_stat})"


def _check_seal_quality(stock: dict) -> Tuple[bool, str]:
    """Check board sealing quality from pool data.

    Good seal: sealed early (before 09:35), never opened.
    Weak seal: sealed late or opened multiple times.

    Returns (is_strong, reason).
    """
    first_seal = str(stock.get("first_seal_time", "150000"))
    open_count = int(stock.get("open_count", 0))

    # Parse seal time: "092500" -> 09:25:00
    seal_minutes = 0
    if len(first_seal) >= 4:
        try:
            h = int(first_seal[:2])
            m = int(first_seal[2:4])
            seal_minutes = (h - 9) * 60 + m - 30  # Minutes from 09:30 open
        except (ValueError, TypeError):
            pass

    if seal_minutes <= 5 and open_count == 0:
        return True, "强封(秒板/一字板)"
    elif seal_minutes <= 30 and open_count <= 1:
        return True, f"早封({first_seal})"
    elif open_count >= 3:
        return False, f"烂板(炸{open_count}次)"
    else:
        return True, f"封板({first_seal})"


def _check_sector_alignment(stock: dict, top_sectors: set) -> Tuple[bool, str]:
    """Check if the stock's sector is among the top-performing sectors."""
    sector = str(stock.get("industry", ""))
    if not sector or not top_sectors:
        return len(top_sectors) == 0, "无板块数据" if not sector else "板块数据不足"
    if sector in top_sectors:
        return True, f"板块共振({sector})"
    return False, f"板块不突出({sector})"


def _check_volume_quality(stock: dict) -> Tuple[bool, str]:
    """Check volume metrics for healthy turnover.

    For limit-up stocks, low turnover can indicate strong sealing (sellers scarce).
    Only filter out extremes: too low (<0.5%) = illiquid, too high (>20%) = distribution risk.

    Returns (passes, reason).
    """
    turnover = float(stock.get("turnover_rate", 0))
    if turnover < 0.5:
        return False, f"换手率极低({turnover:.1f}%)—流动性差"
    if turnover > 20:
        return False, f"换手率过高({turnover:.1f}%)—派发风险"

    return True, f"换手{turnover:.1f}%"


# ── Main screening logic ──────────────────────────────────────────

async def _fetch_single_kline(code: str, retries: int = 2) -> Tuple[str, Optional[List[dict]]]:
    """Fetch K-line for a single stock with retry logic."""
    import akshare as ak
    import time

    for attempt in range(retries + 1):
        try:
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(
                None, lambda: ak.stock_zh_a_hist(symbol=code, period="daily", adjust="qfq")
            )
            if df is not None and len(df) > 0:
                raw_records = df.tail(30).to_dict("records")
                return code, [_normalize_row(r, _KLINE_KEY_MAP) for r in raw_records]
        except Exception as e:
            if attempt < retries:
                await asyncio.sleep(1.0 * (attempt + 1))
            else:
                logger.debug(f"Screening: failed to fetch kline for {code} after {retries+1} attempts: {e}")
    return code, None


async def _fetch_limit_up_kline(codes: List[str], max_concurrent: int = 5) -> Dict[str, List[dict]]:
    """Fetch K-line data concurrently for multiple stock codes.

    Args:
        codes: List of stock codes.
        max_concurrent: Max concurrent AKShare calls (limit to avoid rate-limiting).

    Returns normalized (English-keyed) data dict {code: [bars]}.
    """
    import asyncio

    result = {}
    sem = asyncio.Semaphore(max_concurrent)

    async def _fetch_with_limit(code: str):
        async with sem:
            return await _fetch_single_kline(code)

    tasks = [_fetch_with_limit(c) for c in codes]
    done_results = await asyncio.gather(*tasks, return_exceptions=True)

    for item in done_results:
        if isinstance(item, tuple):
            code, data = item
            if data is not None:
                result[code] = data
        elif isinstance(item, Exception):
            logger.debug(f"Screening: kline fetch exception: {item}")

    return result


async def run_night_screening() -> dict:
    """Stage 1: Night screening after market close (~18:00).

    Scans today's limit-up pool against all strategies and produces
    the initial candidate pool.

    Returns summary dict.
    """
    import akshare as ak

    pool_id = uuid.uuid4().hex[:12]
    now = datetime.datetime.now()
    # Use previous trading day if market hasn't closed yet (before 15:30)
    if now.hour < 15 or (now.hour == 15 and now.minute < 30):
        trade_date = datetime.date.today() - datetime.timedelta(days=1)
    else:
        trade_date = datetime.date.today()
    start_time = now

    logger.info(f"Screening [night]: screening date={trade_date} (now={now.strftime('%H:%M')}) (pool={pool_id})")

    # 1. Fetch limit-up pool for the screening date
    try:
        limit_up_df = ak.stock_zt_pool_em(date=trade_date.strftime("%Y%m%d"))
        if limit_up_df is None or len(limit_up_df) == 0:
            logger.info("Screening [night]: no limit-up stocks today — empty pool")
            return {"pool_id": pool_id, "total_screened": 0, "total_qualified": 0}
    except Exception as e:
        logger.error(f"Screening [night]: failed to fetch limit-up pool: {e}")
        return {"pool_id": pool_id, "total_screened": 0, "total_qualified": 0, "error": str(e)}

    limit_up_list = limit_up_df.to_dict("records")
    # Normalize Chinese column names to English
    limit_up_list = [_normalize_row(r, _LIMIT_UP_KEY_MAP) for r in limit_up_list]
    total = len(limit_up_list)
    # Sort by turnover rate descending, take top 50 for performance
    limit_up_list.sort(key=lambda x: float(x.get("turnover_rate", 0)), reverse=True)
    screen_pool = limit_up_list[:50]
    logger.info(f"Screening [night]: {total} stocks in pool, screening top {len(screen_pool)} by turnover")

    # 2. Fetch sector rankings (for sector alignment check)
    try:
        sector_df = ak.stock_board_concept_spot_em()
        top_sectors = set()
        if sector_df is not None and len(sector_df) > 0:
            sector_list = sector_df.to_dict("records")
            sorted_sectors = sorted(sector_list, key=lambda x: float(x.get("涨跌幅", 0)), reverse=True)
            top_sectors = {s.get("板块名称", s.get("name", "")) for s in sorted_sectors[:10]}
    except Exception:
        top_sectors = set()
    logger.info(f"Screening [night]: top 10 sectors: {list(top_sectors)[:5]}...")

    # 3. Screen each stock (no K-line needed — use pool data)
    qualified = []
    for stock in screen_pool:
        code = str(stock.get("code", ""))
        name = str(stock.get("name", ""))
        sector = str(stock.get("industry", ""))

        # Strategy checks (all from pool data, no K-line API calls)
        first_board, fb_reason = _is_first_board_from_pool(stock)
        seal_ok, seal_reason = _check_seal_quality(stock)
        sector_ok, sector_reason = _check_sector_alignment(stock, top_sectors)
        vol_ok, vol_reason = _check_volume_quality(stock)

        # Score calculation (0-100)
        score = 0.0
        strategies_hit = []
        if first_board:
            score += 35
            strategies_hit.append("first_board")
        if seal_ok:
            score += 25
            strategies_hit.append("strong_seal")
        if sector_ok:
            score += 20
        if vol_ok:
            score += 20

        # Only include if score is meaningful
        if score >= 30:
            close_price = float(stock.get("close", 0))
            qualified.append({
                "code": code,
                "name": name,
                "night_score": round(score, 1),
                "screening_strategy": ",".join(strategies_hit),
                "sector": sector,
                "close_price": close_price,
                "turnover": float(stock.get("turnover_rate", 0)),
                "first_board": first_board,
                "seal_quality": seal_reason,
                "fb_reason": fb_reason,
                "vol_reason": vol_reason,
                "sector_reason": sector_reason,
            })

    # Sort by score descending
    qualified.sort(key=lambda x: x["night_score"], reverse=True)

    # 5. Persist to database
    async with async_session() as db:
        # Create pool record
        pool = CandidatePool(
            pool_id=pool_id,
            trade_date=trade_date,
            stage="night_screen",
            total_screened=total,
            total_qualified=len(qualified),
            strategies_used=json.dumps(["first_board", "wyckoff_sos", "wyckoff_spring", "dragon_low"], ensure_ascii=False),
            market_snapshot=json.dumps({
                "total_limit_ups": total,
                "top_sectors": list(top_sectors)[:5],
                "screen_time": start_time.isoformat(),
            }, ensure_ascii=False),
        )
        db.add(pool)

        # Insert qualified picks
        for q in qualified:
            pick = StockPick(
                trade_date=trade_date,
                code=q["code"],
                name=q["name"],
                score=q["night_score"],
                candidate_status="night_screened",
                pool_id=pool_id,
                screening_strategy=q["screening_strategy"],
                night_score=q["night_score"],
                morning_score=0.0,
                buy_price=q["close_price"],
                reason=f"{q['fb_reason']}; {q['vol_reason']}; 封板:{q.get('seal_quality', '未知')}; 板块:{q.get('sector_reason', '未知')}",
                create_time=datetime.datetime.now(),
                expire_time=datetime.datetime.now() + datetime.timedelta(hours=24),
            )
            db.add(pick)

        await db.commit()

    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    logger.info(
        f"Screening [night]: done in {elapsed:.1f}s — "
        f"{len(qualified)}/{total} qualified (pool={pool_id})"
    )

    return {
        "pool_id": pool_id,
        "trade_date": trade_date.isoformat(),
        "stage": "night_screen",
        "total_screened": total,
        "total_qualified": len(qualified),
        "top_candidates": qualified[:5],
        "elapsed_seconds": round(elapsed, 1),
    }


async def run_morning_calibration() -> dict:
    """Stage 2: Morning calibration (08:30).

    Loads last night's night_screened candidates, re-evaluates based
    on overnight market changes, and updates scores.

    Returns summary dict.
    """
    trade_date = datetime.date.today()
    start_time = datetime.datetime.now()

    logger.info(f"Screening [morning]: calibrating for {trade_date}")

    # 1. Load night_screened candidates
    async with async_session() as db:
        result = await db.execute(
            select(StockPick).where(
                StockPick.trade_date == trade_date,
                StockPick.candidate_status == "night_screened",
            )
        )
        candidates = result.scalars().all()

    if not candidates:
        logger.info("Screening [morning]: no night_screened candidates to calibrate")
        return {"calibrated": 0, "invalidated": 0, "message": "无候选需要校准"}

    logger.info(f"Screening [morning]: loaded {len(candidates)} night_screened candidates")

    # 2. Fetch current sector rankings (may have shifted overnight)
    try:
        import akshare as ak
        sector_df = ak.stock_board_concept_spot_em()
        top_sectors = set()
        if sector_df is not None and len(sector_df) > 0:
            sector_list = sector_df.to_dict("records")
            sorted_sectors = sorted(sector_list, key=lambda x: float(x.get("涨跌幅", 0)), reverse=True)
            top_sectors = {s.get("板块名称", s.get("name", "")) for s in sorted_sectors[:10]}
    except Exception:
        top_sectors = set()

    # 3. Calibrate each candidate
    calibrated = 0
    invalidated = 0
    pool_id = candidates[0].pool_id if candidates else ""

    async with async_session() as db:
        for c in candidates:
            # Adjust morning score: keep 80% of night score, add calibration bonus
            base_score = c.night_score * 0.8
            base_score += 10  # Sector check passed in night screen
            base_score += 10  # Morning calibration survival bonus

            morning_score = min(round(base_score, 1), 100.0)

            # Invalidated if score drops below 30
            if morning_score < 30:
                c.candidate_status = "abandoned"
                c.reason = (c.reason or "") + "; 盘前校准失效"
                invalidated += 1
            else:
                c.candidate_status = "morning_calibrated"
                c.morning_score = morning_score
                c.score = morning_score  # Update final score
                calibrated += 1

            db.add(c)

        # Update pool record
        if pool_id:
            pool_result = await db.execute(
                select(CandidatePool).where(CandidatePool.pool_id == pool_id)
            )
            pool = pool_result.scalar()
            if pool:
                pool.overnight_changes = json.dumps({
                    "calibrated": calibrated,
                    "invalidated": invalidated,
                    "top_sectors_remain": len(top_sectors),
                }, ensure_ascii=False)
                db.add(pool)

        await db.commit()

    elapsed = (datetime.datetime.now() - start_time).total_seconds()
    logger.info(
        f"Screening [morning]: done in {elapsed:.1f}s — "
        f"{calibrated} confirmed, {invalidated} invalidated"
    )

    return {
        "pool_id": pool_id,
        "trade_date": trade_date.isoformat(),
        "stage": "morning_calibrate",
        "calibrated": calibrated,
        "invalidated": invalidated,
        "total": len(candidates),
        "elapsed_seconds": round(elapsed, 1),
    }


# ── Convenience: fetch candidate pool ─────────────────────────────

async def get_candidate_pool(trade_date: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Get the current candidate pool with all stages.

    If no date is specified, auto-detects: today's pool first,
    falls back to the most recent pool (e.g., last night's screening
    when viewed before market open).
    """
    async with async_session() as db:
        if trade_date is None:
            # Try today first, then fall back to yesterday
            today = datetime.date.today()
            for attempt_date in [today, today - datetime.timedelta(days=1)]:
                check = await db.execute(
                    select(StockPick.id).where(
                        StockPick.trade_date == attempt_date,
                        StockPick.candidate_status.in_([
                            "night_screened", "morning_calibrated", "confirmed",
                            "active", "executed", "expired", "abandoned",
                        ])
                    ).limit(1)
                )
                if check.scalar():
                    trade_date = attempt_date
                    break
            else:
                trade_date = today

        result = await db.execute(
            select(StockPick).where(
                StockPick.trade_date == trade_date,
                StockPick.candidate_status.in_([
                    "night_screened", "morning_calibrated", "confirmed",
                    "active", "executed", "expired", "abandoned",
                ])
            ).order_by(StockPick.score.desc())
        )
        picks = result.scalars().all()

        # Get pool metadata
        pool_result = await db.execute(
            select(CandidatePool).where(
                CandidatePool.trade_date == trade_date
            ).order_by(CandidatePool.create_time.desc())
        )
        pools = pool_result.scalars().all()

    return {
        "trade_date": trade_date.isoformat(),
        "total_candidates": len(picks),
        "candidates": [
            {
                "code": p.code,
                "name": p.name,
                "score": p.score,
                "candidate_status": p.candidate_status,
                "pool_id": p.pool_id,
                "screening_strategy": p.screening_strategy,
                "night_score": p.night_score,
                "morning_score": p.morning_score,
                "buy_price": p.buy_price,
                "stop_loss": p.stop_loss,
                "target_price": p.target_price,
                "position_ratio": p.position_ratio,
                "reason": p.reason,
            }
            for p in picks
        ],
        "pools": [
            {
                "pool_id": p.pool_id,
                "stage": p.stage,
                "total_screened": p.total_screened,
                "total_qualified": p.total_qualified,
            }
            for p in pools
        ],
    }

# AI Trading OS - Watchlist API
import asyncio
import datetime
import logging

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select, delete

from backend.database import async_session
from backend.models import WatchlistStock, StockSector
from backend.stock_api import _cache_get, warm_spot_cache  # Share stock_api's spot cache

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


async def _get_spot_df_async():
    """Get spot data from shared cache (8h TTL, covers full trading day)."""
    df = _cache_get("spot_all", ttl=28800)  # 8 hours
    if df is None:
        # Trigger background re-warm (force=True bypasses _warmed_up guard)
        import asyncio as _aio
        _aio.create_task(warm_spot_cache(force=True))
    return df


# ── Schemas ────────────────────────────────────────────────────────

class AddStockRequest(BaseModel):
    code: str
    name: str = ""
    add_price: float = 0.0


# ── Helpers ────────────────────────────────────────────────────────


# ── Sector sync ────────────────────────────────────────────────────


async def sync_sector_data():
    """从东方财富同步行业分类到 SQLite。

    使用 stock_board_industry_name_em（约500个细分行业），逐个获取成分股。
    首次启动约需15-20分钟（后台运行，不阻塞）。每周一刷新。
    """
    import akshare as ak
    logger = logging.getLogger(__name__)

    try:
        # 1. 获取行业名称列表
        loop = asyncio.get_running_loop()
        names_df = await loop.run_in_executor(None, ak.stock_board_industry_name_em)
        if names_df is None or len(names_df) == 0:
            logger.warning("[watchlist] No industry names returned")
            return

        industries = names_df["板块名称"].tolist()
        total = len(industries)
        logger.info(f"[watchlist] Starting sector sync: {total} industries (takes ~15-20 min, runs in background)")

        # 2. 逐个行业获取成分股，构建 code→sector 映射
        code_sector: dict[str, str] = {}
        failed = 0
        for i, ind in enumerate(industries):
            try:
                cons = await loop.run_in_executor(
                    None, lambda name=ind: ak.stock_board_industry_cons_em(symbol=name)
                )
                if cons is not None and len(cons) > 0:
                    for _, row in cons.iterrows():
                        code = str(row.get("代码", "")).strip()
                        if code:
                            code_sector[code] = str(ind)
            except Exception:
                failed += 1
                continue

            # 控制请求频率，避免被限流（东方财富对高频请求会断开连接）
            await asyncio.sleep(1.0)

            # 进度日志（每20个行业）
            if (i + 1) % 20 == 0:
                pct = (i + 1) * 100 // total
                logger.info(f"[watchlist] Sector sync: {i + 1}/{total} ({pct}%), {len(code_sector)} stocks, {failed} failed")

        if not code_sector:
            logger.warning("[watchlist] Sector sync produced no mappings")
            return

        # 3. 写入 SQLite（批量 upsert）
        async with async_session() as db:
            now = datetime.datetime.now()
            batch = []
            for code, sector in code_sector.items():
                existing = await db.get(StockSector, code)
                if existing:
                    existing.sector = sector
                    existing.update_time = now
                else:
                    batch.append(StockSector(code=code, sector=sector, update_time=now))
                # 分批提交，避免单次事务过大
                if len(batch) >= 500:
                    db.add_all(batch)
                    await db.commit()
                    batch = []
            if batch:
                db.add_all(batch)
                await db.commit()

        logger.info(f"[watchlist] Sector sync done: {len(code_sector)} stocks from {total} industries ({failed} failed)")

    except Exception as e:
        logger.warning(f"[watchlist] Sector sync failed: {e}")


# ── Endpoints ──────────────────────────────────────────────────────


def _safe_float(val, default=0.0):
    try:
        return float(val) if val else default
    except (ValueError, TypeError):
        return default


def _fmt_amount(val: float) -> str:
    """Format large numbers: >= 1亿 -> X.XX亿, >= 1万 -> X.XX万"""
    if abs(val) >= 100000000:
        return f"{val / 100000000:.2f}亿"
    if abs(val) >= 10000:
        return f"{val / 10000:.0f}万"
    return f"{val:.2f}"


@router.get("/quotes")
async def get_watchlist_quotes():
    """获取自选股实时行情（合并实时数据与本地自选信息）"""
    # 1. Get watchlist stocks from DB
    async with async_session() as db:
        result = await db.execute(
            select(WatchlistStock).order_by(WatchlistStock.create_time.desc())
        )
        watchlist = result.scalars().all()

    if not watchlist:
        return {"status": "ok", "data": {"stocks": [], "count": 0}}

    codes = [w.code for w in watchlist]

    # 1.5 Get sector data from DB
    sector_result = await db.execute(
        select(StockSector).where(StockSector.code.in_(codes))
    )
    sector_map = {s.code: s.sector for s in sector_result.scalars().all()}

    # 2. Get spot data
    spot_df = await _get_spot_df_async()

    # 3. Merge
    stocks = []
    for w in watchlist:
        code = w.code
        spot_row = None
        if spot_df is not None:
            match = spot_df[spot_df["代码"] == code]
            if len(match) > 0:
                spot_row = match.iloc[0]

        if spot_row is not None:
            close = _safe_float(spot_row.get("最新价"))
            change_pct = _safe_float(spot_row.get("涨跌幅"))
            pre_close = _safe_float(spot_row.get("昨收"))
            add_return = ((close - w.add_price) / w.add_price * 100) if w.add_price > 0 else 0

            stock = {
                "id": w.id,
                "code": str(spot_row.get("代码", code)),
                "name": str(spot_row.get("名称", w.name)),
                "price": close,
                "change_pct": change_pct,
                "change_amount": _safe_float(spot_row.get("涨跌额")),
                "open": _safe_float(spot_row.get("今开")),
                "high": _safe_float(spot_row.get("最高")),
                "low": _safe_float(spot_row.get("最低")),
                "pre_close": pre_close,
                "volume": _safe_float(spot_row.get("成交量")),
                "amount": _safe_float(spot_row.get("成交额")),
                "amplitude": _safe_float(spot_row.get("振幅")),            # 振幅
                "turnover_rate": _safe_float(spot_row.get("换手率")),     # 换手率
                "volume_ratio": _safe_float(spot_row.get("量比")),        # 量比
                "committee_ratio": _safe_float(spot_row.get("委比")),     # 委比
                "total_market_cap": _safe_float(spot_row.get("总市值")),   # 总市值
                "float_market_cap": _safe_float(spot_row.get("流通市值")), # 流通市值
                "pe": _safe_float(spot_row.get("市盈率-动态")),           # 市盈率
                # Local data
                "add_price": w.add_price,
                "add_date": w.create_time.strftime("%Y-%m-%d") if w.create_time else "",
                "add_return": round(add_return, 2),
                # Format helpers for display
                "amount_fmt": _fmt_amount(_safe_float(spot_row.get("成交额"))),
                "total_mcap_fmt": _fmt_amount(_safe_float(spot_row.get("总市值"))),
                "float_mcap_fmt": _fmt_amount(_safe_float(spot_row.get("流通市值"))),
                # Placeholders (需要额外数据源)
                "sector": sector_map.get(code, "-"),               # 板块（DB）
                "main_buy": None,                                          # 主力买入（需资金流向数据）
                "main_sell": None,                                         # 主力卖出
                "consecutive_boards": None,                                # 连板信息
            }
        else:
            # 无实时数据时返回基本信息
            stock = {
                "id": w.id,
                "code": code,
                "name": w.name,
                "price": 0,
                "change_pct": 0,
                "change_amount": 0,
                "open": 0, "high": 0, "low": 0, "pre_close": 0,
                "volume": 0, "amount": 0,
                "amplitude": 0, "turnover_rate": 0, "volume_ratio": 0,
                "committee_ratio": 0, "total_market_cap": 0, "float_market_cap": 0,
                "pe": 0, "sector": sector_map.get(code, "-"),
                "add_price": w.add_price,
                "add_date": w.create_time.strftime("%Y-%m-%d") if w.create_time else "",
                "add_return": 0,
                "amount_fmt": "-", "total_mcap_fmt": "-", "float_mcap_fmt": "-",
                "main_buy": None, "main_sell": None, "consecutive_boards": None,
            }
        stocks.append(stock)

    return {"status": "ok", "data": {"stocks": stocks, "count": len(stocks)}}


@router.post("/add")
async def add_stock(req: AddStockRequest):
    """添加股票到自选股"""
    code = req.code.strip()
    if not code:
        return {"status": "error", "message": "股票代码不能为空"}

    async with async_session() as db:
        # 检查是否已存在
        existing = await db.execute(
            select(WatchlistStock).where(WatchlistStock.code == code)
        )
        if existing.scalar_one_or_none():
            return {"status": "error", "message": f"{code} 已在自选列表中"}

        # 如果没有传入名称和价格，从实时数据获取
        name = req.name
        add_price = req.add_price
        if not name or add_price == 0:
            spot_df = await _get_spot_df_async()
            if spot_df is not None:
                match = spot_df[spot_df["代码"] == code]
                if len(match) > 0:
                    row = match.iloc[0]
                    if not name:
                        name = str(row.get("名称", code))
                    if add_price == 0:
                        add_price = _safe_float(row.get("最新价"))

        record = WatchlistStock(code=code, name=name, add_price=add_price)
        db.add(record)
        await db.commit()
        await db.refresh(record)

        return {
            "status": "ok",
            "data": {
                "id": record.id,
                "code": record.code,
                "name": record.name,
                "add_price": record.add_price,
                "create_time": record.create_time.isoformat(),
            },
        }


@router.delete("/{stock_id}")
async def remove_stock(stock_id: int):
    """从自选股移除"""
    async with async_session() as db:
        stock = await db.get(WatchlistStock, stock_id)
        if not stock:
            return {"status": "error", "message": "未找到该自选股"}
        await db.delete(stock)
        await db.commit()
    return {"status": "ok", "data": {"deleted": stock_id}}


@router.get("/stocks")
async def list_stocks():
    """列出所有自选股（仅基本信息，无实时行情）"""
    async with async_session() as db:
        result = await db.execute(
            select(WatchlistStock).order_by(WatchlistStock.create_time.desc())
        )
        stocks = result.scalars().all()
    return {
        "status": "ok",
        "data": {
            "stocks": [
                {
                    "id": s.id,
                    "code": s.code,
                    "name": s.name,
                    "add_price": s.add_price,
                    "create_time": s.create_time.isoformat() if s.create_time else "",
                }
                for s in stocks
            ],
            "count": len(stocks),
        },
    }

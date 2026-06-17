# AI Trading OS - Backtest API
from __future__ import annotations

import re
from typing import Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from strategies.sample_strategies import STRATEGY_REGISTRY
from strategies.backtest_engine import BacktestEngine

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


def _parse_codes(codes_str: str) -> list[str]:
    """Parse comma/space/newline separated stock codes."""
    return [c.strip() for c in re.split(r'[,\s\n]+', codes_str) if c.strip()]


class BacktestRequest(BaseModel):
    codes: str = ""
    strategies: list[str] = ["first_board"]
    cash: float = 100000
    start_date: str = "2025-06-15"
    end_date: str = "2026-06-15"
    params: dict = {}
    optimize: bool = False
    optimize_params: Optional[dict] = None

class ReportRequest(BaseModel):
    codes: str = ""
    strategies: list[str] = ["first_board"]
    cash: float = 100000
    start_date: str = "2025-06-15"
    end_date: str = "2026-06-15"
    params: dict = {}

class HtmlRequest(BaseModel):
    code: str = ""
    strategy: str = "first_board"
    cash: float = 100000
    start_date: str = "2025-06-15"
    end_date: str = "2026-06-15"
    params: dict = {}


@router.get("/strategies")
async def list_strategies():
    result = {}
    for key, info in STRATEGY_REGISTRY.items():
        result[key] = {"name": info["name"], "description": info["description"], "params": info["params"]}
    return {"status": "ok", "strategies": result}


@router.post("/run")
async def run_backtest(req: BacktestRequest):
    codes = _parse_codes(req.codes)
    if not codes:
        raise HTTPException(status_code=400, detail="请提供至少一个股票代码")
    all_results = []
    for code in codes:
        stock_results = []
        for key in req.strategies:
            info = STRATEGY_REGISTRY.get(key)
            if not info:
                stock_results.append({"strategy": key, "error": f"未知策略"})
                continue
            cls = info["class"]
            vp = {k: v for k, v in req.params.items() if hasattr(cls, k)}
            try:
                if req.optimize and req.optimize_params:
                    result = BacktestEngine.optimize(
                        code=code, strategy_cls=cls, cash=req.cash,
                        start_date=req.start_date, end_date=req.end_date,
                        param_ranges=req.optimize_params)
                else:
                    result = BacktestEngine.run(
                        code=code, strategy_cls=cls, cash=req.cash,
                        start_date=req.start_date, end_date=req.end_date, **vp)
                if "error" in result:
                    stock_results.append({"strategy": key, "error": result["error"]})
                else:
                    stock_results.append({"strategy": key, "name": info["name"], "data": result})
            except Exception as e:
                stock_results.append({"strategy": key, "error": str(e)})
        all_results.append({"code": code, "results": stock_results})
    return {"status": "ok", "stocks": all_results}


@router.post("/report/html")
async def generate_html_report(req: ReportRequest):
    codes = _parse_codes(req.codes)
    key = req.strategies[0] if req.strategies else "first_board"
    info = STRATEGY_REGISTRY.get(key)
    if not info: raise HTTPException(status_code=400, detail=f"未知策略: {key}")
    vp = {k: v for k, v in req.params.items() if hasattr(info["class"], k)}
    filepath = BacktestEngine.generate_html(
        code=codes[0] if codes else "002636", strategy_name=key,
        strategy_cls=info["class"], cash=req.cash,
        start_date=req.start_date, end_date=req.end_date, **vp)
    return {"status": "ok", "filepath": filepath}


@router.post("/report/feishu")
async def push_to_feishu(req: ReportRequest):
    codes = _parse_codes(req.codes)
    for code in codes:
        for key in req.strategies:
            info = STRATEGY_REGISTRY.get(key)
            if not info: continue
            vp = {k: v for k, v in req.params.items() if hasattr(info["class"], k)}
            result = BacktestEngine.run(
                code=code, strategy_cls=info["class"], cash=req.cash,
                start_date=req.start_date, end_date=req.end_date, **vp)
            if "error" not in result:
                try:
                    from backend.feishu import FeishuBitable
                    fb = FeishuBitable()
                    s = result["stats"]
                    await fb.send_backtest_card(
                        code=code, strategy=info["name"], return_pct=s["return_pct"],
                        win_rate=s["win_rate_pct"], max_dd=s["max_drawdown_pct"],
                        sharpe=s["sharpe_ratio"], trades=s["total_trades"],
                        date_range=result["date_range"])
                except: pass
    return {"status": "ok", "message": "已推送到飞书"}


@router.post("/report/html-content")
async def get_html_content(req: HtmlRequest):
    info = STRATEGY_REGISTRY.get(req.strategy)
    if not info: raise HTTPException(status_code=400, detail=f"未知策略: {req.strategy}")
    vp = {k: v for k, v in req.params.items() if hasattr(info["class"], k)}
    try: return HTMLResponse(content=BacktestEngine.generate_thsc_chart(
        code=req.code, strategy_name=info["name"], strategy_cls=info["class"],
        cash=req.cash, start_date=req.start_date, end_date=req.end_date, **vp))
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))


@router.post("/report/chart-image")
async def get_chart_image(req: HtmlRequest):
    info = STRATEGY_REGISTRY.get(req.strategy)
    if not info: raise HTTPException(status_code=400, detail=f"未知策略: {req.strategy}")
    vp = {k: v for k, v in req.params.items() if hasattr(info["class"], k)}
    try: return HTMLResponse(content=BacktestEngine.generate_thsc_chart(
        code=req.code, strategy_name=info["name"], strategy_cls=info["class"],
        cash=req.cash, start_date=req.start_date, end_date=req.end_date, **vp))
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

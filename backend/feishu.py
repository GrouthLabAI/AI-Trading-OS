# AI Trading OS - Feishu Bitable Integration
"""
Syncs trading plans and review reports to Feishu Bitable (多维表格).

Setup:
    1. Create a Feishu app at https://open.feishu.cn/app
    2. Get App ID + App Secret from "Credentials"
    3. Enable Bitable permission in "Permissions"
    4. Create a Bitable document, get its token from the URL
    5. Set env vars in .env

Feishu doc URL: https://xxx.feishu.cn/base/BITABLE_TOKEN?table=tblXXX
                                              ^^^^^^^^^^^^
                                              This is your bitable_id

Usage:
    from backend.feishu import FeishuBitable
    fb = FeishuBitable()
    await fb.insert_trade_plan(...)
    await fb.insert_review(...)
"""

from __future__ import annotations

import datetime
import json
import time
import calendar
from typing import Optional

import httpx

from backend.config import settings


# ── Configuration ────────────────────────────────────────────────────

class FeishuConfig:
    APP_ID = getattr(settings, "feishu_app_id", "")
    APP_SECRET = getattr(settings, "feishu_app_secret", "")
    BITABLE_ID = getattr(settings, "feishu_bitable_id", "")
    # Table IDs (get from Bitable URL: ?table=tblXXX)
    TABLE_TRADE_PLAN = getattr(settings, "feishu_table_trade_plan", "")
    TABLE_REVIEW = getattr(settings, "feishu_table_review", "")


# ── API Client ──────────────────────────────────────────────────────

class FeishuClient:
    """Low-level Feishu API client with token management."""

    BASE = "https://open.feishu.cn/open-apis"

    def __init__(self, app_id: str = "", app_secret: str = ""):
        self.app_id = app_id or FeishuConfig.APP_ID
        self.app_secret = app_secret or FeishuConfig.APP_SECRET
        self._token: str = ""
        self._token_expires: float = 0

    # ── Auth ──────────────────────────────────────────────────────

    async def _ensure_token(self):
        """Fetch or refresh tenant access token."""
        if self._token and time.time() < self._token_expires - 60:
            return

        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.BASE}/auth/v3/tenant_access_token/internal",
                json={
                    "app_id": self.app_id,
                    "app_secret": self.app_secret,
                },
                timeout=10,
            )
            data = r.json()
            if data.get("code") != 0:
                raise Exception(f"Feishu auth failed: {data}")
            self._token = data["tenant_access_token"]
            self._token_expires = time.time() + data.get("expire", 7200)

    # ── HTTP helpers ──────────────────────────────────────────────

    async def _get(self, path: str, params: dict = None) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            r = await client.get(
                f"{self.BASE}{path}",
                headers={"Authorization": f"Bearer {self._token}"},
                params=params,
                timeout=15,
            )
            return r.json()

    async def _post(self, path: str, body: dict) -> dict:
        await self._ensure_token()
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{self.BASE}{path}",
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=15,
            )
            return r.json()


# ── Bitable Operations ──────────────────────────────────────────────

class FeishuBitable:
    """High-level operations on Feishu Bitable tables."""

    def __init__(self, bitable_id: str = ""):
        self.client = FeishuClient()
        self.bitable_id = bitable_id or FeishuConfig.BITABLE_ID

    # ── Table helpers ─────────────────────────────────────────────

    async def list_tables(self) -> list[dict]:
        """List all tables in the Bitable document."""
        r = await self.client._get(
            f"/bitable/v1/apps/{self.bitable_id}/tables"
        )
        if r.get("code") != 0:
            raise Exception(f"List tables failed: {r}")
        items = r.get("data", {}).get("items", [])
        return [{"name": i["name"], "table_id": i["table_id"]} for i in items]

    async def get_fields(self, table_id: str) -> list[dict]:
        """Get field definitions for a table."""
        r = await self.client._get(
            f"/bitable/v1/apps/{self.bitable_id}/tables/{table_id}/fields"
        )
        return r.get("data", {}).get("items", [])

    async def insert_record(self, table_id: str, fields: dict) -> dict:
        """Insert a single record into a table."""
        r = await self.client._post(
            f"/bitable/v1/apps/{self.bitable_id}/tables/{table_id}/records",
            {"fields": fields},
        )
        if r.get("code") != 0:
            raise Exception(f"Insert failed: {r}")
        return r.get("data", {}).get("record", {})

    async def insert_records(self, table_id: str, records: list[dict]) -> dict:
        """Batch insert records."""
        r = await self.client._post(
            f"/bitable/v1/apps/{self.bitable_id}/tables/{table_id}/records/batch_create",
            {"records": [{"fields": f} for f in records]},
        )
        if r.get("code") != 0:
            raise Exception(f"Batch insert failed: {r}")
        return r.get("data", {})

    # ── Trade Plan operations ─────────────────────────────────────

    @staticmethod
    def _date_val() -> int:
        """Feishu Date field expects Unix timestamp in milliseconds."""
        today = datetime.date.today()
        dt = datetime.datetime(today.year, today.month, today.day)
        return int(calendar.timegm(dt.timetuple()) * 1000)

    async def insert_trade_plan(
        self,
        code: str,
        name: str,
        action: str,          # "买入" / "卖出"
        price: float,
        quantity: int,
        score: int = 0,
        category: str = "",
        buy_price: float = 0,
        stop_loss: float = 0,
        target_price: float = 0,
        position_ratio: str = "",
        reason: str = "",
        emotion_phase: str = "",
        main_theme: str = "",
        risk_level: str = "",
        table_id: str = "",
    ) -> dict:
        tid = table_id or FeishuConfig.TABLE_TRADE_PLAN
        return await self.insert_record(tid, {
            "日期": self._date_val(),
            "│ 股票代码": code,
            "股票名称": name,
            "操作": action,
            "价格": price,
            "数量": quantity,
            "AI评分": score,
            "类型": category,
            "买入参考价": buy_price if buy_price else price,
            "止损价": stop_loss if stop_loss else round(price * 0.95, 2),
            "目标价": target_price if target_price else round(price * 1.10, 2),
            "仓位": position_ratio,
            "推荐理由": reason[:500] if reason else "",
            "市场情绪": emotion_phase,
            "│ 主线方向": main_theme,
            "风险等级": risk_level,
        })

    async def insert_trade_plan_batch(
        self, picks: list[dict], emotion_phase: str = "",
        main_theme: str = "", risk_level: str = "", table_id: str = "",
    ) -> dict:
        """Batch insert multiple trade plans from AI picks."""
        tid = table_id or FeishuConfig.TABLE_TRADE_PLAN
        records = []
        for p in picks:
            records.append({
                "日期": self._date_val(),
                "│ 股票代码": p.get("code", ""),
                "股票名称": p.get("name", ""),
                "操作": "买入",
                "价格": p.get("buy_price", 0),
                "数量": 100,
                "AI评分": p.get("score", 0),
                "类型": p.get("category", ""),
                "买入参考价": p.get("buy_price", 0),
                "止损价": p.get("stop_loss", 0),
                "目标价": p.get("target_price", 0),
                "仓位": p.get("position_ratio", ""),
                "推荐理由": p.get("reason", "")[:500],
                "市场情绪": emotion_phase,
                "│ 主线方向": main_theme,
                "风险等级": risk_level,
            })
        if records:
            return await self.insert_records(tid, records)
        return {}

    # ── Review operations ──────────────────────────────────────────

    async def insert_review(
        self,
        win_rate: float,
        total_trades: int,
        wins: int,
        losses: int,
        total_profit: float,
        biggest_mistake: str = "",
        strategy_review: str = "",
        improvement_plan: str = "",
        suggestions: str = "",
        table_id: str = "",
    ) -> dict:
        tid = table_id or FeishuConfig.TABLE_REVIEW
        return await self.insert_record(tid, {
            "日期": self._date_val(),
            "总交易数": total_trades,
            "盈利次数": wins,
            "亏损次数": losses,
            "胜率": f"{win_rate}%",
            "总盈亏": total_profit,
            "最大问题": biggest_mistake[:200] if biggest_mistake else "",
            "策略评价": strategy_review[:300] if strategy_review else "",
            "改进计划": improvement_plan[:300] if improvement_plan else "",
            "改进建议": suggestions[:500] if suggestions else "",
        })

    # ── Backtest report card ─────────────────────────────────────

    async def send_backtest_card(
        self, code: str, strategy: str, return_pct: float,
        win_rate: float, max_dd: float, sharpe: float,
        trades: int, date_range: str,
    ) -> dict:
        """Send backtest summary card to Feishu."""
        from backend.notify import Notifier
        n = Notifier()
        emoji = "🟢" if return_pct > 0 else "🔴"
        await n.send_card(
            title=f"{emoji} 回测报告: {code} {strategy}",
            fields={
                "股票": code,
                "策略": strategy,
                "区间": date_range,
                "收益率": f"{return_pct:+.1f}%",
                "胜率": f"{win_rate:.1f}%",
                "最大回撤": f"{max_dd:.1f}%",
                "夏普比率": f"{sharpe:.2f}",
                "交易次数": str(trades),
            },
        )
        return {"status": "ok"}

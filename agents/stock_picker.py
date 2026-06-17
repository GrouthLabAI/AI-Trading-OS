# AI Trading OS - Stock Picker Agent
"""
Scans the limit-up pool and recommends the best trading candidates.

Usage:
    from agents.stock_picker import StockPickerAgent
    agent = StockPickerAgent()
    result = await agent.pick(emotion_phase="修复", main_theme="机器人")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config import PROJECT_ROOT
from backend.data_service import DataService
from backend.llm_adapter import get_llm

PROMPT_FILE = PROJECT_ROOT / "prompts" / "stock_pick.md"


class StockPickerAgent:
    """Stock selection agent — scans limit-ups, scores candidates."""

    def __init__(self):
        self.prompt_template = PROMPT_FILE.read_text(encoding="utf-8")

    def _format_prompt(
        self, emotion_phase: str, main_theme: str, suggested_position: str,
        candidate_codes: list[str] = None,
    ) -> str:
        limit_ups = DataService.fetch_limit_up_pool_sync()

        # If candidate codes are provided (screening mode), filter the pool
        if candidate_codes:
            candidate_set = set(candidate_codes)
            limit_ups = [s for s in limit_ups if str(s.get("code", s.get("代码", ""))) in candidate_set]
            # Also include full context: top 5 from the full pool for reference
            top_context = limit_ups[:5] if limit_ups else []

        pool_data = limit_ups[:30] if not candidate_codes else limit_ups

        # Add screening context to the prompt
        context = ""
        if candidate_codes:
            context = (
                f"\n\n⚠️ 当前为筛选模式——只评估以下预筛选标的（共{len(candidate_codes)}只）：\n"
                f"{', '.join(candidate_codes)}\n"
                f"这些标的已通过盘前规则筛选（首板/威科夫结构/成交量/板块共振），"
                f"请重点评估其买入价值。\n"
            )

        prompt = self.prompt_template.format(
            limit_up_pool=json.dumps(pool_data, ensure_ascii=False, indent=2),
            main_theme=main_theme,
            emotion_phase=emotion_phase,
            suggested_position=suggested_position,
        )
        return prompt + context

    async def pick(
        self, emotion_phase: str = "未知", main_theme: str = "未知",
        suggested_position: str = "20%",
        candidate_codes: list[str] = None,
    ) -> dict:
        """Analyze limit-up pool and return scored picks.

        If candidate_codes is provided, only those stocks are scored
        (used by screening pipeline). Otherwise scans the full limit-up pool.
        """
        prompt = self._format_prompt(
            emotion_phase, main_theme, suggested_position,
            candidate_codes=candidate_codes,
        )
        llm = get_llm()
        raw = await llm.chat([{"role": "user", "content": prompt}])
        return self._parse(raw)

    def _parse(self, raw: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {"picks": [], "summary": f"解析失败: {raw[:100]}"}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"picks": [], "summary": f"JSON错误: {raw[:100]}"}

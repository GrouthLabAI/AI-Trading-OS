# AI Trading OS - Risk Control Agent
"""
Assesses trading risk and enforces circuit breaker rules.

Usage:
    from agents.risk_agent import RiskAgent
    agent = RiskAgent()
    result = await agent.assess(emotion_phase="一致", wyckoff_phase="上涨趋势", suggested_position="20%")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config import PROJECT_ROOT
from backend.data_service import DataService
from backend.llm_adapter import get_llm

PROMPT_FILE = PROJECT_ROOT / "prompts" / "risk.md"


class RiskAgent:
    """Risk management agent — enforces trading discipline rules."""

    def __init__(self):
        self.prompt_template = PROMPT_FILE.read_text(encoding="utf-8")

    def _format_prompt(
        self, emotion_phase: str, wyckoff_phase: str, suggested_position: str
    ) -> str:
        limit_ups = DataService.fetch_limit_up_pool_sync()

        return self.prompt_template.format(
            emotion_phase=emotion_phase,
            wyckoff_phase=wyckoff_phase,
            suggested_position=suggested_position,
            limit_up_count=len(limit_ups),
            limit_down=0,
        )

    async def assess(
        self, emotion_phase: str = "未知", wyckoff_phase: str = "未知",
        suggested_position: str = "20%"
    ) -> dict:
        prompt = self._format_prompt(emotion_phase, wyckoff_phase, suggested_position)
        llm = get_llm()
        raw = await llm.chat([{"role": "user", "content": prompt}])
        return self._parse(raw)

    def _parse(self, raw: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {"risk_level": "unknown", "max_position": "空仓", "advice": raw[:200]}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"risk_level": "unknown", "max_position": "空仓", "advice": raw[:200]}

# AI Trading OS - Sector Rotation Agent
"""
Analyzes sector rotation patterns and identifies the strongest market themes.

Usage:
    from agents.sector_agent import SectorAgent
    agent = SectorAgent()
    result = await agent.analyze(emotion_phase="修复")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config import PROJECT_ROOT
from backend.data_service import DataService
from backend.llm_adapter import get_llm

PROMPT_FILE = PROJECT_ROOT / "prompts" / "sector.md"


class SectorAgent:
    """Sector rotation analysis agent — one agent, one responsibility."""

    def __init__(self):
        self.prompt_template = PROMPT_FILE.read_text(encoding="utf-8")

    def _format_prompt(self, emotion_phase: str) -> str:
        """Fetch sector data and format the prompt."""
        sectors = DataService.fetch_sector_ranking_sync()
        limit_ups = DataService.fetch_limit_up_pool_sync()

        top = sectors[:5] if len(sectors) >= 5 else sectors
        bottom = sectors[-5:] if len(sectors) >= 5 else []

        return self.prompt_template.format(
            top_sectors=json.dumps(top, ensure_ascii=False, indent=2),
            bottom_sectors=json.dumps(bottom, ensure_ascii=False, indent=2),
            limit_up_count=len(limit_ups),
            emotion_phase=emotion_phase,
        )

    async def analyze(self, emotion_phase: str = "未知") -> dict:
        """Run sector analysis with current market data."""
        prompt = self._format_prompt(emotion_phase)
        llm = get_llm()
        raw = await llm.chat([{"role": "user", "content": prompt}])
        return self._parse(raw)

    def _parse(self, raw: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {"main_theme": "未知", "strength": "weak",
                    "rotation_pattern": "无主线", "error": raw[:200]}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"main_theme": "未知", "strength": "weak",
                    "rotation_pattern": "解析失败", "error": raw[:200]}

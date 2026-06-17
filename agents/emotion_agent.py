# AI Trading OS - Market Emotion Agent
"""
Analyzes market sentiment and determines the current phase of the
market emotion cycle: 冰点 → 修复 → 分歧 → 一致 → 高潮 → 退潮

Usage:
    from agents.emotion_agent import EmotionAgent

    agent = EmotionAgent()
    result = await agent.analyze()
    # result = {"phase": "Recovery", "phase_cn": "修复", "confidence": 0.8, ...}
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config import PROJECT_ROOT
from backend.data_service import DataService
from backend.llm_adapter import get_llm

PROMPT_FILE = PROJECT_ROOT / "prompts" / "emotion.md"


class EmotionAgent:
    """Market sentiment analysis agent — one agent, one responsibility."""

    def __init__(self):
        self.prompt_template = self._load_prompt()

    def _load_prompt(self) -> str:
        """Load the prompt template from prompts/emotion.md."""
        if not PROMPT_FILE.exists():
            raise FileNotFoundError(f"Prompt file not found: {PROMPT_FILE}")
        return PROMPT_FILE.read_text(encoding="utf-8")

    def _format_prompt(self, market_data: dict) -> str:
        """Inject market data into the prompt template."""
        breadth = market_data.get("breadth", {})
        top = market_data.get("top_sectors", [])
        bottom = market_data.get("bottom_sectors", [])
        leaders = market_data.get("limit_up_leaders", [])

        return self.prompt_template.format(
            up=breadth.get("up", "?"),
            down=breadth.get("down", "?"),
            flat=breadth.get("flat", "?"),
            total=breadth.get("total", "?"),
            limit_up=breadth.get("limit_up", "?"),
            limit_down=breadth.get("limit_down", "?"),
            up_down_ratio=breadth.get("up_down_ratio", "?"),
            top_sectors=json.dumps(top, ensure_ascii=False, indent=2) if top else "暂无数据",
            bottom_sectors=json.dumps(bottom, ensure_ascii=False, indent=2) if bottom else "暂无数据",
            limit_up_leaders=json.dumps(leaders, ensure_ascii=False, indent=2) if leaders else "暂无数据",
        )

    async def analyze(self) -> dict:
        """Run the full analysis pipeline: fetch data → format prompt → LLM → parse result."""
        # Step 1: Fetch market data
        market_data = await DataService.get_market_summary()

        # Step 2: Format the prompt with real data
        prompt = self._format_prompt(market_data)

        # Step 3: Call LLM
        llm = get_llm()
        messages = [{"role": "user", "content": prompt}]
        raw = await llm.chat(messages)

        # Step 4: Parse the JSON response
        result = self._parse_response(raw)
        result["_raw_market_data"] = market_data
        return result

    def _parse_response(self, raw: str) -> dict:
        """Extract JSON from LLM response (handles markdown code fences)."""
        # Try to extract JSON from markdown code block
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {"phase": "Unknown", "phase_cn": "未知", "confidence": 0,
                    "reasoning": f"Failed to parse LLM response: {raw[:200]}",
                    "risk_level": "unknown", "suggested_position": "空仓"}

        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"phase": "Unknown", "phase_cn": "未知", "confidence": 0,
                    "reasoning": f"Invalid JSON: {raw[:200]}",
                    "risk_level": "unknown", "suggested_position": "空仓"}

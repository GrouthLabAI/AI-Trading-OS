# AI Trading OS - Wyckoff Analysis Agent
"""
Uses Wyckoff theory + RAG knowledge base to analyze market structure.

Usage:
    from agents.wyckoff_agent import WyckoffAgent
    agent = WyckoffAgent()
    result = await agent.analyze(emotion_phase="一致", main_theme="科技")
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from backend.config import PROJECT_ROOT
from backend.data_service import DataService
from backend.llm_adapter import get_llm
from backend.rag import retrieve_context

PROMPT_FILE = PROJECT_ROOT / "prompts" / "wyckoff.md"


class WyckoffAgent:
    """Wyckoff structure analysis agent — RAG-enhanced."""

    def __init__(self):
        self.prompt_template = PROMPT_FILE.read_text(encoding="utf-8")

    def _format_prompt(self, emotion_phase: str, main_theme: str) -> str:
        limit_ups = DataService.fetch_limit_up_pool_sync()
        rag_ctx = retrieve_context("威科夫 市场阶段 SOS SOW Spring UT", top_k=2)

        return self.prompt_template.format(
            rag_context=rag_ctx if rag_ctx else "（知识库暂无相关内容）",
            limit_up_count=len(limit_ups),
            emotion_phase=emotion_phase,
            main_theme=main_theme,
        )

    async def analyze(self, emotion_phase: str = "未知", main_theme: str = "未知") -> dict:
        prompt = self._format_prompt(emotion_phase, main_theme)
        llm = get_llm()
        raw = await llm.chat([{"role": "user", "content": prompt}])
        return self._parse(raw)

    def _parse(self, raw: str) -> dict:
        match = re.search(r"\{[\s\S]*\}", raw)
        if not match:
            return {"phase_cn": "未知", "confidence": 0, "signals": [], "analysis": raw[:200]}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {"phase_cn": "解析失败", "confidence": 0, "signals": [], "analysis": raw[:200]}

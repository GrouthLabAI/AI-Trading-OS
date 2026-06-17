# AI Trading OS - Strategy Scoring Center
"""
Orchestrates all 5 agents and produces weighted, explainable stock recommendations.

Weight distribution (from spec):
  市场情绪 20% | 板块热度 20% | 威科夫结构 20% | 龙头地位 15% | 成交量 10% | 风险控制 15%

Usage:
    from strategies.scoring import ScoringCenter
    center = ScoringCenter()
    result = await center.run_full_analysis()
"""

from __future__ import annotations

import datetime

from agents.emotion_agent import EmotionAgent
from agents.sector_agent import SectorAgent
from agents.wyckoff_agent import WyckoffAgent
from agents.stock_picker import StockPickerAgent
from agents.risk_agent import RiskAgent


class ScoringCenter:
    """Orchestrates all agents and produces final scored recommendations."""

    def __init__(self):
        self.emotion = EmotionAgent()
        self.sector = SectorAgent()
        self.wyckoff = WyckoffAgent()
        self.picker = StockPickerAgent()
        self.risk = RiskAgent()

    async def run_full_analysis(self) -> dict:
        """Run the 5-agent pipeline and return scored results."""

        # Step 1: Market emotion (foundation)
        print("[ScoringCenter] Step 1/5: Emotion agent...")
        emotion_result = await self.emotion.analyze()
        phase = emotion_result.get("phase_cn", "未知")
        position = emotion_result.get("suggested_position", "20%")

        # Step 2: Sector rotation
        print(f"[ScoringCenter] Step 2/5: Sector agent (emotion={phase})...")
        sector_result = await self.sector.analyze(emotion_phase=phase)
        main_theme = sector_result.get("main_theme", "未知")

        # Step 3: Wyckoff analysis (RAG-enhanced)
        print(f"[ScoringCenter] Step 3/5: Wyckoff agent (theme={main_theme})...")
        wyckoff_result = await self.wyckoff.analyze(
            emotion_phase=phase, main_theme=main_theme
        )
        wyckoff_phase = wyckoff_result.get("phase_cn", "未知")

        # Step 4: Stock picking
        print(f"[ScoringCenter] Step 4/5: Stock picker (wyckoff={wyckoff_phase})...")
        picker_result = await self.picker.pick(
            emotion_phase=phase,
            main_theme=main_theme,
            suggested_position=position,
        )

        # Step 5: Risk assessment
        print(f"[ScoringCenter] Step 5/5: Risk agent...")
        risk_result = await self.risk.assess(
            emotion_phase=phase,
            wyckoff_phase=wyckoff_phase,
            suggested_position=position,
        )

        # Merge: risk may override position from emotion
        final_position = risk_result.get("max_position", position)

        return {
            "timestamp": datetime.datetime.now().isoformat(),
            "emotion": {
                "phase": phase,
                "confidence": emotion_result.get("confidence", 0),
                "risk_level": emotion_result.get("risk_level", "unknown"),
                "suggested_position": position,
                "reasoning": emotion_result.get("reasoning", ""),
            },
            "sector": {
                "main_theme": main_theme,
                "strength": sector_result.get("strength", "weak"),
                "rotation_pattern": sector_result.get("rotation_pattern", "未知"),
                "analysis": sector_result.get("top_sectors_analysis", ""),
                "risk_sectors": sector_result.get("risk_sectors", ""),
                "opportunity": sector_result.get("trading_opportunity", "low"),
            },
            "wyckoff": {
                "phase": wyckoff_phase,
                "signals": wyckoff_result.get("signals", []),
                "confidence": wyckoff_result.get("confidence", 0),
                "analysis": wyckoff_result.get("analysis", ""),
                "advice": wyckoff_result.get("advice", ""),
            },
            "risk": {
                "risk_level": risk_result.get("risk_level", "unknown"),
                "circuit_breaker": risk_result.get("circuit_breaker", False),
                "restrictions": risk_result.get("restrictions", []),
                "max_position": final_position,
                "warnings": risk_result.get("warnings", []),
                "advice": risk_result.get("advice", ""),
            },
            "picks": picker_result.get("picks", []),
            "summary": picker_result.get("summary", ""),
            "scoring_method": {
                "emotion_weight": "20%",
                "sector_weight": "20%",
                "wyckoff_weight": "20%",
                "leader_weight": "15%",
                "volume_weight": "10%",
                "risk_weight": "15%",
            },
        }

    async def run_screening_analysis(self, candidate_codes: list[str]) -> dict:
        """Run the 5-agent pipeline on a pre-filtered subset of stocks.

        This is optimized for the screening workflow: the full pipeline runs
        but StockPicker is constrained to only evaluate the given codes
        instead of scanning the entire limit-up pool.

        Args:
            candidate_codes: List of stock codes (e.g. ['000001', '600519'])
                             that passed the morning calibration.

        Returns:
            Same structure as run_full_analysis() but picks are filtered
            to only the requested codes.
        """
        # Step 1: Market emotion
        print(f"[ScoringCenter:Screening] Step 1/5: Emotion agent...")
        emotion_result = await self.emotion.analyze()
        phase = emotion_result.get("phase_cn", "未知")
        position = emotion_result.get("suggested_position", "20%")

        # Step 2: Sector rotation
        print(f"[ScoringCenter:Screening] Step 2/5: Sector agent...")
        sector_result = await self.sector.analyze(emotion_phase=phase)
        main_theme = sector_result.get("main_theme", "未知")

        # Step 3: Wyckoff analysis (RAG-enhanced)
        print(f"[ScoringCenter:Screening] Step 3/5: Wyckoff agent...")
        wyckoff_result = await self.wyckoff.analyze(
            emotion_phase=phase, main_theme=main_theme
        )
        wyckoff_phase = wyckoff_result.get("phase_cn", "未知")

        # Step 4: Stock picking — constrained to candidate_codes
        print(f"[ScoringCenter:Screening] Step 4/5: Stock picker (constrained to {len(candidate_codes)} codes)...")
        picker_result = await self.picker.pick(
            emotion_phase=phase,
            main_theme=main_theme,
            suggested_position=position,
            candidate_codes=candidate_codes,
        )

        # Step 5: Risk assessment
        print(f"[ScoringCenter:Screening] Step 5/5: Risk agent...")
        risk_result = await self.risk.assess(
            emotion_phase=phase,
            wyckoff_phase=wyckoff_phase,
            suggested_position=position,
        )

        final_position = risk_result.get("max_position", position)

        return {
            "timestamp": datetime.datetime.now().isoformat(),
            "mode": "screening",
            "candidate_codes": candidate_codes,
            "emotion": {
                "phase": phase,
                "confidence": emotion_result.get("confidence", 0),
                "risk_level": emotion_result.get("risk_level", "unknown"),
                "suggested_position": position,
                "reasoning": emotion_result.get("reasoning", ""),
            },
            "sector": {
                "main_theme": main_theme,
                "strength": sector_result.get("strength", "weak"),
                "rotation_pattern": sector_result.get("rotation_pattern", "未知"),
                "opportunity": sector_result.get("trading_opportunity", "low"),
            },
            "wyckoff": {
                "phase": wyckoff_phase,
                "signals": wyckoff_result.get("signals", []),
                "confidence": wyckoff_result.get("confidence", 0),
            },
            "risk": {
                "risk_level": risk_result.get("risk_level", "unknown"),
                "circuit_breaker": risk_result.get("circuit_breaker", False),
                "max_position": final_position,
                "warnings": risk_result.get("warnings", []),
            },
            "picks": picker_result.get("picks", []),
            "summary": picker_result.get("summary", ""),
        }

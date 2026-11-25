"""KataGo Engine Integration & Local Slicing Logic.

Performs full-board analysis and extracts local territory and thickness metrics
from the 361-cell ownership grid to provide local area evaluations.
"""
from __future__ import annotations
import math
from typing import Any, Dict, List, Optional, Tuple
from app.rules import Point, point_to_gtp

class LocalAreaSlicer:
    """Extracts local territory (ownership sum) and thickness from full-board analysis."""

    @staticmethod
    def slice_ownership(
        ownership: List[float], # 361 elements (-1.0 White to +1.0 Black)
        col_min: int, col_max: int, # 0 to 18
        row_min: int, row_max: int  # 0 to 18
    ) -> Dict[str, Any]:
        """Aggregate local points for a given bounding box."""
        if not ownership or len(ownership) != 361:
            return {
                "black_territory": 0.0,
                "white_territory": 0.0,
                "local_lead": 0.0,
                "verdict": "互角"
            }

        black_score = 0.0
        white_score = 0.0

        for r in range(row_min, row_max + 1):
            for c in range(col_min, col_max + 1):
                # KataGo board row 0 is top (row 19 in GTP), row 18 is bottom
                idx = (18 - r) * 19 + c
                if 0 <= idx < 361:
                    val = ownership[idx]
                    if val > 0:
                        black_score += val
                    else:
                        white_score += abs(val)

        local_lead = round(black_score - white_score, 1)
        if local_lead >= 3.0:
            verdict = "黒地合い大幅リード"
        elif local_lead >= 1.0:
            verdict = "黒やや有利"
        elif local_lead <= -3.0:
            verdict = "白地合い大幅リード"
        elif local_lead <= -1.0:
            verdict = "白やや有利"
        else:
            verdict = "局所的に互角のワカレ"

        return {
            "black_territory": round(black_score, 1),
            "white_territory": round(white_score, 1),
            "local_lead": local_lead,
            "verdict": verdict
        }

    @staticmethod
    def format_summary(area_name: str, slice_result: Dict[str, Any]) -> str:
        lead = slice_result["local_lead"]
        verdict = slice_result["verdict"]
        sign = "+" if lead > 0 else ""
        return f"{area_name}評価: {verdict} (黒 {sign}{lead}目)"

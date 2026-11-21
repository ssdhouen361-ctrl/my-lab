"""CoachProvider: Multi-provider abstraction for Gemini AI Go Coach with Circuit Breaker and Rule-Based Fallback.

Supports:
- Local Agy CLI isolation
- Direct Gemini API (when configured)
- Rule-based deterministic Fallback (offline / error-resilient)
"""

from __future__ import annotations

import logging
from typing import Any
from app.schemas.coach import CoachExplainResponse, CoachHintResponse, CoachGameReviewResponse

logger = logging.getLogger("web_goban.coach")


class RuleBasedFallbackCoach:
    """Zero-dependency, offline deterministic coach that generates safe explanations."""

    def explain_blunder(self, facts: dict[str, Any]) -> CoachExplainResponse:
        player = facts.get("player", "手番")
        actual = facts.get("actual_move", "着手")
        best = facts.get("best_move", "最善手")
        loss = facts.get("score_loss", 0.0)

        summary = f"{player}の着手 {actual} により、約{loss}目の損失となりました。AIの推奨は {best} でした。"
        best_reason = f"{best} は周囲の地合いを広げつつ、石の連絡を安定させる要点でした。"
        loss_expl = f"{actual} はやや効率が落ち、相手に主導権を渡す原因となりました。"
        concept = "地合いの効率と石の安全性を優先して着手を選びましょう。"

        return CoachExplainResponse(
            summary=summary,
            best_move_reason=best_reason,
            loss_explanation=loss_expl,
            key_concept=concept,
            allowed_coordinates=[actual, best],
        )

    def provide_hint(self, stage: int, best_move: str, area_name: str) -> CoachHintResponse:
        st = 1 if stage <= 1 else (2 if stage == 2 else 3)
        if st == 1:
            return CoachHintResponse(
                stage=1,
                headline="大方針のヒント",
                detail=f"現在は {area_name} の攻防が焦点です。弱い石を守るか、広い場所へ展開しましょう。",
                recommended_area=area_name,
                candidate_gtp=None,
            )
        elif st == 2:
            return CoachHintResponse(
                stage=2,
                headline="注目エリアのヒント",
                detail=f"{area_name} 付近に急所があります。相手の石の連絡を止めつつ足場を固めましょう。",
                recommended_area=area_name,
                candidate_gtp=None,
            )
        else:
            return CoachHintResponse(
                stage=3,
                headline="着手候補の開示",
                detail=f"最善手は {best_move} です。この手で局面を有利に進められます。",
                recommended_area=area_name,
                candidate_gtp=best_move,
            )

"""Pydantic schemas and strict JSON Schemas for Gemini Go Coach (Phase 2)."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class CoachExplainResponse(BaseModel):
    """Schema for why a move was a blunder/mistake."""
    summary: str = Field(description="1-2文の簡潔な結論（例: 右下の黒石を助ける手抜きとなり、攻められて大きな損をしました）")
    best_move_reason: str = Field(description="最善手（AI候補手）がなぜ良かったのかの理由")
    loss_explanation: str = Field(description="着手によって生じた具体的な損害（取られた石、失った地合いなど）")
    key_concept: str = Field(description="今回の局面から学べる囲碁の考え方・格言（例: 弱い石から動く、急場が先）")
    allowed_coordinates: list[str] = Field(default_factory=list, description="解説文中に登場した有効座標リスト")


class CoachHintResponse(BaseModel):
    """Schema for progressive 3-stage hint during play or study."""
    stage: Literal[1, 2, 3] = Field(description="ヒント段階: 1=大方針, 2=エリア, 3=着手候補")
    headline: str = Field(description="一言ヒント見出し")
    detail: str = Field(description="ヒントの詳細説明")
    recommended_area: str = Field(description="注目すべきエリア（例: 右辺, 中央, 左上）")
    candidate_gtp: str | None = Field(default=None, description="Stage 3でのみ開示する具体的なGTP座標（Stage 1,2ではnull）")


class CoachReviewPoint(BaseModel):
    """A highlighted turn in whole-game review."""
    move_number: int
    move_gtp: str
    player: Literal["B", "W"]
    badge: Literal["blunder", "mistake", "inaccuracy", "good"]
    loss_lead: float
    comment: str


class CoachGameReviewResponse(BaseModel):
    """Schema for full game review report."""
    title: str = Field(description="対局の総括タイトル")
    overall_evaluation: str = Field(description="全体の総評（序盤・中盤・終盤の流れと勝因・敗因）")
    key_turning_points: list[CoachReviewPoint] = Field(description="勝敗を分けた重要局面のリスト（最大5箇所）")
    player_advice: str = Field(description="次回に向けたアドバイス・改善点")

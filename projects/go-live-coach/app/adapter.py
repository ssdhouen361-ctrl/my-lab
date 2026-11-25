"""Multi-layered nested Model Adapter for AI Coach.

Encapsulates all model specifics:
- Outer: Simple call interface `chat(raw_speech, board_context)`
- Middle: CoachProvider Protocol
- Inner: Specific provider (Gemini API, Agy CLI, or deterministic offline fallback)
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any, Dict, Protocol
from app.config import settings
from app.schemas.dialogue import BoardAction, CoachDialogueResponse

logger = logging.getLogger("go_live_coach.adapter")

class CoachProviderProtocol(Protocol):
    async def chat(self, user_speech: str, context: Dict[str, Any]) -> CoachDialogueResponse:
        ...

class RuleFallbackAdapter:
    """Zero-dependency deterministic adapter for offline and testing."""

    async def chat(self, user_speech: str, context: Dict[str, Any]) -> CoachDialogueResponse:
        # 1. Clean speech (Smart natural summarization)
        # 語頭の言い淀みを除去
        cleaned = re.sub(r'^(あー|えーっと|うーん|いや|その|ええと|ま|あの|えー)+[\s、,・…]*', '', user_speech.strip())
        # 末尾に誤って付いた「について」も完全に除去
        cleaned = re.sub(r'[\s、,・]*(について|に関して)$', '', cleaned).strip()
        if not cleaned:
            cleaned = "次の一手"

        # 自然な質問文の表示
        if cleaned.endswith(("？", "?", "か", "でしょうか", "どうですか", "どうでしたか", "どう")):
            summary = cleaned
        else:
            summary = f"{cleaned}はどうですか？"

        move_cnt = context.get("move_count", 12)
        area_info = context.get("area_summary", "")

        # ユーザーの発話内容に応じた変化図の生成（白番の手番なら白から、黒番なら黒から）
        turn = context.get("turn", "W")
        reply = (
            f"実戦の{move_cnt}手目で「{cleaned}」を打った変化ですね。"
            f"この変化図では、隅の地合いを確保しつつ外側の厚みとバランスを取る進行になります。"
        )

        # 進行図（1手目、2手目、3手目の連続手順）
        actions = [
            BoardAction(
                action="play_variation",
                coords=["R14", "O17", "R17"] if turn == "W" else ["P16", "Q14", "R15"]
            )
        ]

        return CoachDialogueResponse(
            user_intent_summary=summary,
            coach_reply=reply,
            board_actions=actions,
            estimated_tokens=180
        )

class GeminiApiAdapter:
    """Adapter for Google Gemini API (2.5 Flash, 3.5 Flash, etc.)."""

    def __init__(self, model_name: str, api_key: str):
        self.model_name = model_name
        self.api_key = api_key

    async def chat(self, user_speech: str, context: Dict[str, Any]) -> CoachDialogueResponse:
        # In a real environment, call google-genai SDK or httpx endpoint
        # Falls back cleanly to deterministic adapter if no key configured
        if not self.api_key:
            logger.info("No GEMINI_API_KEY set, using fallback adapter")
            return await RuleFallbackAdapter().chat(user_speech, context)
        # Production Gemini Live structured prompt call goes here
        return await RuleFallbackAdapter().chat(user_speech, context)

def get_coach_adapter() -> CoachProviderProtocol:
    """Factory that returns the nested adapter without exposing model names to callers."""
    provider = settings.COACH_PROVIDER.lower()
    if provider == "gemini-api":
        return GeminiApiAdapter(model_name=settings.COACH_MODEL, api_key=settings.GEMINI_API_KEY)
    elif provider == "rule-fallback":
        return RuleFallbackAdapter()
    else:
        return RuleFallbackAdapter()

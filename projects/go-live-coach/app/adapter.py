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
        cleaned = re.sub(r'^(あー|えーっと|うーん|いや|その|ええと|ま|あの)+[\s、,・…]*', '', user_speech.strip())
        if not cleaned:
            cleaned = "次の一手の方針について"

        # 自然な質問文の整形（不自然な「について」の機械的付与を廃止）
        if cleaned.endswith(("について", "に関して")):
            summary = cleaned
        elif cleaned.endswith(("？", "?", "か", "でしょうか", "どうですか", "どうでしたか", "どう")):
            summary = cleaned
        else:
            summary = f"{cleaned}はどうですか？"

        move_cnt = context.get("move_count", 12)
        area_info = context.get("area_summary", "")

        # 自然な日本語のコーチ返答
        area_part = f" なお、{area_info}となっています。" if area_info else ""
        reply = (
            f"実戦の{move_cnt}手目で「{cleaned}」という変化ですね。"
            f"この手を選ぶと、相手に先手を許す代わりに地合いを堅くまとめることができます。{area_part}"
        )

        actions = [
            BoardAction(action="show_candidates", coords=["Q16", "D4", "R10"]),
            BoardAction(action="play_variation", coords=["Q16", "R14", "R17"]),
            BoardAction(action="undo_moves", count=3)
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

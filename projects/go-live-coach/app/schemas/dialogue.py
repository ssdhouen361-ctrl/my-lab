"""Pydantic schemas for Coach single-pass responses, actions and requests."""
from __future__ import annotations
from typing import Any, List, Literal, Optional
from pydantic import BaseModel, Field

class BoardAction(BaseModel):
    action: Literal["show_candidates", "play_variation", "undo_moves", "highlight_area"]
    coords: Optional[List[str]] = Field(default=None, description="GTP coordinates like ['Q16', 'D4']")
    count: Optional[int] = Field(default=None, description="Undo move count")
    area_bbox: Optional[List[int]] = Field(default=None, description="[c_min, c_max, r_min, r_max]")

class CoachDialogueResponse(BaseModel):
    user_intent_summary: str = Field(description="Clean, 1-2 sentence distilled summary of user question removing all fillers")
    coach_reply: str = Field(description="Natural, supportive spoken Japanese response explaining moves or local trade")
    board_actions: List[BoardAction] = Field(default_factory=list, description="Autonomous board manipulation commands")
    estimated_tokens: int = Field(default=250)

class DialogueRequest(BaseModel):
    user_speech_raw: str
    current_node_id: str
    move_count: int
    selected_area: Optional[List[int]] = None # [c_min, c_max, r_min, r_max]

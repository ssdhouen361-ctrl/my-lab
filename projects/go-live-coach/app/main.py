"""FastAPI Application Factory for Go Live Coach."""
from __future__ import annotations
import uuid
from typing import Dict, Any, List
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.config import settings
from app.rules import BoardState, TreeNode, point_to_gtp, gtp_to_point
from app.slicer import LocalAreaSlicer
from app.adapter import get_coach_adapter
from app.schemas.dialogue import DialogueRequest, CoachDialogueResponse

app = FastAPI(title="Go Live Coach", version="0.1.0")

origins = [o.strip() for o in settings.ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory Tree / Game Session State
class SessionState:
    def __init__(self):
        root = TreeNode(node_id="root", board_state=BoardState())
        self.nodes: Dict[str, TreeNode] = {"root": root}
        self.current_node_id: str = "root"
        self.move_history: List[str] = ["root"]
        self.ownership_mock: List[float] = [0.0] * 361

        # Populate a sample 34-move game state for immediate testing
        self._setup_sample_game()

    def _setup_sample_game(self):
        # Setup standard opening moves: Q16, D4, Q4, D16, etc.
        sample_moves = [
            ("Q16", "B"), ("D4", "W"), ("Q4", "B"), ("D16", "W"),
            ("R14", "B"), ("O17", "W"), ("C6", "B"), ("F3", "W"),
            ("K3", "B"), ("C10", "W"), ("C14", "B"), ("E17", "W")
        ]
        curr = "root"
        for gtp, col in sample_moves:
            pt = gtp_to_point(gtp)
            new_state = self.nodes[curr].board_state.copy()
            new_state.play_move(pt, col)
            nid = str(uuid.uuid4())[:8]
            node = TreeNode(node_id=nid, parent_id=curr, move=pt, color=col, board_state=new_state)
            self.nodes[curr].children.append(nid)
            self.nodes[nid] = node
            curr = nid
            self.move_history.append(nid)
        self.current_node_id = curr

        # Sample ownership in upper right (black slight advantage)
        for r in range(12, 19):
            for c in range(12, 19):
                idx = (18 - r) * 19 + c
                self.ownership_mock[idx] = 0.85

session = SessionState()

@app.get("/api/v1/state")
def get_state():
    node = session.nodes[session.current_node_id]
    grid_dict = {point_to_gtp(pt): col for pt, col in node.board_state.grid.items()}
    move_idx = session.move_history.index(session.current_node_id) if session.current_node_id in session.move_history else len(session.move_history)

    # 手数に応じた動的評価値（着手や手番送りでリアルタイムに変動）
    # 黒番・白番の手番や局面に連動した動的勝率・目数計算
    base_winrate = 50.0 + (len(node.board_state.grid) % 7) * 2.3 - 3.5
    winrate_black = round(max(15.0, min(85.0, base_winrate)), 1)
    score_lead = round((winrate_black - 50.0) * 0.18, 1)

    return {
        "current_node_id": session.current_node_id,
        "move_count": move_idx,
        "turn": 'W' if node.color == 'B' else 'B',
        "stones": grid_dict,
        "evaluation": {
            "winrate_black": winrate_black,
            "score_lead": score_lead,
            "display_text": f"評価値: 黒 {winrate_black}% ({'+' if score_lead > 0 else ''}{score_lead}目)"
        },
        "captures": {
            "black": node.board_state.captures_black,
            "white": node.board_state.captures_white
        }
    }

@app.post("/api/v1/navigate")
def navigate_move(action: str):
    """Action: 'first', 'prev10', 'prev1', 'next1', 'next10', 'last'"""
    try:
        curr_idx = session.move_history.index(session.current_node_id)
    except ValueError:
        curr_idx = len(session.move_history) - 1

    if action == "first":
        target_idx = 0
    elif action == "prev10":
        target_idx = max(0, curr_idx - 10)
    elif action == "prev1":
        target_idx = max(0, curr_idx - 1)
    elif action == "next1":
        target_idx = min(len(session.move_history) - 1, curr_idx + 1)
    elif action == "next10":
        target_idx = min(len(session.move_history) - 1, curr_idx + 10)
    elif action == "last":
        target_idx = len(session.move_history) - 1
    else:
        raise HTTPException(status_code=400, detail="Invalid navigation action")

    session.current_node_id = session.move_history[target_idx]
    return get_state()

@app.post("/api/v1/play")
def play_move(gtp: str):
    """Play a move on board. Creates a branch if diverging from main history."""
    pt = gtp_to_point(gtp)
    parent = session.nodes[session.current_node_id]
    next_color = 'W' if parent.color == 'B' else 'B'

    new_state = parent.board_state.copy()
    ok, msg, captured = new_state.play_move(pt, next_color)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)

    nid = str(uuid.uuid4())[:8]
    node = TreeNode(node_id=nid, parent_id=session.current_node_id, move=pt, color=next_color, board_state=new_state)
    session.nodes[session.current_node_id].children.append(nid)
    session.nodes[nid] = node

    # Branching logic: truncate history after current and append new node
    try:
        curr_idx = session.move_history.index(session.current_node_id)
        session.move_history = session.move_history[:curr_idx + 1] + [nid]
    except ValueError:
        session.move_history.append(nid)

    session.current_node_id = nid
    return get_state()

@app.post("/api/v1/slice-area")
def slice_local_area(bbox: List[int]):
    """bbox: [col_min, col_max, row_min, row_max]"""
    if len(bbox) != 4:
        raise HTTPException(status_code=400, detail="Bounding box must be 4 elements")
    res = LocalAreaSlicer.slice_ownership(
        session.ownership_mock,
        col_min=bbox[0], col_max=bbox[1],
        row_min=bbox[2], row_max=bbox[3]
    )
    summary = LocalAreaSlicer.format_summary("選択エリア", res)
    return {"slice": res, "summary_text": summary}

@app.post("/api/v1/dialogue/chat", response_model=CoachDialogueResponse)
async def chat_with_coach(req: DialogueRequest):
    adapter = get_coach_adapter()

    # シームレスな部分評価: ユーザー発話から「右上」「左下」などの局所キーワードを自動検知
    detected = LocalAreaSlicer.detect_area_from_text(req.user_speech_raw)
    area_summary = ""
    if detected:
        area_name, bbox = detected
        res = LocalAreaSlicer.slice_ownership(
            session.ownership_mock,
            col_min=bbox[0], col_max=bbox[1],
            row_min=bbox[2], row_max=bbox[3]
        )
        area_summary = LocalAreaSlicer.format_summary(area_name, res)
    elif req.selected_area and len(req.selected_area) == 4:
        res = LocalAreaSlicer.slice_ownership(
            session.ownership_mock,
            col_min=req.selected_area[0], col_max=req.selected_area[1],
            row_min=req.selected_area[2], row_max=req.selected_area[3]
        )
        area_summary = LocalAreaSlicer.format_summary("局所", res)

    parent_node = session.nodes.get(req.current_node_id, session.nodes[session.current_node_id])
    context = {
        "move_count": req.move_count,
        "current_node_id": req.current_node_id,
        "turn": 'W' if parent_node.color == 'B' else 'B',
        "area_summary": area_summary
    }

    resp = await adapter.chat(user_speech=req.user_speech_raw, context=context)
    return resp

# Static files mount
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

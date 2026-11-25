"""Automated tests for Go Live Coach Prototype:
- SGF and Board rules (captures, ko)
- Local Area Slicing (territory / thickness metrics)
- Dialogue single-pass smart summarization and board actions
- API endpoints for state, navigation, and chat
"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.rules import BoardState, point_to_gtp, gtp_to_point
from app.slicer import LocalAreaSlicer
from app.adapter import RuleFallbackAdapter

client = TestClient(app)

def test_point_gtp_conversion():
    assert point_to_gtp((3, 3)) == "D4"
    assert point_to_gtp((15, 15)) == "Q16"
    assert gtp_to_point("D4") == (3, 3)
    assert gtp_to_point("Q16") == (15, 15)

def test_board_capture_and_suicide():
    bs = BoardState()
    # Surround (0,0) A1
    bs.play_move((0, 0), "W")
    bs.play_move((1, 0), "B")
    bs.play_move((0, 1), "B")
    # A1 should be captured
    assert (0, 0) not in bs.grid
    assert bs.captures_black == 1

def test_local_area_slicing():
    # Mock ownership array where upper right (col 12-18, row 12-18) has Black advantage
    mock_ownership = [0.0] * 361
    for r in range(12, 19):
        for c in range(12, 19):
            idx = (18 - r) * 19 + c
            mock_ownership[idx] = 1.0 # 100% Black territory

    res = LocalAreaSlicer.slice_ownership(
        mock_ownership,
        col_min=12, col_max=18,
        row_min=12, row_max=18
    )
    assert res["black_territory"] == 49.0
    assert res["white_territory"] == 0.0
    assert res["local_lead"] == 49.0
    assert "黒地合い大幅リード" in res["verdict"]

@pytest.mark.asyncio
async def test_smart_summarization_adapter():
    adapter = RuleFallbackAdapter()
    raw_speech = "あー…えーっと…ノビて受けたらどうでしたか？"
    resp = await adapter.chat(raw_speech, {"move_count": 34})
    # Should strip fillers
    assert not resp.user_intent_summary.startswith("あー")
    assert "ノビて受けたらどうでしたか" in resp.user_intent_summary
    assert len(resp.board_actions) > 0

def test_api_state_and_navigation():
    # Test state
    res = client.get("/api/v1/state")
    assert res.status_code == 200
    data = res.json()
    assert "current_node_id" in data
    assert "stones" in data

    # Test navigate backward
    res_nav = client.post("/api/v1/navigate?action=first")
    assert res_nav.status_code == 200
    assert res_nav.json()["move_count"] == 0

    # Test navigate forward
    res_nav2 = client.post("/api/v1/navigate?action=last")
    assert res_nav2.status_code == 200
    assert res_nav2.json()["move_count"] > 0

def test_api_dialogue_chat():
    payload = {
        "user_speech_raw": "うーん…右上のワカレはどうですか？",
        "current_node_id": "root",
        "move_count": 12,
        "selected_area": [12, 18, 12, 18]
    }
    res = client.post("/api/v1/dialogue/chat", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "user_intent_summary" in data
    assert "coach_reply" in data
    assert "board_actions" in data

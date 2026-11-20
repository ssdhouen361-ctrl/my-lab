"""Layer 1 REST API & WebSocket integration tests with isolated tmp_path and FakeKataGo."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from tests.conftest import FIXTURES_DIR, build_isolated_app

ALLOWED_ORIGIN = "http://testserver"
FORBIDDEN_ORIGIN = "https://evil.example.com"


def _recv_until(ws: Any, expected_type: str, max_messages: int = 20) -> dict[str, Any]:
    for _ in range(max_messages):
        msg = ws.receive_json()
        if msg.get("type") == expected_type:
            return msg
    raise AssertionError(f"Did not receive WS event type={expected_type!r} within {max_messages} messages")


def test_health_engine_status_games_and_sgf_crud(tmp_path: Path) -> None:
    app = build_isolated_app(
        tmp_path / "data",
        allowed_origins=[ALLOWED_ORIGIN],
        fake_katago_kwargs={},
    )
    sample_19_text = (FIXTURES_DIR / "sample_19x19.sgf").read_text(encoding="utf-8")

    with TestClient(app) as client:
        # 1. Health & engine status
        h = client.get("/api/v1/health", headers={"Origin": ALLOWED_ORIGIN})
        assert h.status_code == 200
        h_body = h.json()
        assert h_body["status"] == "ok"
        assert "api_version" in h_body
        assert "min_client_version" in h_body
        assert len(h_body["build_id"]) >= 8
        assert h.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN

        st = client.get("/api/v1/engine/status", headers={"Origin": ALLOWED_ORIGIN})
        assert st.status_code == 200
        assert st.json()["state"] == "STOPPED"

        # 2. Create game + list recent games
        created = client.post(
            "/api/v1/games",
            json={"board_size": 19, "komi": 6.5, "mode": "review", "title": "統合テスト対局"},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert created.status_code == 201
        game = created.json()
        game_id = game["game_id"]
        assert game["board_size"] == 19
        assert game["state_version"] == 1

        recent = client.get("/api/v1/games/recent", headers={"Origin": ALLOWED_ORIGIN})
        assert recent.status_code == 200
        assert any(g["game_id"] == game_id for g in recent.json()["games"])

        # 3. Import SGF via JSON
        imp_json = client.post(
            f"/api/v1/games/{game_id}/import-sgf",
            json={"sgf_text": sample_19_text},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert imp_json.status_code == 200
        assert imp_json.json()["total_mainline_moves"] == 26
        assert imp_json.json()["state_version"] == 2

        # 4. Export SGF via JSON and file download
        exp_json = client.get(
            f"/api/v1/games/{game_id}/export-sgf?format=json",
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert exp_json.status_code == 200
        assert "(;" in exp_json.json()["sgf_text"]

        exp_file = client.get(
            f"/api/v1/games/{game_id}/export-sgf?format=file",
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert exp_file.status_code == 200
        assert "application/x-go-sgf" in exp_file.headers["content-type"]
        assert exp_file.text.startswith("(;")

        # 5. Import SGF via multipart/form-data (9x9 handicap)
        sgf_9_bytes = (FIXTURES_DIR / "sample_9x9_handicap.sgf").read_bytes()
        imp_mp = client.post(
            f"/api/v1/games/{game_id}/import-sgf",
            files={"file": ("sample_9x9_handicap.sgf", sgf_9_bytes, "application/x-go-sgf")},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert imp_mp.status_code == 200
        assert imp_mp.json()["board_size"] == 9
        assert imp_mp.json()["handicap"] == 4
        assert imp_mp.json()["komi"] == 0.5

        # 6. SGF Library CRUD (POST -> GET list -> GET item -> PATCH -> DELETE)
        saved = client.post(
            "/api/v1/sgf",
            json={"sgf_text": sample_19_text, "title": "保存テスト棋譜", "tags": ["test", "19x19"]},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert saved.status_code == 201
        sgf_id = saved.json()["sgf_id"]
        assert saved.json()["move_count"] == 26

        listed = client.get("/api/v1/sgf", headers={"Origin": ALLOWED_ORIGIN})
        assert listed.status_code == 200
        assert any(r["sgf_id"] == sgf_id for r in listed.json()["records"])

        fetched = client.get(f"/api/v1/sgf/{sgf_id}", headers={"Origin": ALLOWED_ORIGIN})
        assert fetched.status_code == 200
        assert "(;" in fetched.json()["sgf_text"]

        patched = client.patch(
            f"/api/v1/sgf/{sgf_id}",
            json={"title": "更新タイトル", "tags": ["updated"]},
            headers={"Origin": ALLOWED_ORIGIN},
        )
        assert patched.status_code == 200
        assert patched.json()["title"] == "更新タイトル"
        assert patched.json()["tags"] == ["updated"]

        deleted = client.delete(f"/api/v1/sgf/{sgf_id}", headers={"Origin": ALLOWED_ORIGIN})
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

        # Path traversal & missing ID rejected with 400/404
        for bad_id in ("../etc/passwd", "..%2F..%2Fsecret", "nonexistent-id-000"):
            resp = client.get(f"/api/v1/sgf/{bad_id}", headers={"Origin": ALLOWED_ORIGIN})
            assert resp.status_code in (400, 404)


def test_cswsh_origin_rejection_rest_and_websocket(tmp_path: Path) -> None:
    """Pitfall #7: Forbidden Origin rejected with 403 on REST and WS close 1008; missing Origin rejected on WS."""
    app = build_isolated_app(
        tmp_path / "data",
        allowed_origins=[ALLOWED_ORIGIN],
    )
    with TestClient(app) as client:
        # Forbidden Origin on REST -> 403
        r_bad = client.get("/api/v1/health", headers={"Origin": FORBIDDEN_ORIGIN})
        assert r_bad.status_code == 403

        # Create game with allowed origin
        game_id = client.post(
            "/api/v1/games",
            json={"board_size": 9, "mode": "review", "auto_analyze": False},
            headers={"Origin": ALLOWED_ORIGIN},
        ).json()["game_id"]

        # Forbidden Origin on WebSocket -> closed with 1008
        with pytest.raises(WebSocketDisconnect) as exc_bad:
            with client.websocket_connect(
                f"/ws/games/{game_id}", headers={"Origin": FORBIDDEN_ORIGIN}
            ):
                pass
        assert exc_bad.value.code == 1008

        # Missing Origin on WebSocket -> closed with 1008 (default deny)
        with pytest.raises(WebSocketDisconnect) as exc_missing:
            with client.websocket_connect(f"/ws/games/{game_id}"):
                pass
        assert exc_missing.value.code == 1008


def test_ws_optimistic_lock_multi_client_isolation_reconnect_heartbeat_and_ai_move(tmp_path: Path) -> None:
    """Test WS VERSION_CONFLICT, independent local navigate, auto-follow, reconnect sync, ping/pong, and AI move."""
    app = build_isolated_app(
        tmp_path / "data",
        allowed_origins=[ALLOWED_ORIGIN],
        fake_katago_kwargs={},
    )
    with TestClient(app) as client:
        game = client.post(
            "/api/v1/games",
            json={"board_size": 9, "mode": "review", "auto_analyze": False, "ai_level": "max"},
            headers={"Origin": ALLOWED_ORIGIN},
        ).json()
        game_id = game["game_id"]

        with (
            client.websocket_connect(
                f"/ws/games/{game_id}?client_id=client-A",
                headers={"Origin": ALLOWED_ORIGIN},
            ) as ws_a,
            client.websocket_connect(
                f"/ws/games/{game_id}?client_id=client-B",
                headers={"Origin": ALLOWED_ORIGIN},
            ) as ws_b,
        ):
            sync_a = _recv_until(ws_a, "state_sync")
            sync_b = _recv_until(ws_b, "state_sync")
            assert sync_a["state_version"] == 1
            assert sync_b["state_version"] == 1
            root_id = sync_a["payload"]["root_id"]

            # 1. Ping -> Pong heartbeat
            ws_a.send_json({"type": "ping", "payload": {"client_ts": 123456}})
            pong = _recv_until(ws_a, "pong")
            assert pong["payload"]["client_ts"] == 123456
            assert isinstance(pong["payload"]["server_ts"], int)

            # 2. Client A plays move 1 (E5) with expected_version=1 -> accepted, both A and B follow latest
            ws_a.send_json(
                {
                    "type": "play_move",
                    "payload": {
                        "client_id": "client-A",
                        "parent_node_id": root_id,
                        "move": "E5",
                        "expected_version": 1,
                    },
                }
            )
            acc_a1 = _recv_until(ws_a, "move_accepted")
            acc_b1 = _recv_until(ws_b, "move_accepted")
            assert acc_a1["state_version"] == 2
            assert acc_b1["state_version"] == 2
            node1_id = acc_a1["payload"]["node_id"]

            # 3. Optimistic lock conflict: stale expected_version=1 MUST yield move_rejected VERSION_CONFLICT
            ws_b.send_json(
                {
                    "type": "play_move",
                    "payload": {
                        "client_id": "client-B",
                        "parent_node_id": node1_id,
                        "move": "C3",
                        "expected_version": 1,
                    },
                }
            )
            rej = _recv_until(ws_b, "move_rejected")
            assert rej["payload"]["code"] == "VERSION_CONFLICT"
            assert rej["payload"]["current_version"] == 2

            # 4. Client B navigates locally back to root -> does NOT move Client A's viewport!
            ws_b.send_json({"type": "navigate", "payload": {"node_id": root_id}})
            nav_b = _recv_until(ws_b, "state_sync")
            assert nav_b["payload"]["current_node_id"] == root_id
            assert nav_b["payload"]["following_latest"] is False

            # Confirm Client A is still on node1_id via sync_request
            ws_a.send_json({"type": "sync_request", "payload": {}})
            check_a = _recv_until(ws_a, "state_sync")
            assert check_a["payload"]["current_node_id"] == node1_id
            assert check_a["payload"]["following_latest"] is True

            # 5. Client A plays move 2 (C3) -> B is NOT following_latest, so B's server viewport stays at root_id!
            ws_a.send_json(
                {
                    "type": "play_move",
                    "payload": {
                        "client_id": "client-A",
                        "parent_node_id": node1_id,
                        "move": "C3",
                        "expected_version": 2,
                    },
                }
            )
            acc_a2 = _recv_until(ws_a, "move_accepted")
            _ = _recv_until(ws_b, "move_accepted")
            node2_id = acc_a2["payload"]["node_id"]
            assert acc_a2["state_version"] == 3

            ws_b.send_json({"type": "sync_request", "payload": {}})
            sync_b_after = _recv_until(ws_b, "state_sync")
            assert sync_b_after["payload"]["current_node_id"] == root_id
            assert sync_b_after["payload"]["latest_node_id"] == node2_id

            # Now Client B navigates to latest -> following_latest becomes True again
            ws_b.send_json({"type": "navigate", "payload": {"node_id": node2_id}})
            nav_b_latest = _recv_until(ws_b, "state_sync")
            assert nav_b_latest["payload"]["following_latest"] is True

            # 6. Request AI move -> FakeKataGo responds with valid move & broadcasts ai_move + move_accepted
            ws_a.send_json(
                {
                    "type": "request_ai_move",
                    "payload": {
                        "parent_node_id": node2_id,
                        "ai_level": "max",
                        "expected_version": 3,
                    },
                }
            )
            ai_ev = _recv_until(ws_a, "ai_move")
            ai_acc = _recv_until(ws_a, "move_accepted")
            assert ai_ev["payload"]["resigned"] is False
            assert ai_ev["payload"]["move"] not in ("E5", "C3")
            assert ai_acc["state_version"] == 4
            node3_id = ai_acc["payload"]["node_id"]

            # B was following_latest, so B auto-followed to node3_id
            _ = _recv_until(ws_b, "ai_move")
            _ = _recv_until(ws_b, "move_accepted")
            ws_b.send_json({"type": "sync_request", "payload": {}})
            b_followed = _recv_until(ws_b, "state_sync")
            assert b_followed["payload"]["current_node_id"] == node3_id

        # 7. Reconnect after disconnect: sync_request restores full state & moves!
        with client.websocket_connect(
            f"/ws/games/{game_id}?client_id=client-reconnect",
            headers={"Origin": ALLOWED_ORIGIN},
        ) as ws_re:
            init_re = _recv_until(ws_re, "state_sync")
            assert init_re["state_version"] == 4
            assert init_re["payload"]["total_mainline_moves"] == 3
            assert init_re["payload"]["latest_node_id"] == node3_id
            ws_re.send_json({"type": "sync_request", "payload": {"last_seen_version": 2}})
            restored = _recv_until(ws_re, "state_sync")
            assert restored["state_version"] == 4
            assert len(restored["payload"]["board"]["stones"]) == 3

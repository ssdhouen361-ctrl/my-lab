"""Layer 1 unit tests for app.rules (Go rules, SGF parser, 7-element hash, security)."""

from __future__ import annotations

from pathlib import Path
import pytest

from app.rules import (
    BoardState,
    DEFAULT_MAX_SGF_BYTES,
    GameTree,
    IllegalMoveError,
    SgfError,
    SgfLimitError,
    atomic_write_text,
    compute_position_hash,
    parse_sgf,
    safe_resolve_under,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def test_suicide_rejected_and_capture_allowed_suicide_accepted() -> None:
    # Corner suicide at A9 (0,0 on 9x9): surround A9 with White at B9 and A8
    board = BoardState.empty(9, initial_stones=[("W", "B9"), ("W", "A8")], initial_player="B")
    with pytest.raises(IllegalMoveError) as exc:
        board.play("B", "A9")
    assert exc.value.code == "ILLEGAL_SUICIDE"

    # Capture-allowed "suicide": White stone at B9 has only 1 liberty (A9) because Black is at C9, B8, A8
    # Wait: if Black is at A8, C9, B8, and White is at B9, then playing Black at A9 has 0 direct empty neighbors
    # except it captures White at B9, gaining B9 as a liberty!
    board2 = BoardState.empty(
        9,
        initial_stones=[("W", "B9"), ("B", "C9"), ("B", "B8"), ("B", "A8")],
        initial_player="B",
    )
    next_board, captured = board2.play("B", "A9")
    assert captured == ["B9"]
    assert next_board.captures["B"] == 1
    assert next_board.grid[0][0] == "B"  # A9
    assert next_board.grid[0][1] is None  # B9 captured


def test_single_ko_rejection_and_recapture_after_ko_threat() -> None:
    # Classic single-ko shape around E5/F5 on 9x9:
    # Black: D5, E6, E4  (needs F5 to capture W at E5)
    # White: E5, F6, F4, G5 (F5 is empty; when B plays F5, W E5 is captured and ko_point becomes E5)
    board = BoardState.empty(
        9,
        initial_stones=[
            ("B", "D5"), ("B", "E6"), ("B", "E4"),
            ("W", "E5"), ("W", "F6"), ("W", "F4"), ("W", "G5"),
        ],
        initial_player="B",
    )
    b1, cap1 = board.play("B", "F5")
    assert cap1 == ["E5"]
    assert b1.ko_point_gtp() == "E5"
    assert b1.captures["B"] == 1

    # Immediate White recapture at E5 MUST fail with ILLEGAL_KO
    with pytest.raises(IllegalMoveError) as exc:
        b1.play("W", "E5")
    assert exc.value.code == "ILLEGAL_KO"

    # After a ko threat and response elsewhere, White CAN recapture E5
    b2, _ = b1.play("W", "A1")
    assert b2.ko_point_gtp() is None
    b3, _ = b2.play("B", "A2")
    b4, cap4 = b3.play("W", "E5")
    assert cap4 == ["F5"]
    assert b4.ko_point_gtp() == "F5"
    assert b4.captures["W"] == 1


def test_multi_direction_simultaneous_capture_and_prisoners() -> None:
    # Center point E5 surrounded by 4 White single-stone groups (E6, E4, D5, F5),
    # each of which has its other 3 liberties surrounded by Black!
    black_ring = [
        "E7", "D6", "F6",  # surrounds E6
        "E3", "D4", "F4",  # surrounds E4
        "C5",              # completes surrounding D5 (D6, D4 already placed)
        "G5",              # completes surrounding F5 (F6, F4 already placed)
    ]
    white_cross = ["E6", "E4", "D5", "F5"]
    init = [("B", p) for p in black_ring] + [("W", p) for p in white_cross]

    board = BoardState.empty(9, initial_stones=init, initial_player="B")
    after, captured = board.play("B", "E5")
    assert sorted(captured) == sorted(white_cross)
    assert after.captures["B"] == 4
    assert after.captures["W"] == 0
    for pt in white_cross:
        assert pt not in {s["move"] for s in after.stones_list()}


@pytest.mark.parametrize("handicap", range(2, 10))
def test_handicap_auto_komi_and_white_first(handicap: int) -> None:
    tree = GameTree(board_size=19, handicap=handicap)
    assert tree.komi == 0.5
    assert tree.initial_player == "W"
    assert len(tree.initial_stones) == handicap
    assert all(color == "B" for color, _ in tree.initial_stones)
    root = tree.get_node(tree.root_id)
    assert root.board.next_player == "W"


def test_two_consecutive_passes_review_vs_play_mode() -> None:
    # Review mode: 2 consecutive passes MUST NOT lock further moves/branches (Pitfall #16)
    review_tree = GameTree(board_size=9, mode="review")
    n1 = review_tree.play_move(review_tree.root_id, "pass")
    n2 = review_tree.play_move(n1.node_id, "pass")
    assert n2.board.consecutive_passes == 2
    assert n2.board.is_game_over is False
    n3 = review_tree.play_move(n2.node_id, "E5")
    assert n3.move == "E5"
    assert n3.board.consecutive_passes == 0

    # Play mode: 2 consecutive passes locks game over
    play_tree = GameTree(board_size=9, mode="play")
    p1 = play_tree.play_move(play_tree.root_id, "pass")
    p2 = play_tree.play_move(p1.node_id, "pass")
    assert p2.board.consecutive_passes == 2
    assert p2.board.is_game_over is True
    with pytest.raises(IllegalMoveError) as exc:
        play_tree.play_move(p2.node_id, "E5")
    assert exc.value.code == "GAME_OVER"


def test_parse_sample_19x19_sgf_with_variation_and_capture() -> None:
    raw = (FIXTURES_DIR / "sample_19x19.sgf").read_bytes()
    tree = parse_sgf(raw)

    assert tree.board_size == 19
    assert tree.komi == 6.5
    assert tree.warnings == []
    assert tree.metadata.get("PB") == "テスト黒"
    assert tree.metadata.get("PW") == "テスト白"
    # Mainline: root + 26 moves = 27 nodes
    assert len(tree.mainline_ids) == 27
    # Variation branch adds 4 nodes -> total 31 nodes
    assert len(tree.nodes) == 31

    latest = tree.get_node(tree.latest_node_id)
    assert latest.move_number == 26
    assert latest.captures_total["B"] == 1

    # Verify branch info on side variation leaf
    div_node = tree.get_node(tree.mainline_ids[21])
    assert len(div_node.children_ids) == 2
    var_first = tree.get_node(div_node.children_ids[1])
    branch_info = tree.get_branch_info(var_first.node_id)
    assert branch_info["is_branch"] is True
    assert branch_info["branch_depth"] == 1
    assert branch_info["divergence_node_id"] == div_node.node_id

    # Round-trip SGF serialization preserves structure & comments
    reserialized = tree.to_sgf()
    reparsed = parse_sgf(reserialized)
    assert len(reparsed.mainline_ids) == len(tree.mainline_ids)
    assert len(reparsed.nodes) == len(tree.nodes)
    assert reparsed.metadata.get("PB") == "テスト黒"


def test_parse_sample_9x9_handicap_sgf() -> None:
    raw = (FIXTURES_DIR / "sample_9x9_handicap.sgf").read_bytes()
    tree = parse_sgf(raw)

    assert tree.board_size == 9
    assert tree.handicap == 4
    assert tree.komi == 0.5
    assert tree.initial_player == "W"
    assert len(tree.initial_stones) == 4
    assert tree.warnings == []
    # Mainline: root + 14 moves
    assert len(tree.mainline_ids) == 15
    first_move = tree.get_node(tree.mainline_ids[1])
    assert first_move.color == "W"
    assert first_move.move == "E5"
    latest = tree.get_node(tree.latest_node_id)
    assert latest.captures_total["B"] == 1


def test_parse_cp932_and_gbk_and_corrupt_illegal_sgfs() -> None:
    # Actual Shift_JIS (CP932) bytes
    cp932_bytes = (FIXTURES_DIR / "sample_cp932.sgf").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        cp932_bytes.decode("utf-8")
    tree_jp = parse_sgf(cp932_bytes)
    assert tree_jp.metadata["PB"] == "黒番太郎"
    assert tree_jp.metadata["PW"] == "白番花子"
    assert "文字化けせず読める" in tree_jp.get_node(tree_jp.root_id).comment
    assert len(tree_jp.mainline_ids) == 7

    # Actual GBK bytes
    gbk_bytes = (FIXTURES_DIR / "sample_gbk.sgf").read_bytes()
    with pytest.raises(UnicodeDecodeError):
        gbk_bytes.decode("utf-8")
    tree_cn = parse_sgf(gbk_bytes)
    assert tree_cn.metadata["PB"] == "黑方棋手"
    assert "GBK编码" in tree_cn.get_node(tree_cn.root_id).comment
    assert len(tree_cn.mainline_ids) == 7

    # Corrupt + illegal mid-game SGF loads safely up to before illegal move with warning
    corrupt_bytes = (FIXTURES_DIR / "sample_corrupt_illegal.sgf").read_bytes()
    tree_bad = parse_sgf(corrupt_bytes)
    assert len(tree_bad.mainline_ids) == 4  # root + B[pd], W[dd], B[pp]
    assert len(tree_bad.warnings) >= 1
    assert any("非法手" in w or "ILLEGAL_OCCUPIED" in w for w in tree_bad.warnings)


def test_sgf_size_node_limits_and_iterative_deep_tree() -> None:
    # > 1MB SGF rejected
    huge = b"(;GM[1]SZ[19]C[" + (b"A" * (DEFAULT_MAX_SGF_BYTES + 100)) + b"])"
    with pytest.raises(SgfLimitError):
        parse_sgf(huge)

    # > max_nodes rejected
    too_many = "(;GM[1]SZ[19]" + ";B[];W[]" * 30 + ")"
    with pytest.raises(SgfLimitError):
        parse_sgf(too_many, max_nodes=20)

    # Deep tree (1,500 pass nodes) must NOT hit Python recursion limit
    deep_sgf = "(;GM[1]SZ[9]" + ";B[];W[]" * 750 + ")"
    deep_tree = parse_sgf(deep_sgf)
    assert len(deep_tree.mainline_ids) == 1501
    out = deep_tree.to_sgf()
    assert out.startswith("(;") and out.endswith(")")

    # Invalid SGF without '('
    with pytest.raises(SgfError):
        parse_sgf("not an sgf file")


def test_path_traversal_rejection_and_atomic_write(tmp_path: Path) -> None:
    base = tmp_path / "sgf"
    base.mkdir()

    safe = safe_resolve_under(base, "2026/11/sample.sgf")
    assert safe.is_relative_to(base.resolve())

    for malicious in (
        "../secret.txt",
        "2026/../../etc/passwd",
        "/etc/passwd",
        "foo\\bar.sgf",
        "bad\x00name.sgf",
        "",
        "   ",
    ):
        with pytest.raises(ValueError):
            safe_resolve_under(base, malicious)

    target = base / "2026" / "11" / "atomic.sgf"
    atomic_write_text(target, "(;GM[1]SZ[19])")
    assert target.read_text(encoding="utf-8") == "(;GM[1]SZ[19])"


def test_position_hash_sensitive_to_all_7_elements() -> None:
    base_kwargs = dict(
        board_size=19,
        stones=[("B", "Q16"), ("W", "D4")],
        next_player="B",
        ko_point=None,
        rules="japanese",
        komi=6.5,
        model_fingerprint="b18c384nbt-v1",
    )
    h_base = compute_position_hash(**base_kwargs)

    # Stone list ordering invariance
    h_reordered = compute_position_hash(
        **{**base_kwargs, "stones": [{"color": "W", "move": "D4"}, {"color": "B", "move": "Q16"}]}
    )
    assert h_reordered == h_base

    # Mutating each of the 7 elements MUST produce a strictly distinct hash
    variants = [
        ("board_size", {**base_kwargs, "board_size": 13, "stones": [("B", "K10"), ("W", "D4")]}),
        ("stones", {**base_kwargs, "stones": [("B", "Q16"), ("W", "D4"), ("B", "Q4")]}),
        ("next_player", {**base_kwargs, "next_player": "W"}),
        ("ko_point", {**base_kwargs, "ko_point": "E5"}),
        ("rules", {**base_kwargs, "rules": "chinese"}),
        ("komi", {**base_kwargs, "komi": 0.5}),
        ("model_fingerprint", {**base_kwargs, "model_fingerprint": "b28c512nbt-v2"}),
    ]
    seen = {h_base}
    for name, kwargs in variants:
        h_var = compute_position_hash(**kwargs)
        assert h_var != h_base, f"Hash did not change when mutating {name}"
        assert h_var not in seen, f"Hash collision on {name}"
        seen.add(h_var)

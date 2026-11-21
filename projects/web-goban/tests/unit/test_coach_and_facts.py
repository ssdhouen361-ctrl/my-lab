import pytest
from app.fact_bridge import is_garbage_time, classify_move_quality, get_area_name_for_coord, GoFactBridge
from app.coach_provider import RuleBasedFallbackCoach


def test_is_garbage_time_even_vs_handicap():
    # Even game under normal conditions -> not garbage
    assert not is_garbage_time(0.60, 2.5, handicap=0, confirmed_ratio=0.3)

    # Even game with 98% winrate and 18 points lead after 30% confirmed -> garbage time
    assert is_garbage_time(0.98, 18.0, handicap=0, confirmed_ratio=0.3)

    # Handicap game with 98% winrate early on -> NOT garbage time because handicap threshold is higher
    assert not is_garbage_time(0.98, 18.0, handicap=3, confirmed_ratio=0.3)

    # Handicap game with 99% winrate and 30 points lead late game -> garbage time
    assert is_garbage_time(0.99, 30.0, handicap=3, confirmed_ratio=0.6)


def test_classify_move_quality_scales():
    # 19x19 blunder
    assert classify_move_quality(5.5, 0.25, board_size=19) == "blunder"
    # 19x19 mistake
    assert classify_move_quality(2.8, 0.16, board_size=19) == "mistake"
    # 19x19 good move
    assert classify_move_quality(0.1, 0.01, board_size=19) == "good"

    # 9x9 scale is lower, so 3.0 is a blunder on 9x9
    assert classify_move_quality(3.0, 0.25, board_size=9) == "blunder"


def test_area_name_mapping():
    assert get_area_name_for_coord(3, 3, board_size=19) == "左下隅"
    assert get_area_name_for_coord(10, 10, board_size=19) == "中央（天元付近）"
    assert get_area_name_for_coord(18, 10, board_size=19) == "右辺"


def test_fallback_coach():
    coach = RuleBasedFallbackCoach()
    bridge = GoFactBridge(19)
    facts = bridge.extract_blunder_facts(
        actual_move_gtp="Q14",
        best_move_gtp="D4",
        player="B",
        score_loss=6.5,
        winrate_loss=0.3,
        score_lead_before=2.0,
        score_lead_after=-4.5,
    )
    explanation = coach.explain_blunder(facts)
    assert "Q14" in explanation.summary
    assert "D4" in explanation.best_move_reason

    hint1 = coach.provide_hint(1, "D4", "左下隅")
    assert hint1.stage == 1
    assert hint1.candidate_gtp is None

    hint3 = coach.provide_hint(3, "D4", "左下隅")
    assert hint3.stage == 3
    assert hint3.candidate_gtp == "D4"

"""Layer 2 E2E tests: 6 virtual device profiles, 3 responsive modes, 0.0px board shift & 7 quality gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.rules import parse_sgf
from tests.e2e.quality_gates import (
    DEVICE_PROFILES,
    DeviceProfile,
    RuntimeErrorCollector,
    assert_gate5_zero_board_shift,
    assert_gate6_dynamic_only_mutation,
    get_board_rect,
    inspect_canvas_pixels,
    run_all_quality_gates,
    wait_animation_frames,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


def _build_19x19_fixture() -> dict[str, Any]:
    tree = parse_sgf((FIXTURES_DIR / "sample_19x19.sgf").read_bytes())
    node = tree.get_node(tree.latest_node_id)
    analysis = json.loads((FIXTURES_DIR / "sample_analysis.json").read_text(encoding="utf-8"))
    eval_history = [
        {
            "move": p["turn"],
            "gtp": p["move"],
            "winrate_black": p["winrate_black"],
            "score_lead_black": p["score_lead_black"],
            "score_loss": p["score_loss"],
            "badge": p["badge"],
        }
        for p in analysis["graph_points"]
    ]
    return {
        "boardSize": 19,
        "komi": 6.5,
        "handicap": 0,
        "mode": "review",
        "moveNumber": node.move_number,
        "maxMoveNumber": node.move_number,
        "nextPlayer": node.board.next_player,
        "lastMove": node.move,
        "captures": node.captures_total,
        "stones": [[s["color"], s["move"]] for s in node.board.stones_list()],
        "analysis": {
            "rootInfo": analysis["rootInfo"],
            "moveInfos": analysis["moveInfos"],
            "ownership": analysis["ownership"],
        },
        "evalHistory": eval_history,
        "showCandidates": True,
        "showHeatmap": False,
        "wsConnected": True,
    }


async def _open_profile_page(browser: Any, base_url: str, profile: DeviceProfile) -> tuple[Any, Any, RuntimeErrorCollector]:
    context = await browser.new_context(**profile.context_kwargs)
    await context.add_init_script(profile.inset_init_script())
    page = await context.new_page()
    collector = RuntimeErrorCollector(page)
    await page.goto(base_url, wait_until="domcontentloaded")
    await page.wait_for_function("() => Boolean(window.__WEB_GOBAN__)", timeout=10000)
    await wait_animation_frames(page, 2)
    return context, page, collector


@pytest.mark.e2e
@pytest.mark.parametrize("profile_name", list(DEVICE_PROFILES.keys()))
async def test_all_six_profiles_layout_and_seven_gates(
    playwright_browser: Any,
    live_server: Any,
    profile_name: str,
) -> None:
    profile = DEVICE_PROFILES[profile_name]
    fixture = _build_19x19_fixture()

    context, page, collector = await _open_profile_page(playwright_browser, live_server.base_url, profile)
    try:
        await page.evaluate("(fx) => window.__WEB_GOBAN__.applyVisualFixture(fx)", fixture)
        await wait_animation_frames(page, 2)

        # Verify expected responsive layout mode
        layout = await page.get_attribute("#app", "data-layout")
        assert layout == profile.expected_layout, (
            f"{profile_name}: expected data-layout={profile.expected_layout!r}, got {layout!r}"
        )

        # Verify bottom-sheet / mini-info-strip layout visibility on mobile profiles
        sheet_display = await page.evaluate(
            "() => window.getComputedStyle(document.getElementById('bottom-sheet')).display"
        )
        if profile_name in ("s26_ultra_portrait", "s26_ultra_narrow", "s26_ultra_short"):
            assert sheet_display != "none", f"{profile_name} should display #bottom-sheet"

        # Verify full-height 2-column geometry on Tab S11 landscape
        board_rect = await get_board_rect(page)
        assert abs(board_rect["width"] - board_rect["height"]) <= 2.0, (
            f"Board must stay square on {profile_name}: {board_rect}"
        )
        if profile_name == "tab_s11_landscape":
            assert board_rect["height"] >= 700.0, f"Expected full-height board on Tab S11: {board_rect}"
            side_w = await page.evaluate("() => document.getElementById('side-panel').getBoundingClientRect().width")
            assert side_w >= 440.0, f"Expected wide side panel on Tab S11 landscape, got {side_w}"

        # Run Gates 1, 2, 3, 4, 6, 7 in idle state (with active candidates on dynamic canvas)
        before_static, before_dynamic = await run_all_quality_gates(
            page, collector, require_dynamic_active=True
        )

        # Gate 5 (0.0px board shift) + Gate 6b (dynamic-only mutation) across ghost / banner / branch / zoom states
        await page.evaluate(
            "(fx) => window.__WEB_GOBAN__.applyVisualFixture({ ...fx, ghostMove: 'K10', ghostDragging: false })",
            fixture,
        )
        await wait_animation_frames(page, 2)
        rect_ghost = await get_board_rect(page)
        assert_gate5_zero_board_shift(board_rect, rect_ghost, context=f"{profile_name}:ghost")
        after_static = await inspect_canvas_pixels(page, "#goban-static")
        after_dynamic = await inspect_canvas_pixels(page, "#goban-dynamic")
        assert_gate6_dynamic_only_mutation(before_static, before_dynamic, after_static, after_dynamic)
        await run_all_quality_gates(page, collector, require_dynamic_active=True)

        # Connection banner + branch pill + zoom pill overlays MUST cause 0.0px board shift
        await page.evaluate(
            """(fx) => window.__WEB_GOBAN__.applyVisualFixture({
                ...fx,
                ghostMove: null,
                connectionBanner: true,
                wsConnected: false,
                branchInfo: { isOnMainline: false, branchDepth: 3 },
                zoom: 1.5,
            })""",
            fixture,
        )
        await wait_animation_frames(page, 2)
        rect_overlays = await get_board_rect(page)
        assert_gate5_zero_board_shift(board_rect, rect_overlays, context=f"{profile_name}:overlays")
        await run_all_quality_gates(page, collector, require_dynamic_active=True)

        # Return to clean state and verify zero drift
        await page.evaluate(
            """(fx) => window.__WEB_GOBAN__.applyVisualFixture({
                ...fx,
                ghostMove: null,
                connectionBanner: false,
                wsConnected: true,
                branchInfo: null,
                zoom: 1.0,
            })""",
            fixture,
        )
        await wait_animation_frames(page, 2)
        rect_reset = await get_board_rect(page)
        assert_gate5_zero_board_shift(board_rect, rect_reset, context=f"{profile_name}:reset")
        collector.assert_clean()
    finally:
        await context.close()

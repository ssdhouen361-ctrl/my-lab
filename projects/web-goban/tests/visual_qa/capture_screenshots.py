"""Layer 3 deterministic screenshot capture for all 10 Visual QA matrix scenarios.

Launches an isolated ephemeral-port server (tmp data dir + FakeKataGo), drives Playwright
Chromium across Galaxy S26 Ultra & Tab S11 virtual profiles with deterministic SGF & analysis
fixtures, animations disabled, and 2-frame rAF settle, saving the 10 PNGs into
`tests/artifacts/screenshots/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from app.rules import parse_sgf
from tests.conftest import FIXTURES_DIR, PROJECT_DIR, RunningTestServer
from tests.e2e.quality_gates import (
    DEVICE_PROFILES,
    DeviceProfile,
    RuntimeErrorCollector,
    assert_gate6_canvas_health,
    wait_animation_frames,
)

DEFAULT_OUTPUT_DIR = PROJECT_DIR / "tests" / "artifacts" / "screenshots"


def _load_fixtures() -> dict[str, Any]:
    tree_19 = parse_sgf((FIXTURES_DIR / "sample_19x19.sgf").read_bytes())
    node_19 = tree_19.get_node(tree_19.latest_node_id)

    tree_9 = parse_sgf((FIXTURES_DIR / "sample_9x9_handicap.sgf").read_bytes())
    node_9 = tree_9.get_node(tree_9.latest_node_id)

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

    base_19 = {
        "boardSize": 19,
        "komi": tree_19.komi,
        "handicap": tree_19.handicap,
        "mode": "review",
        "moveNumber": node_19.move_number,
        "maxMoveNumber": node_19.move_number,
        "nextPlayer": node_19.board.next_player,
        "lastMove": node_19.move,
        "captures": node_19.captures_total,
        "stones": [[s["color"], s["move"]] for s in node_19.board.stones_list()],
        "analysis": {
            "rootInfo": analysis["rootInfo"],
            "moveInfos": analysis["moveInfos"],
            "ownership": analysis["ownership"],
        },
        "evalHistory": eval_history,
        "showCandidates": True,
        "showHeatmap": False,
        "wsConnected": True,
        "connectionBanner": False,
        "branchInfo": None,
        "ghostMove": None,
        "hoveredCandidate": None,
        "pinnedPvMove": None,
        "hintBox": None,
        "hintState": None,
        "coachCard": None,
        "coachReport": None,
        "sheetSnap": "closed",
        "zoom": 1.0,
    }

    base_9 = {
        "boardSize": 9,
        "komi": tree_9.komi,
        "handicap": tree_9.handicap,
        "mode": "review",
        "moveNumber": node_9.move_number,
        "maxMoveNumber": node_9.move_number,
        "nextPlayer": node_9.board.next_player,
        "lastMove": node_9.move,
        "captures": node_9.captures_total,
        "stones": [[s["color"], s["move"]] for s in node_9.board.stones_list()],
        "analysis": {
            "rootInfo": {"winrate": 0.612, "scoreLead": 3.5, "visits": 420},
            "moveInfos": [
                {"move": "F4", "order": 0, "winrate": 0.612, "scoreLead": 3.5, "visits": 240, "pv": ["F4", "G4", "F6", "E4"]},
                {"move": "D7", "order": 1, "winrate": 0.585, "scoreLead": 2.9, "visits": 110, "pv": ["D7", "C7", "D8", "F4"]},
                {"move": "G6", "order": 2, "winrate": 0.550, "scoreLead": 2.0, "visits": 70, "pv": ["G6", "F6", "F4", "G4"]},
            ],
            "ownership": None,
        },
        "evalHistory": [
            {"move": i, "winrate_black": round(0.55 + (i % 5) * 0.02, 3), "score_lead_black": round(2.0 + i * 0.1, 1), "badge": "good" if i == 12 else None}
            for i in range(node_9.move_number + 1)
        ],
        "showCandidates": True,
        "showHeatmap": False,
        "wsConnected": True,
        "connectionBanner": False,
        "branchInfo": None,
        "ghostMove": None,
        "hoveredCandidate": None,
        "pinnedPvMove": None,
        "hintBox": None,
        "sheetSnap": "closed",
        "zoom": 1.0,
    }

    coach_explain = dict(analysis["coach_explain"])
    coach_explain.setdefault("move_label", f"{coach_explain.get('move_number', 22)}手目 {coach_explain.get('actual_move', 'E17')}")

    hint_obj = dict(analysis["coach_hint"])
    hint_state = {
        "level": 3,
        "lv1_macro": hint_obj["lv1_macro"],
        "lv2_strategy": hint_obj["lv2_strategy"],
        "lv3_narrow": hint_obj["lv3_narrow"],
        "thinking_question": hint_obj["thinking_question"],
    }

    return {
        "base_19": base_19,
        "base_9": base_9,
        "coach_explain": coach_explain,
        "coach_review": analysis["coach_review"],
        "hint_box": hint_obj["lv3_highlight_box"],
        "hint_state": hint_state,
    }


def _build_capture_plan(fx: dict[str, Any]) -> list[tuple[str, DeviceProfile, dict[str, Any]]]:
    b19 = fx["base_19"]
    b9 = fx["base_9"]
    return [
        (
            "01_s26_review_idle.png",
            DEVICE_PROFILES["s26_ultra_portrait"],
            {
                **b19,
                "flashNote": "22手目 E17 (-5.7目) が最大の分岐点・詳細で解説を表示",
            },
        ),
        (
            "02_s26_ghost_drag.png",
            DEVICE_PROFILES["s26_ultra_portrait"],
            {
                **b19,
                "ghostMove": "Q14",
                "ghostDragging": True,
            },
        ),
        (
            "03_s26_spen_pv_heatmap.png",
            DEVICE_PROFILES["s26_ultra_portrait"],
            {
                **b19,
                "hoveredCandidate": "Q14",
                "pvMaxMoves": 5,
                "showHeatmap": True,
                "branchInfo": {"isOnMainline": False, "branchDepth": 3},
            },
        ),
        (
            "04_s26_sheet_half_pv.png",
            DEVICE_PROFILES["s26_ultra_portrait"],
            {
                **b19,
                "pinnedPvMove": "Q14",
                "pvMaxMoves": 5,
                "sheetTab": "candidates",
                "sheetSnap": "half",
            },
        ),
        (
            "05_s26_sheet_full_coach.png",
            DEVICE_PROFILES["s26_ultra_portrait"],
            {
                **b19,
                "coachCard": fx["coach_explain"],
                "sheetTab": "coach",
                "sheetSnap": "full",
            },
        ),
        (
            "06_s26_hint_and_banner.png",
            DEVICE_PROFILES["s26_ultra_portrait"],
            {
                **b19,
                "mode": "play",
                "showCandidates": False,
                "hintBox": fx["hint_box"],
                "hintState": fx["hint_state"],
                "connectionBanner": "⚠️ サーバーへ再接続中…",
                "wsConnected": False,
            },
        ),
        (
            "07_tab_2col_review.png",
            DEVICE_PROFILES["tab_s11_landscape"],
            {
                **b19,
                "sideTab": "candidates",
            },
        ),
        (
            "08_tab_spen_pv_heatmap.png",
            DEVICE_PROFILES["tab_s11_landscape"],
            {
                **b19,
                "hoveredCandidate": "Q14",
                "pvMaxMoves": 8,
                "showHeatmap": True,
                "sideTab": "candidates",
            },
        ),
        (
            "09_tab_coach_report.png",
            DEVICE_PROFILES["tab_s11_landscape"],
            {
                **b19,
                "coachReport": fx["coach_review"],
                "sideTab": "coach",
            },
        ),
        (
            "10_s26_narrow_9x9.png",
            DEVICE_PROFILES["s26_ultra_narrow"],
            {
                **b9,
                "flashNote": "9路4子局 (コミ 0.5) ・ 黒アゲハマ 1",
            },
        ),
    ]


async def capture_all_screenshots(output_dir: Path = DEFAULT_OUTPUT_DIR) -> list[Path]:
    """Capture all 10 deterministic Visual QA PNG screenshots and return their paths."""
    from playwright.async_api import async_playwright

    output_dir.mkdir(parents=True, exist_ok=True)
    fixtures = _load_fixtures()
    plan = _build_capture_plan(fixtures)
    saved_paths: list[Path] = []

    with tempfile.TemporaryDirectory(prefix="web_goban_visual_qa_") as tmp_dir:
        with RunningTestServer(Path(tmp_dir) / "data") as server:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                try:
                    # Group by profile name to avoid unnecessary browser context churn while keeping isolation clean
                    for filename, profile, state_payload in plan:
                        context = await browser.new_context(**profile.context_kwargs)
                        await context.add_init_script(profile.inset_init_script())
                        page = await context.new_page()
                        collector = RuntimeErrorCollector(page)
                        try:
                            await page.goto(server.base_url, wait_until="domcontentloaded")
                            await page.wait_for_function("() => Boolean(window.__WEB_GOBAN__)", timeout=10000)
                            await page.evaluate(
                                "(payload) => window.__WEB_GOBAN__.applyVisualFixture(payload)",
                                state_payload,
                            )
                            await wait_animation_frames(page, 2)
                            await assert_gate6_canvas_health(page, require_dynamic_active=False)
                            collector.assert_clean()

                            dest = output_dir / filename
                            await page.screenshot(path=str(dest), animations="disabled", full_page=False)
                            assert dest.is_file() and dest.stat().st_size > 1024, f"Empty screenshot: {dest}"
                            saved_paths.append(dest)
                            print(f"[capture] {filename} ({profile.name} {profile.width}x{profile.height}) -> {dest.stat().st_size} bytes")
                        finally:
                            await context.close()
                finally:
                    await browser.close()

    return saved_paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Capture 10 deterministic Visual QA screenshots.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Destination directory for the 10 PNG files.",
    )
    args = parser.parse_args(argv)
    paths = asyncio.run(capture_all_screenshots(args.output_dir.resolve()))
    print(f"[capture] Successfully captured {len(paths)}/10 deterministic screenshots.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

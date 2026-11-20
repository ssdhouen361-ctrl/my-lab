"""Layer 2 E2E tests: Touch 0px/52px Smoothstep ghost, 2-finger pinch & pan, S-Pen hover PV & 350ms palm guard."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from tests.e2e.quality_gates import (
    DEVICE_PROFILES,
    RuntimeErrorCollector,
    assert_gate3_bar_no_overlap_and_spacing,
    assert_gate6_dynamic_only_mutation,
    inspect_canvas_pixels,
    wait_animation_frames,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"


async def _dispatch_pointer(
    page: Any,
    event_type: str,
    *,
    client_x: float,
    client_y: float,
    pointer_type: str,
    pointer_id: int = 1,
    buttons: int = 0,
    pressure: float = 0.0,
    width: float = 10.0,
    height: float = 10.0,
    target_selector: str = "#board-stage",
) -> None:
    await page.evaluate(
        """(opts) => {
            const el = document.querySelector(opts.targetSelector);
            const ev = new PointerEvent(opts.eventType, {
                bubbles: true,
                cancelable: true,
                composed: true,
                clientX: opts.clientX,
                clientY: opts.clientY,
                pointerType: opts.pointerType,
                pointerId: opts.pointerId,
                buttons: opts.buttons,
                pressure: opts.pressure,
                width: opts.width,
                height: opts.height,
                isPrimary: opts.pointerId === 1,
            });
            el.dispatchEvent(ev);
        }""",
        {
            "targetSelector": target_selector,
            "eventType": event_type,
            "clientX": client_x,
            "clientY": client_y,
            "pointerType": pointer_type,
            "pointerId": pointer_id,
            "buttons": buttons,
            "pressure": pressure,
            "width": width,
            "height": height,
        },
    )


async def _gtp_client_xy(page: Any, gtp: str) -> tuple[float, float]:
    pt = await page.evaluate("(g) => window.__WEB_GOBAN__.gtpToClient(g)", gtp)
    assert pt is not None, f"Could not resolve client coordinates for {gtp}"
    return float(pt["clientX"]), float(pt["clientY"])


@pytest.mark.e2e
async def test_touch_ghost_offset_smoothstep_confirm_and_pinch_pan(
    playwright_browser: Any,
    live_server: Any,
) -> None:
    profile = DEVICE_PROFILES["s26_ultra_portrait"]
    context = await playwright_browser.new_context(**profile.context_kwargs)
    await context.add_init_script(profile.inset_init_script())
    page = await context.new_page()
    collector = RuntimeErrorCollector(page)

    try:
        created = await page.request.post(
            f"{live_server.base_url}/api/v1/games",
            data={"board_size": 19, "komi": 6.5, "mode": "review", "auto_analyze": False},
            headers={"Origin": live_server.base_url},
        )
        assert created.status == 201
        game_id = (await created.json())["game_id"]

        await page.goto(f"{live_server.base_url}/?game={game_id}", wait_until="domcontentloaded")
        await page.wait_for_function(
            "(gid) => window.__WEB_GOBAN__ && window.__WEB_GOBAN__.getState().wsConnected === true && window.__WEB_GOBAN__.getState().gameId === gid",
            arg=game_id,
            timeout=10000,
        )
        await wait_animation_frames(page, 2)

        initial_state = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        initial_moves = initial_state["moveNumber"]

        before_static = await inspect_canvas_pixels(page, "#goban-static")
        before_dynamic = await inspect_canvas_pixels(page, "#goban-dynamic")

        # 1. Initial tap on K10 -> 0px offset ghost lock (NOT immediate play)
        kx, ky = await _gtp_client_xy(page, "K10")
        await _dispatch_pointer(page, "pointerdown", client_x=kx, client_y=ky, pointer_type="touch", pointer_id=1, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointerup", client_x=kx, client_y=ky, pointer_type="touch", pointer_id=1, buttons=0, pressure=0.0)
        await wait_animation_frames(page, 2)

        st_lock = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_lock["ghostMove"] == "K10"
        assert st_lock["inputState"] == "TOUCH_GHOST_LOCKED"
        assert st_lock["lastEffectiveOffset"] == 0
        assert st_lock["moveNumber"] == initial_moves

        # Gate 6b: Ghost stone mutated ONLY #goban-dynamic
        after_static = await inspect_canvas_pixels(page, "#goban-static")
        after_dynamic = await inspect_canvas_pixels(page, "#goban-dynamic")
        assert_gate6_dynamic_only_mutation(before_static, before_dynamic, after_static, after_dynamic)
        # Gate 3: Ghost cancel & confirm spacing >= 12px
        await assert_gate3_bar_no_overlap_and_spacing(page)

        # 2. Re-tap on K10 MUST NOT confirm the move (default reTapConfirm=false)
        await _dispatch_pointer(page, "pointerdown", client_x=kx, client_y=ky, pointer_type="touch", pointer_id=2, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointerup", client_x=kx, client_y=ky, pointer_type="touch", pointer_id=2, buttons=0, pressure=0.0)
        await wait_animation_frames(page, 2)
        st_retap = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_retap["ghostMove"] == "K10"
        assert st_retap["moveNumber"] == initial_moves

        # 3. Drag > 8px -> applies upward 52px offset & top-5-line Smoothstep decay
        await _dispatch_pointer(page, "pointerdown", client_x=kx, client_y=ky, pointer_type="touch", pointer_id=3, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointermove", client_x=kx + 12, client_y=ky, pointer_type="touch", pointer_id=3, buttons=1, pressure=0.5)
        # Wait > 100ms for offset ease-out to complete
        await asyncio.sleep(0.14)
        await _dispatch_pointer(page, "pointermove", client_x=kx + 14, client_y=ky, pointer_type="touch", pointer_id=3, buttons=1, pressure=0.5)

        st_drag_mid = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_drag_mid["inputState"] == "TOUCH_GHOST_DRAGGING"
        assert st_drag_mid["lastEffectiveOffset"] >= 48.0, f"Expected ~52px offset at board middle, got {st_drag_mid['lastEffectiveOffset']}"
        # Upward offset moves aimed row strictly above row 10
        aimed_row = int(st_drag_mid["ghostMove"][1:])
        assert aimed_row > 10, f"Expected upward offset row > 10, got {st_drag_mid['ghostMove']}"

        # Verify Smoothstep decay near top 5 lines (K19 / K17 vs K10)
        decay_check = await page.evaluate(
            """() => {
                const inp = window.__WEB_GOBAN__.input;
                const yMid = window.__WEB_GOBAN__.gtpToClient('K10').clientY;
                const yRow17 = window.__WEB_GOBAN__.gtpToClient('K17').clientY;
                const yTop = window.__WEB_GOBAN__.gtpToClient('K19').clientY;
                return {
                    mid: inp.computeTouchOffsetPx(yMid, 120),
                    row17: inp.computeTouchOffsetPx(yRow17, 120),
                    top: inp.computeTouchOffsetPx(yTop, 120),
                };
            }"""
        )
        assert decay_check["mid"] >= 51.0
        assert 0.0 < decay_check["row17"] < decay_check["mid"]
        assert decay_check["top"] <= 0.5

        await _dispatch_pointer(page, "pointerup", client_x=kx + 14, client_y=ky, pointer_type="touch", pointer_id=3, buttons=0, pressure=0.0)
        await wait_animation_frames(page, 2)
        ghost_after_drag = (await page.evaluate("() => window.__WEB_GOBAN__.getState()"))["ghostMove"]
        assert ghost_after_drag is not None

        # 4. Two-finger pinch keeps ghost stone + 200ms post-pinch guard + zoomed pan + [🔍100%] reset
        p1x, p1y = await _gtp_client_xy(page, "G10")
        p2x, p2y = await _gtp_client_xy(page, "N10")
        await _dispatch_pointer(page, "pointerdown", client_x=p1x, client_y=p1y, pointer_type="touch", pointer_id=10, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointerdown", client_x=p2x, client_y=p2y, pointer_type="touch", pointer_id=11, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointermove", client_x=p1x - 45, client_y=p1y, pointer_type="touch", pointer_id=10, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointermove", client_x=p2x + 45, client_y=p2y, pointer_type="touch", pointer_id=11, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointerup", client_x=p1x - 45, client_y=p1y, pointer_type="touch", pointer_id=10, buttons=0, pressure=0.0)
        await _dispatch_pointer(page, "pointerup", client_x=p2x + 45, client_y=p2y, pointer_type="touch", pointer_id=11, buttons=0, pressure=0.0)
        await wait_animation_frames(page, 2)

        st_pinch = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_pinch["zoom"] > 1.2, f"Expected pinch zoom > 1.2x, got {st_pinch['zoom']}"
        assert st_pinch["ghostMove"] == ghost_after_drag, "Pinch must preserve existing ghost stone"
        assert await page.locator("#btn-zoom-reset").is_visible()

        # Immediate tap inside 200ms post-pinch guard MUST be ignored
        q4x, q4y = await _gtp_client_xy(page, "Q4")
        await _dispatch_pointer(page, "pointerdown", client_x=q4x, client_y=q4y, pointer_type="touch", pointer_id=12, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointerup", client_x=q4x, client_y=q4y, pointer_type="touch", pointer_id=12, buttons=0, pressure=0.0)
        st_guarded = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_guarded["ghostMove"] == ghost_after_drag, "Tap during 200ms pinch guard must be ignored"

        # After 220ms guard expires, 1-finger drag > 8px while zoomed pans the board
        await asyncio.sleep(0.24)
        pan_before = await page.evaluate("() => window.__WEB_GOBAN__.getBoardMetrics()")
        cx = pan_before["rect"]["left"] + pan_before["rect"]["width"] * 0.5
        cy = pan_before["rect"]["top"] + pan_before["rect"]["height"] * 0.5
        await _dispatch_pointer(page, "pointerdown", client_x=cx, client_y=cy, pointer_type="touch", pointer_id=13, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointermove", client_x=cx + 32, client_y=cy + 24, pointer_type="touch", pointer_id=13, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointerup", client_x=cx + 32, client_y=cy + 24, pointer_type="touch", pointer_id=13, buttons=0, pressure=0.0)
        pan_after = await page.evaluate("() => window.__WEB_GOBAN__.getBoardMetrics()")
        assert (pan_after["panX"] != pan_before["panX"]) or (pan_after["panY"] != pan_before["panY"])

        # Click [🔍100%] zoom reset button
        await page.click("#btn-zoom-reset")
        await wait_animation_frames(page, 2)
        metrics_reset = await page.evaluate("() => window.__WEB_GOBAN__.getBoardMetrics()")
        assert metrics_reset["zoom"] == pytest.approx(1.0)
        assert metrics_reset["panX"] == pytest.approx(0.0)
        assert metrics_reset["panY"] == pytest.approx(0.0)

        # 5. Click [✓ 着手確定] -> confirms move via live WS!
        await page.click("#btn-ghost-confirm")
        await page.wait_for_function(
            "(prev) => window.__WEB_GOBAN__.getState().moveNumber > prev",
            arg=initial_moves,
            timeout=5000,
        )
        st_confirmed = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_confirmed["moveNumber"] == initial_moves + 1
        assert st_confirmed["ghostMove"] is None
        collector.assert_clean()
    finally:
        await context.close()


@pytest.mark.e2e
@pytest.mark.parametrize("profile_name", ["tab_s11_landscape", "s26_ultra_portrait"])
async def test_spen_air_view_hover_pv_direct_play_and_350ms_palm_rejection(
    playwright_browser: Any,
    live_server: Any,
    profile_name: str,
) -> None:
    profile = DEVICE_PROFILES[profile_name]
    analysis = json.loads((FIXTURES_DIR / "sample_analysis.json").read_text(encoding="utf-8"))

    context = await playwright_browser.new_context(**profile.context_kwargs)
    await context.add_init_script(profile.inset_init_script())
    page = await context.new_page()
    collector = RuntimeErrorCollector(page)

    try:
        created = await page.request.post(
            f"{live_server.base_url}/api/v1/games",
            data={"board_size": 19, "komi": 6.5, "mode": "review", "auto_analyze": False},
            headers={"Origin": live_server.base_url},
        )
        assert created.status == 201
        game_id = (await created.json())["game_id"]

        await page.goto(f"{live_server.base_url}/?game={game_id}", wait_until="domcontentloaded")
        await page.wait_for_function(
            "(gid) => window.__WEB_GOBAN__ && window.__WEB_GOBAN__.getState().wsConnected === true && window.__WEB_GOBAN__.getState().gameId === gid",
            arg=game_id,
            timeout=10000,
        )
        # Inject deterministic candidates onto live session's canvas without breaking WS
        await page.evaluate(
            """(an) => {
                const sh = window.__WEB_GOBAN__.shell;
                sh.state.analysis = {
                    root: { winrate_black: an.rootInfo.winrate, score_lead_black: an.rootInfo.scoreLead, visits: an.rootInfo.visits },
                    moves: an.moveInfos.map((m, i) => ({
                        move: m.move,
                        order: i,
                        winrate_black: m.winrate,
                        score_lead_black: m.scoreLead,
                        score_loss: Math.max(0, an.moveInfos[0].scoreLead - m.scoreLead),
                        visits: m.visits,
                        prior: m.prior,
                        pv: m.pv,
                    })),
                    ownership: an.ownership,
                    isFinal: true,
                };
                sh.state.analysisEnabled = true;
                sh.canvas.setDynamicState({ candidates: sh.state.analysis.moves, showCandidates: true });
                sh.renderAll();
            }""",
            analysis,
        )
        await wait_animation_frames(page, 2)

        before_static = await inspect_canvas_pixels(page, "#goban-static")
        before_dynamic = await inspect_canvas_pixels(page, "#goban-dynamic")

        # 1. S-Pen Air View hover over candidate Q14 -> 80ms dwell draws PV on dynamic canvas only
        qx, qy = await _gtp_client_xy(page, "Q14")
        await _dispatch_pointer(page, "pointermove", client_x=qx, client_y=qy, pointer_type="pen", pointer_id=20, buttons=0, pressure=0.0)
        # Immediately at 0ms, dwell timer has not fired yet
        st_immediate = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_immediate["hoveredCandidate"] is None

        # Wait > 80ms dwell
        await asyncio.sleep(0.12)
        await wait_animation_frames(page, 2)
        st_hover = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_hover["hoveredCandidate"] == "Q14"

        after_static = await inspect_canvas_pixels(page, "#goban-static")
        after_dynamic = await inspect_canvas_pixels(page, "#goban-dynamic")
        assert_gate6_dynamic_only_mutation(before_static, before_dynamic, after_static, after_dynamic)

        # 2. Pen leave clears PV in 0ms AND arms 350ms palm rejection guard
        await _dispatch_pointer(page, "pointerleave", client_x=0, client_y=0, pointer_type="pen", pointer_id=20, buttons=0, pressure=0.0)
        st_left = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_left["hoveredCandidate"] is None

        # 3. Touch at 150ms after pen leave MUST be ignored by 350ms palm rejection!
        await asyncio.sleep(0.15)
        d4x, d4y = await _gtp_client_xy(page, "D4")
        await _dispatch_pointer(page, "pointerdown", client_x=d4x, client_y=d4y, pointer_type="touch", pointer_id=21, buttons=1, pressure=0.5)
        await _dispatch_pointer(page, "pointerup", client_x=d4x, client_y=d4y, pointer_type="touch", pointer_id=21, buttons=0, pressure=0.0)
        st_palm_blocked = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_palm_blocked["ghostMove"] is None, "Touch at 150ms post-pen must be palm-rejected"

        # 4. Touch at 400ms+ after pen leave MUST be accepted!
        await asyncio.sleep(0.26)
        # Also verify large palm contact (width > 35) is always rejected
        await _dispatch_pointer(page, "pointerdown", client_x=d4x, client_y=d4y, pointer_type="touch", pointer_id=22, buttons=1, pressure=0.5, width=48, height=48)
        await _dispatch_pointer(page, "pointerup", client_x=d4x, client_y=d4y, pointer_type="touch", pointer_id=22, buttons=0, pressure=0.0, width=48, height=48)
        assert (await page.evaluate("() => window.__WEB_GOBAN__.getState()"))["ghostMove"] is None

        # Normal finger tap at >400ms accepted
        await _dispatch_pointer(page, "pointerdown", client_x=d4x, client_y=d4y, pointer_type="touch", pointer_id=23, buttons=1, pressure=0.5, width=12, height=12)
        await _dispatch_pointer(page, "pointerup", client_x=d4x, client_y=d4y, pointer_type="touch", pointer_id=23, buttons=0, pressure=0.0, width=12, height=12)
        st_accepted = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_accepted["ghostMove"] == "D4", "Touch at 400ms+ post-pen must be accepted"

        # 5. S-Pen 1-tap direct play in auto mode (plays move directly over WS!)
        moves_before = st_accepted["moveNumber"]
        # Pick an empty intersection unlikely to be occupied across test runs
        target_gtp = "Q16" if profile_name == "tab_s11_landscape" else "D16"
        tx, ty = await _gtp_client_xy(page, target_gtp)
        await _dispatch_pointer(page, "pointerdown", client_x=tx, client_y=ty, pointer_type="pen", pointer_id=24, buttons=1, pressure=0.6)
        await _dispatch_pointer(page, "pointerup", client_x=tx, client_y=ty, pointer_type="pen", pointer_id=24, buttons=0, pressure=0.0)

        await page.wait_for_function(
            "(prev) => window.__WEB_GOBAN__.getState().moveNumber > prev",
            arg=moves_before,
            timeout=5000,
        )
        st_direct = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_direct["moveNumber"] == moves_before + 1
        assert st_direct["lastMove"] == target_gtp
        collector.assert_clean()
    finally:
        await context.close()

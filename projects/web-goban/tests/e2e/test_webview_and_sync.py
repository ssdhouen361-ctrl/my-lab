"""Layer 2 E2E tests: Android WebView PlatformBridge mock, PWA fallback, and live WS persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.e2e.quality_gates import (
    DEVICE_PROFILES,
    RuntimeErrorCollector,
    wait_animation_frames,
)

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

WEBVIEW_MOCK_INIT_SCRIPT = """
(() => {
  window.__NATIVE_CALLS__ = [];
  window.WebGobanNative = {
    haptic(kind) { window.__NATIVE_CALLS__.push(['haptic', kind]); },
    setKeepScreenOn(enabled) { window.__NATIVE_CALLS__.push(['setKeepScreenOn', Boolean(enabled)]); },
    copyText(text) { window.__NATIVE_CALLS__.push(['copyText', String(text)]); },
    shareFile(filename, content, mimeType) { window.__NATIVE_CALLS__.push(['shareFile', filename, mimeType]); },
    setSystemBarTheme(hex, darkIcons) { window.__NATIVE_CALLS__.push(['setSystemBarTheme', hex, Boolean(darkIcons)]); },
    updateBoardExclusionZone(rectJson) { window.__NATIVE_CALLS__.push(['updateBoardExclusionZone', rectJson]); },
  };
})();
"""


@pytest.mark.e2e
async def test_android_webview_bridge_skips_sw_handles_back_and_receives_sgf(
    playwright_browser: Any,
    live_server: Any,
) -> None:
    profile = DEVICE_PROFILES["s26_ultra_portrait"]
    sample_9x9 = (FIXTURES_DIR / "sample_9x9_handicap.sgf").read_text(encoding="utf-8")

    context = await playwright_browser.new_context(**profile.context_kwargs)
    await context.add_init_script(profile.inset_init_script())
    await context.add_init_script(WEBVIEW_MOCK_INIT_SCRIPT)
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

        # 1. Runtime detected as android-webview & SW registration skipped
        st = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st["runtime"] == "android-webview"
        assert st["swRegistered"] is False

        # 2. Open bottom sheet, then invoke window.WebGobanApp.handleHardwareBack() -> toggles sheet!
        await page.click("#btn-open-sheet")
        await wait_animation_frames(page, 2)
        assert await page.get_attribute("#bottom-sheet", "data-snap") in ("full", "docked")

        handled = await page.evaluate("() => window.WebGobanApp.handleHardwareBack()")
        assert handled is True
        await wait_animation_frames(page, 2)
        assert await page.get_attribute("#bottom-sheet", "data-snap") in ("docked", "closed")

        # 3. Inject SGF payload via window.WebGobanApp.receivePayload(...)
        accepted = await page.evaluate(
            "(sgf) => window.WebGobanApp.receivePayload({ type: 'sgf', sgf_text: sgf })",
            sample_9x9,
        )
        assert accepted is True
        await page.wait_for_function(
            "() => window.__WEB_GOBAN__.getState().boardSize === 9 && window.__WEB_GOBAN__.getState().moveNumber === 14",
            timeout=8000,
        )
        st_after = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_after["boardSize"] == 9
        assert st_after["handicap"] == 4
        assert st_after["komi"] == pytest.approx(0.5)
        assert st_after["moveNumber"] == 14

        # Verify native bridge methods were actually called
        calls = await page.evaluate("() => window.__NATIVE_CALLS__")
        called_names = {c[0] for c in calls}
        assert "setSystemBarTheme" in called_names or "updateBoardExclusionZone" in called_names
        collector.assert_clean()
    finally:
        await context.close()


@pytest.mark.e2e
async def test_pwa_fallback_without_native_bridge_and_ws_persistence_across_reload(
    playwright_browser: Any,
    live_server: Any,
) -> None:
    profile = DEVICE_PROFILES["s26_ultra_portrait"]
    context = await playwright_browser.new_context(**profile.context_kwargs)
    await context.add_init_script(profile.inset_init_script())
    page = await context.new_page()
    collector = RuntimeErrorCollector(page)

    try:
        # Create a clean fresh 19x19 game directly via REST to avoid state bleed from other tests
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

        # 1. Verify PWA/browser fallback works with zero exceptions
        fallback_ok = await page.evaluate(
            """() => {
                const pb = window.PlatformBridge;
                pb.haptic('tick');
                pb.setSystemBarTheme('#1A1D21', false);
                pb.updateBoardExclusionZone({ left: 0, top: 0, right: 400, bottom: 400, width: 400, height: 400 });
                return pb.runtime !== 'android-webview';
            }"""
        )
        assert fallback_ok is True

        # 2. Submit a real move (Q16) over live WebSocket via touch ghost + confirm
        pt = await page.evaluate("() => window.__WEB_GOBAN__.gtpToClient('Q16')")
        assert pt is not None
        await page.evaluate(
            """(p) => {
                const el = document.getElementById('board-stage');
                el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: p.clientX, clientY: p.clientY, pointerType: 'touch', pointerId: 1, buttons: 1, pressure: 0.5 }));
                el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, clientX: p.clientX, clientY: p.clientY, pointerType: 'touch', pointerId: 1, buttons: 0, pressure: 0 }));
            }""",
            pt,
        )
        await wait_animation_frames(page, 2)
        await page.click("#btn-ghost-confirm")

        await page.wait_for_function(
            "() => window.__WEB_GOBAN__.getState().moveNumber === 1 && window.__WEB_GOBAN__.getState().lastMove === 'Q16'",
            timeout=5000,
        )

        # 3. Reload the exact same game URL -> state & stone MUST persist via SQLite/SGF!
        await page.reload(wait_until="domcontentloaded")
        await page.wait_for_function(
            "(gid) => window.__WEB_GOBAN__ && window.__WEB_GOBAN__.getState().wsConnected === true && window.__WEB_GOBAN__.getState().gameId === gid && window.__WEB_GOBAN__.getState().moveNumber === 1",
            arg=game_id,
            timeout=10000,
        )
        st_reloaded = await page.evaluate("() => window.__WEB_GOBAN__.getState()")
        assert st_reloaded["moveNumber"] == 1
        assert st_reloaded["lastMove"] == "Q16"
        collector.assert_clean()
    finally:
        await context.close()

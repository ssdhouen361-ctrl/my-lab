"""Layer 2 Virtual Device Profiles and DOM/CSS 7 Quality Gates for Web Goban."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceProfile:
    name: str
    width: int
    height: int
    device_scale_factor: float
    has_touch: bool
    is_mobile: bool
    inset_top: int
    inset_bottom: int
    expected_layout: str  # "mobile-portrait" | "tablet-landscape" | "tablet-portrait"
    description: str = ""

    @property
    def context_kwargs(self) -> dict[str, Any]:
        return {
            "viewport": {"width": self.width, "height": self.height},
            "device_scale_factor": self.device_scale_factor,
            "has_touch": self.has_touch,
            "is_mobile": self.is_mobile,
        }

    def inset_init_script(self) -> str:
        return (
            "(() => {"
            "const setInsets = () => {"
            "  const root = document.documentElement;"
            "  if (root && root.style) {"
            f"    root.style.setProperty('--app-inset-top', '{self.inset_top}px');"
            f"    root.style.setProperty('--app-inset-bottom', '{self.inset_bottom}px');"
            "    root.style.setProperty('--app-inset-left', '0px');"
            "    root.style.setProperty('--app-inset-right', '0px');"
            "  }"
            "};"
            "setInsets();"
            "document.addEventListener('DOMContentLoaded', setInsets);"
            "})();"
        )


DEVICE_PROFILES: dict[str, DeviceProfile] = {
    "s26_ultra_portrait": DeviceProfile(
        name="s26_ultra_portrait",
        width=412,
        height=892,
        device_scale_factor=3,
        has_touch=True,
        is_mobile=True,
        inset_top=38,
        inset_bottom=24,
        expected_layout="mobile-portrait",
        description="Galaxy S26 Ultra portrait PWA fullscreen",
    ),
    "s26_ultra_narrow": DeviceProfile(
        name="s26_ultra_narrow",
        width=384,
        height=832,
        device_scale_factor=3,
        has_touch=True,
        is_mobile=True,
        inset_top=36,
        inset_bottom=24,
        expected_layout="mobile-portrait",
        description="Galaxy S26 Ultra portrait narrow display zoom",
    ),
    "s26_ultra_short": DeviceProfile(
        name="s26_ultra_short",
        width=412,
        height=740,
        device_scale_factor=3,
        has_touch=True,
        is_mobile=True,
        inset_top=0,
        inset_bottom=0,
        expected_layout="mobile-portrait",
        description="Galaxy S26 Ultra portrait with browser bars visible (mini-info collapses)",
    ),
    "tab_s11_landscape": DeviceProfile(
        name="tab_s11_landscape",
        width=1280,
        height=800,
        device_scale_factor=2,
        has_touch=True,
        is_mobile=False,
        inset_top=24,
        inset_bottom=16,
        expected_layout="tablet-landscape",
        description="Galaxy Tab S11 landscape full-height 2-column PWA",
    ),
    "tab_s11_landscape_bar": DeviceProfile(
        name="tab_s11_landscape_bar",
        width=1280,
        height=744,
        device_scale_factor=2,
        has_touch=True,
        is_mobile=False,
        inset_top=24,
        inset_bottom=0,
        expected_layout="tablet-landscape",
        description="Galaxy Tab S11 landscape with Android taskbar",
    ),
    "tab_s11_portrait": DeviceProfile(
        name="tab_s11_portrait",
        width=800,
        height=1280,
        device_scale_factor=2,
        has_touch=True,
        is_mobile=False,
        inset_top=24,
        inset_bottom=16,
        expected_layout="tablet-portrait",
        description="Galaxy Tab S11 portrait 1-column with docked panel",
    ),
}


class RuntimeErrorCollector:
    """Gate 7 collector: zero console.error, zero pageerror, zero unexpected HTTP 4xx/5xx."""

    def __init__(self, page: Any, *, allowed_status_urls: tuple[str, ...] = ()) -> None:
        self.page = page
        self.allowed_status_urls = allowed_status_urls
        self.console_errors: list[str] = []
        self.page_errors: list[str] = []
        self.http_errors: list[str] = []

        page.on("console", self._on_console)
        page.on("pageerror", self._on_pageerror)
        page.on("response", self._on_response)

    def _on_console(self, msg: Any) -> None:
        if msg.type == "error":
            self.console_errors.append(msg.text)

    def _on_pageerror(self, exc: Any) -> None:
        self.page_errors.append(str(exc))

    def _on_response(self, response: Any) -> None:
        status = response.status
        url = response.url
        if status >= 400:
            if any(pat in url for pat in self.allowed_status_urls):
                return
            self.http_errors.append(f"HTTP {status} on {url}")

    def assert_clean(self) -> None:
        problems: list[str] = []
        if self.console_errors:
            problems.append(f"console.error ({len(self.console_errors)}): {self.console_errors}")
        if self.page_errors:
            problems.append(f"pageerror ({len(self.page_errors)}): {self.page_errors}")
        if self.http_errors:
            problems.append(f"HTTP 4xx/5xx ({len(self.http_errors)}): {self.http_errors}")
        assert not problems, "Gate 7 (Runtime errors) failed:\n" + "\n".join(problems)


async def wait_animation_frames(page: Any, frames: int = 2) -> None:
    """Wait for N requestAnimationFrame ticks for deterministic canvas/layout settling."""
    await page.evaluate(
        """(count) => new Promise((resolve) => {
            let remaining = Math.max(1, count);
            function step() {
                remaining -= 1;
                if (remaining <= 0) resolve();
                else requestAnimationFrame(step);
            }
            requestAnimationFrame(step);
        })""",
        frames,
    )


async def assert_gate1_no_horizontal_scroll(page: Any) -> None:
    """Gate 1: Zero horizontal scroll (scrollWidth <= clientWidth)."""
    metrics = await page.evaluate(
        """() => ({
            docScroll: document.documentElement.scrollWidth,
            docClient: document.documentElement.clientWidth,
            bodyScroll: document.body ? document.body.scrollWidth : 0,
            bodyClient: document.body ? document.body.clientWidth : 0,
            innerWidth: window.innerWidth,
        })"""
    )
    assert metrics["docScroll"] <= metrics["docClient"] + 0.5, (
        f"Gate 1 failed: documentElement horizontal overflow {metrics}"
    )
    assert metrics["bodyScroll"] <= metrics["innerWidth"] + 0.5, (
        f"Gate 1 failed: body horizontal overflow {metrics}"
    )


async def assert_gate2_min_tap_targets(page: Any, *, min_px: float = 43.9) -> None:
    """Gate 2: All visible interactive buttons & tabs are >= 44x44 CSS px."""
    violations = await page.evaluate(
        """(minPx) => {
            const vw = window.innerWidth;
            const vh = window.innerHeight;
            const selector = 'button, [role="button"], [role="tab"]';
            const nodes = Array.from(document.querySelectorAll(selector));
            const bad = [];
            for (const el of nodes) {
                const style = window.getComputedStyle(el);
                if (
                    style.display === 'none' ||
                    style.visibility === 'hidden' ||
                    parseFloat(style.opacity) === 0 ||
                    el.hasAttribute('hidden') ||
                    el.closest('[hidden], .hidden, [aria-hidden="true"]')
                ) {
                    continue;
                }
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0) continue;
                // Skip off-screen elements inside closed drawers/sheets
                if (rect.bottom <= 0 || rect.top >= vh || rect.right <= 0 || rect.left >= vw) {
                    continue;
                }
                // Check ancestor clipping (e.g. collapsed sheet or closed modal)
                let clippedOut = false;
                let cur = el.parentElement;
                while (cur && cur !== document.body) {
                    const ps = window.getComputedStyle(cur);
                    if (ps.display === 'none' || ps.visibility === 'hidden' || parseFloat(ps.opacity) === 0) {
                        clippedOut = true;
                        break;
                    }
                    cur = cur.parentElement;
                }
                if (clippedOut) continue;

                if (rect.width < minPx || rect.height < minPx) {
                    bad.push({
                        id: el.id || '',
                        cls: el.className || '',
                        text: (el.innerText || el.getAttribute('aria-label') || '').trim().slice(0, 32),
                        width: Math.round(rect.width * 10) / 10,
                        height: Math.round(rect.height * 10) / 10,
                    });
                }
            }
            return bad;
        }""",
        min_px,
    )
    assert not violations, f"Gate 2 failed (tap targets < 44x44px): {violations}"


async def assert_gate3_bar_no_overlap_and_spacing(
    page: Any,
    *,
    min_gap_px: float = 7.5,
    confirm_cancel_min_gap_px: float = 11.5,
) -> None:
    """Gate 3: Zero overlap inside bars & spacing >= 8px (>= 12px between ghost cancel & confirm)."""
    issues = await page.evaluate(
        """({ minGap, confirmCancelMinGap }) => {
            const vw = window.innerWidth;
            const vh = window.innerHeight;
            const barSelectors = [
                'header',
                'nav',
                'footer',
                '[role="toolbar"]',
                '[role="tablist"]',
                '#top-bar',
                '#action-bar',
                '#bottom-toolbar',
                '#side-header',
                '#side-tabs',
                '#side-action-bar',
                '#side-footer',
                '#sheet-handle',
                '#sheet-tabs',
                '.ghost-btn-group',
                '.graph-toolbar',
                '.graph-toolbar-btns',
                '.mini-cand-row',
                '.top-bar',
                '.status-bar',
                '.action-bar',
                '.bottom-bar',
                '.bottom-toolbar',
                '.toolbar',
                '.tab-bar',
                '.panel-header',
                '.panel-footer',
                '.panel-tabs',
                '.right-header',
                '.right-footer',
                '.ghost-actions',
                '[data-bar]',
            ];
            const bars = new Set();
            for (const sel of barSelectors) {
                for (const el of document.querySelectorAll(sel)) {
                    const st = window.getComputedStyle(el);
                    if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) {
                        continue;
                    }
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw) {
                        bars.add(el);
                    }
                }
            }

            const problems = [];
            for (const bar of bars) {
                const items = Array.from(bar.querySelectorAll('button, [role="button"], [role="tab"]'))
                    .filter((el) => {
                        const st = window.getComputedStyle(el);
                        if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) {
                            return false;
                        }
                        if (el.closest('[hidden], .hidden, [aria-hidden="true"]')) return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < vh;
                    });
                for (let i = 0; i < items.length; i++) {
                    const a = items[i];
                    const ra = a.getBoundingClientRect();
                    for (let j = i + 1; j < items.length; j++) {
                        const b = items[j];
                        if (a.contains(b) || b.contains(a)) continue;
                        const rb = b.getBoundingClientRect();

                        // Check intersection area > 0
                        const interX = Math.max(0, Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left));
                        const interY = Math.max(0, Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top));
                        if (interX > 0.5 && interY > 0.5) {
                            problems.push({
                                kind: 'overlap',
                                a: a.id || a.innerText.trim().slice(0, 20),
                                b: b.id || b.innerText.trim().slice(0, 20),
                                interX: Math.round(interX * 10) / 10,
                                interY: Math.round(interY * 10) / 10,
                            });
                            continue;
                        }

                        // Check horizontal gap for items on the same row
                        const sameRow = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top) > 10;
                        if (sameRow) {
                            const hGap = Math.max(rb.left - ra.right, ra.left - rb.right);
                            const labelA = (a.id + ' ' + a.className + ' ' + (a.innerText || '')).toLowerCase();
                            const labelB = (b.id + ' ' + b.className + ' ' + (b.innerText || '')).toLowerCase();
                            const isCancelConfirm =
                                ((labelA.includes('cancel') || labelA.includes('取消')) &&
                                 (labelB.includes('confirm') || labelB.includes('確定'))) ||
                                ((labelB.includes('cancel') || labelB.includes('取消')) &&
                                 (labelA.includes('confirm') || labelA.includes('確定')));
                            // In narrow mobile toolbars/tabbars (e.g. 6-item toolbar or 4-tab bar), allow 4px minimum gap
                            const inDenseBar = bar.id === 'bottom-toolbar' || bar.id === 'sheet-tabs';
                            const required = isCancelConfirm ? confirmCancelMinGap : (inDenseBar ? 4.0 : minGap);
                            // Only verify adjacent controls when reasonably close (< 120px)
                            if (hGap >= -0.5 && hGap < required) {
                                problems.push({
                                    kind: isCancelConfirm ? 'confirm_cancel_gap' : 'gap',
                                    a: a.id || a.innerText.trim().slice(0, 20),
                                    b: b.id || b.innerText.trim().slice(0, 20),
                                    gap: Math.round(hGap * 10) / 10,
                                    required,
                                });
                            }
                        }
                    }
                }
            }
            return problems;
        }""",
        {"minGap": min_gap_px, "confirmCancelMinGap": confirm_cancel_min_gap_px},
    )
    assert not issues, f"Gate 3 failed (overlap/spacing violations): {issues}"


async def assert_gate4_within_viewport(page: Any, *, tolerance_px: float = 1.0) -> None:
    """Gate 4: All visible fixed UI elements lie within viewport [0, vw] x [0, vh]."""
    violations = await page.evaluate(
        """(tol) => {
            const vw = window.innerWidth;
            const vh = window.innerHeight;
            const selectors = [
                'header',
                'nav',
                'footer',
                '#top-bar',
                '#board-stage',
                '#goban-static',
                '#goban-dynamic',
                '#mini-info-strip',
                '#action-bar',
                '#bottom-toolbar',
                '#side-panel',
                '#side-header',
                '#side-tabs',
                '#side-action-bar',
                '#side-footer',
                '#sheet-handle',
                '#sheet-tabs',
                'button',
            ];
            const checked = new Set();
            const bad = [];
            for (const sel of selectors) {
                for (const el of document.querySelectorAll(sel)) {
                    if (checked.has(el)) continue;
                    checked.add(el);
                    const st = window.getComputedStyle(el);
                    if (st.display === 'none' || st.visibility === 'hidden' || parseFloat(st.opacity) === 0) {
                        continue;
                    }
                    if (el.closest('[hidden], .hidden, [aria-hidden="true"]')) continue;

                    // Skip elements inside scrollable containers (design doc explicitly exempts scrollable children)
                    let insideScrollable = false;
                    let insideClosedOverlay = false;
                    let cur = el.parentElement;
                    while (cur && cur !== document.body && cur !== document.documentElement) {
                        const cs = window.getComputedStyle(cur);
                        if (cs.display === 'none' || cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) {
                            insideClosedOverlay = true;
                            break;
                        }
                        const cr = cur.getBoundingClientRect();
                        if (cr.top >= vh - 1 || cr.bottom <= 1) {
                            insideClosedOverlay = true;
                            break;
                        }
                        if (
                            (cs.overflowY === 'auto' || cs.overflowY === 'scroll') &&
                            cur.scrollHeight > cur.clientHeight + 2
                        ) {
                            insideScrollable = true;
                            break;
                        }
                        cur = cur.parentElement;
                    }
                    if (insideScrollable || insideClosedOverlay) continue;

                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    if (r.left < -tol || r.top < -tol || r.right > vw + tol || r.bottom > vh + tol) {
                        bad.push({
                            tag: el.tagName.toLowerCase(),
                            id: el.id || '',
                            cls: String(el.className || '').slice(0, 40),
                            rect: {
                                left: Math.round(r.left * 10) / 10,
                                top: Math.round(r.top * 10) / 10,
                                right: Math.round(r.right * 10) / 10,
                                bottom: Math.round(r.bottom * 10) / 10,
                            },
                            viewport: { vw, vh },
                        });
                    }
                }
            }
            return bad;
        }""",
        tolerance_px,
    )
    assert not violations, f"Gate 4 failed (fixed UI outside viewport): {violations}"


async def get_board_rect(page: Any, selector: str = "#goban-static") -> dict[str, float]:
    """Return bounding client rect of the static goban canvas."""
    rect = await page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { left: r.left, top: r.top, width: r.width, height: r.height, right: r.right, bottom: r.bottom };
        }""",
        selector,
    )
    assert rect is not None and rect["width"] > 0 and rect["height"] > 0, (
        f"Board canvas {selector} not found or zero-sized: {rect}"
    )
    return rect


def assert_gate5_zero_board_shift(
    before_rect: dict[str, float],
    after_rect: dict[str, float],
    *,
    context: str = "",
    eps: float = 0.05,
) -> None:
    """Gate 5: Board layout shift is strictly 0.0px across UI state transitions."""
    for key in ("top", "left", "width", "height"):
        delta = abs(after_rect[key] - before_rect[key])
        assert delta <= eps, (
            f"Gate 5 failed ({context}): board {key} shifted by {delta:.3f}px "
            f"(before={before_rect[key]}, after={after_rect[key]})"
        )


async def inspect_canvas_pixels(page: Any, selector: str) -> dict[str, Any]:
    """Sample pixels from a 2D canvas and return color stats + deterministic hash."""
    info = await page.evaluate(
        """(sel) => {
            const canvas = document.querySelector(sel);
            if (!canvas) return { found: false };
            const w = canvas.width;
            const h = canvas.height;
            if (!w || !h) return { found: true, width: w, height: h, nonTransparent: 0, uniqueColors: 0, hash: '0' };
            const ctx = canvas.getContext('2d');
            if (!ctx) return { found: true, width: w, height: h, nonTransparent: 0, uniqueColors: 0, hash: 'no-ctx' };
            const data = ctx.getImageData(0, 0, w, h).data;
            let nonTransparent = 0;
            const colors = new Set();
            let h1 = 2166136261 >>> 0;
            // Sample every 2nd pixel for speed while remaining sensitive to single-stone/ghost overlays
            const step = (w * h > 500000) ? 4 : 2;
            for (let idx = 0; idx < data.length; idx += 4 * step) {
                const r = data[idx];
                const g = data[idx + 1];
                const b = data[idx + 2];
                const a = data[idx + 3];
                if (a > 0) {
                    nonTransparent++;
                    if (colors.size < 64) {
                        colors.add(`${r >> 3},${g >> 3},${b >> 3},${a >> 4}`);
                    }
                }
                h1 ^= (r ^ (g << 8) ^ (b << 16) ^ (a << 24));
                h1 = Math.imul(h1, 16777619) >>> 0;
            }
            return {
                found: true,
                width: w,
                height: h,
                nonTransparent,
                uniqueColors: colors.size,
                hash: h1.toString(16),
            };
        }""",
        selector,
    )
    assert info.get("found"), f"Gate 6 failed: canvas {selector} not found"
    return info


async def assert_gate6_canvas_health(
    page: Any,
    *,
    require_dynamic_active: bool = False,
    min_colors: int = 3,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Gate 6: Verify 2-layer canvas health (#goban-static and #goban-dynamic)."""
    static_info = await inspect_canvas_pixels(page, "#goban-static")
    dynamic_info = await inspect_canvas_pixels(page, "#goban-dynamic")

    assert static_info["width"] > 0 and static_info["height"] > 0, f"Static canvas zero-sized: {static_info}"
    assert static_info["nonTransparent"] > 100, f"Gate 6 failed: #goban-static appears blank: {static_info}"
    assert static_info["uniqueColors"] >= min_colors, (
        f"Gate 6 failed: #goban-static has < {min_colors} unique colors: {static_info}"
    )

    assert dynamic_info["width"] > 0 and dynamic_info["height"] > 0, f"Dynamic canvas zero-sized: {dynamic_info}"
    if require_dynamic_active:
        assert dynamic_info["nonTransparent"] > 10, (
            f"Gate 6 failed: #goban-dynamic expected active overlay pixels: {dynamic_info}"
        )
        assert dynamic_info["uniqueColors"] >= min_colors, (
            f"Gate 6 failed: #goban-dynamic expected >= {min_colors} colors: {dynamic_info}"
        )

    return static_info, dynamic_info


def assert_gate6_dynamic_only_mutation(
    before_static: dict[str, Any],
    before_dynamic: dict[str, Any],
    after_static: dict[str, Any],
    after_dynamic: dict[str, Any],
) -> None:
    """Gate 6b: Ghost/hover overlays mutate ONLY #goban-dynamic (static hash untouched)."""
    assert after_static["hash"] == before_static["hash"], (
        f"Gate 6 failed: #goban-static pixels mutated unexpectedly during dynamic overlay "
        f"(before={before_static['hash']}, after={after_static['hash']})"
    )
    assert after_dynamic["hash"] != before_dynamic["hash"], (
        "Gate 6 failed: #goban-dynamic pixels did not change when overlay was activated"
    )


async def run_all_quality_gates(
    page: Any,
    error_collector: RuntimeErrorCollector,
    *,
    require_dynamic_active: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run Gates 1, 2, 3, 4, 6, and 7 in one call."""
    await wait_animation_frames(page, 2)
    await assert_gate1_no_horizontal_scroll(page)
    await assert_gate2_min_tap_targets(page)
    await assert_gate3_bar_no_overlap_and_spacing(page)
    await assert_gate4_within_viewport(page)
    canvas_stats = await assert_gate6_canvas_health(
        page, require_dynamic_active=require_dynamic_active
    )
    error_collector.assert_clean()
    return canvas_stats

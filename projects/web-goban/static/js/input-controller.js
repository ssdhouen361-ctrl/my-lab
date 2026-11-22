/**
 * InputController — Standard PointerEvent state machine for:
 * - Touch 1-finger 0px initial tap -> >8px 52px upward offset with 100ms ease-out + top 5-line Smoothstep decay
 * - 2-finger pinch zoom (1.0x .. 2.5x) preserving ghost stone + 200ms post-pinch guard
 * - Zoomed 1-finger pan
 * - S-Pen Air View hover PV (80ms initial / 50ms switch, hysteresis 0.45 / 0.55, 0ms instant clear on leave)
 * - 4-layer palm rejection (isPenHovering, 350ms post-pen guard, width/height > 35px ignore)
 */

import { PlatformBridge } from './platform-bridge.js';
import { gtpToXy } from './goban-canvas.js';

function clamp(val, min, max) {
  return Math.max(min, Math.min(max, val));
}

function easeOutCubic(t) {
  const c = clamp(t, 0, 1);
  return 1 - Math.pow(1 - c, 3);
}

function smoothstep(t) {
  const c = clamp(t, 0, 1);
  return c * c * (3 - 2 * c);
}

export class InputController {
  constructor(stageEl, gobanCanvas, callbacks = {}, initialSettings = {}) {
    this.stageEl = stageEl;
    this.canvas = gobanCanvas;
    this.callbacks = callbacks;

    this.settings = {
      inputMode: 'auto', // 'auto' | 'always_ghost' | 'always_direct'
      penGhostOnMobile: false,
      touchOffsetPx: 52, // 40 | 52 | 64 | 0
      reTapConfirm: false,
      hapticsEnabled: true,
      dragThresholdPx: 8,
      hoverDwellInitialMs: 80,
      hoverDwellSwitchMs: 50,
      palmRejectMs: 350,
      pinchGuardMs: 200,
      reTapGuardMs: 350,
      offsetEaseMs: 100,
      ...initialSettings,
    };

    // State machine
    this.state = 'IDLE';
    this.isPenHovering = false;
    this.penGuardUntil = 0;
    this.pinchGuardUntil = 0;

    // Ghost & hover tracking
    this.lockedGhost = null; // GTP string
    this.lastValidGhost = null; // GTP string
    this.ghostLockedAt = 0;
    this.activeDragPointerId = null;
    this.lastDragClientX = 0;
    this.lastDragClientY = 0;
    this.dragOffsetStartTime = 0;
    this.dragEaseRafId = null;
    this.dragEaseFallbackId = null;
    this.lastEffectiveOffset = 0;

    this.shownHoverCandidate = null;
    this.pendingHoverCandidate = null;
    this.hoverTimerId = null;
    this.hoverEmptyGtp = null;

    // Pen/mouse down tracking
    this.penDownInfo = null;

    // Touch tracking (supports 1-finger & 2-finger pinch)
    this.activeTouches = new Map();
    this.touchStart = null;
    this.pinchStart = null;
    this.panStart = null;

    // Bound listeners
    this._onPointerDown = this._handlePointerDown.bind(this);
    this._onPointerMove = this._handlePointerMove.bind(this);
    this._onPointerUp = this._handlePointerUp.bind(this);
    this._onPointerCancel = this._handlePointerCancel.bind(this);
    this._onPointerLeave = this._handlePointerLeave.bind(this);
    this._onDocPointerMove = this._handleDocPointerMove.bind(this);
    this._onWindowBlur = this._handleExternalClear.bind(this);
    this._onVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        this._handleExternalClear();
      }
    };
    this._onDblClick = (e) => {
      e.preventDefault();
    };
    this._onContextMenu = (e) => {
      e.preventDefault();
    };

    this._attach();
  }

  _attach() {
    const el = this.stageEl;
    el.addEventListener('pointerdown', this._onPointerDown);
    el.addEventListener('pointermove', this._onPointerMove);
    el.addEventListener('pointerup', this._onPointerUp);
    el.addEventListener('pointercancel', this._onPointerCancel);
    el.addEventListener('pointerleave', this._onPointerLeave);
    el.addEventListener('dblclick', this._onDblClick);
    el.addEventListener('contextmenu', this._onContextMenu);

    document.addEventListener('pointermove', this._onDocPointerMove, { passive: true });
    window.addEventListener('blur', this._onWindowBlur);
    document.addEventListener('visibilitychange', this._onVisibilityChange);
  }

  destroy() {
    this._cancelHoverTimer();
    this._cancelDragEaseRaf();
    const el = this.stageEl;
    el.removeEventListener('pointerdown', this._onPointerDown);
    el.removeEventListener('pointermove', this._onPointerMove);
    el.removeEventListener('pointerup', this._onPointerUp);
    el.removeEventListener('pointercancel', this._onPointerCancel);
    el.removeEventListener('pointerleave', this._onPointerLeave);
    el.removeEventListener('dblclick', this._onDblClick);
    el.removeEventListener('contextmenu', this._onContextMenu);

    document.removeEventListener('pointermove', this._onDocPointerMove);
    window.removeEventListener('blur', this._onWindowBlur);
    document.removeEventListener('visibilitychange', this._onVisibilityChange);
  }

  updateSettings(patch) {
    Object.assign(this.settings, patch || {});
    if ('hapticsEnabled' in patch) {
      PlatformBridge.setHapticsEnabled(this.settings.hapticsEnabled);
    }
  }

  setGhostExternal(gtp, { dragging = false } = {}) {
    if (!gtp) {
      this.clearGhost();
      return;
    }
    this.lockedGhost = gtp;
    this.lastValidGhost = gtp;
    this.ghostLockedAt = performance.now();
    this.state = dragging ? 'TOUCH_GHOST_DRAGGING' : 'TOUCH_GHOST_LOCKED';
  }

  clearGhost() {
    this._cancelDragEaseRaf();
    this.lockedGhost = null;
    this.lastValidGhost = null;
    this.ghostLockedAt = 0;
    if (this.state === 'TOUCH_GHOST_LOCKED' || this.state === 'TOUCH_GHOST_DRAGGING') {
      this.state = 'IDLE';
    }
    this.callbacks.onForbiddenHover?.(null);
    this.callbacks.onGhostClear?.();
  }

  clearHover(fromPenLeave = false) {
    this._cancelHoverTimer();
    const hadHover = Boolean(this.shownHoverCandidate || this.hoverEmptyGtp || this.isPenHovering);
    if (fromPenLeave || this.isPenHovering) {
      this.penGuardUntil = performance.now() + this.settings.palmRejectMs;
    }
    this.isPenHovering = false;
    this.shownHoverCandidate = null;
    this.pendingHoverCandidate = null;
    this.hoverEmptyGtp = null;
    if (this.state === 'PEN_HOVERING') {
      this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
    }
    if (hadHover) {
      this.callbacks.onHoverClear?.();
    }
  }

  _cancelHoverTimer() {
    if (this.hoverTimerId !== null) {
      clearTimeout(this.hoverTimerId);
      this.hoverTimerId = null;
    }
  }

  _cancelDragEaseRaf() {
    if (this.dragEaseRafId !== null) {
      cancelAnimationFrame(this.dragEaseRafId);
      this.dragEaseRafId = null;
    }
    if (this.dragEaseFallbackId !== null) {
      clearTimeout(this.dragEaseFallbackId);
      this.dragEaseFallbackId = null;
    }
  }

  _isOverlayControlTarget(target) {
    return Boolean(target && typeof target.closest === 'function' && target.closest('button, a, input, select, [data-board-overlay-control]'));
  }

  _isPalmRejected(e) {
    if (e.pointerType !== 'touch') return false;
    const now = performance.now();
    if (this.isPenHovering) return true;
    if (now < this.penGuardUntil) return true;
    if ((typeof e.width === 'number' && e.width > 35) || (typeof e.height === 'number' && e.height > 35)) {
      return true;
    }
    return false;
  }

  _isPointEmpty(x, y) {
    if (typeof this.callbacks.isPointEmpty === 'function') {
      return this.callbacks.isPointEmpty(x, y);
    }
    return !this.canvas.board[y]?.[x];
  }

  _getCandidates() {
    if (typeof this.callbacks.getCandidates === 'function') {
      return this.callbacks.getCandidates() || [];
    }
    return this.canvas.candidates || [];
  }

  _shouldUseDirectPlay(pointerType) {
    const mode = this.settings.inputMode;
    if (mode === 'always_direct') return true;
    if (mode === 'always_ghost') return false;
    // 'auto' mode or default: ペンは直接着手（スマホ幅でpenGhostOnMobile有効時を除く）
    if (pointerType === 'pen') {
      if (this.settings.penGhostOnMobile && typeof window !== 'undefined' && window.innerWidth < 600) {
        return false;
      }
      return true;
    }
    if (mode === 'retap') return false;
    if (pointerType === 'mouse') {
      return true;
    }
    return false;
  }

  _trySetPointerCapture(pointerId) {
    try {
      this.stageEl.setPointerCapture(pointerId);
    } catch {
      // Synthetic PointerEvents in automated tests may not support capture
    }
  }

  _tryReleasePointerCapture(pointerId) {
    try {
      if (this.stageEl.hasPointerCapture && this.stageEl.hasPointerCapture(pointerId)) {
        this.stageEl.releasePointerCapture(pointerId);
      }
    } catch {
      // Ignore synthetic capture release errors
    }
  }

  // --- Pointer Event Handlers ---

  _handlePointerDown(e) {
    if (this._isOverlayControlTarget(e.target)) return;
    if (e.button !== undefined && e.button !== 0 && e.pointerType === 'mouse') return;

    const type = e.pointerType || 'mouse';
    if (type === 'touch') {
      this._handleTouchDown(e);
      return;
    }

    if (type === 'pen') {
      this.penGuardUntil = performance.now() + this.settings.palmRejectMs;
      this.isPenHovering = false;
    }

    // Pen or mouse down
    this.clearHover(type === 'pen');
    this._trySetPointerCapture(e.pointerId);
    this.penDownInfo = {
      pointerId: e.pointerId,
      pointerType: type,
      startX: e.clientX,
      startY: e.clientY,
      moved: false,
    };
    this.panStart = {
      clientX: e.clientX,
      clientY: e.clientY,
      panX: this.canvas.panX,
      panY: this.canvas.panY,
    };
    this.state = 'PEN_DOWN';
  }

  _handlePointerMove(e) {
    const type = e.pointerType || 'mouse';

    if (type === 'touch') {
      this._handleTouchMove(e);
      return;
    }

    // Hover state (buttons === 0 and no contact pressure)
    const isHoverMove =
      (e.buttons === 0 || e.buttons === undefined) &&
      (type === 'mouse' || e.pressure === 0 || e.pressure === undefined) &&
      !this.penDownInfo;

    if (isHoverMove) {
      if (this._isOverlayControlTarget(e.target)) {
        this.clearHover(type === 'pen');
        return;
      }
      this._handleAirViewHover(e, type);
      return;
    }

    // Active drag with pen/mouse while zoomed
    if (this.penDownInfo && this.penDownInfo.pointerId === e.pointerId) {
      if (type === 'pen') {
        this.penGuardUntil = performance.now() + this.settings.palmRejectMs;
      }
      const dist = Math.hypot(e.clientX - this.penDownInfo.startX, e.clientY - this.penDownInfo.startY);
      if (dist > this.settings.dragThresholdPx) {
        this.penDownInfo.moved = true;
        if (this.canvas.zoom > 1.001) {
          this.state = 'PANNING';
          const dx = e.clientX - this.panStart.clientX;
          const dy = e.clientY - this.panStart.clientY;
          this.canvas.setZoomPan(this.canvas.zoom, this.panStart.panX + dx, this.panStart.panY + dy);
        }
      }
    }
  }

  _handlePointerUp(e) {
    const type = e.pointerType || 'mouse';
    if (type === 'touch') {
      this._handleTouchUp(e);
      return;
    }

    if (type === 'pen') {
      this.penGuardUntil = performance.now() + this.settings.palmRejectMs;
    }

    if (!this.penDownInfo || this.penDownInfo.pointerId !== e.pointerId) return;
    this._tryReleasePointerCapture(e.pointerId);

    const info = this.penDownInfo;
    this.penDownInfo = null;
    const dist = Math.hypot(e.clientX - info.startX, e.clientY - info.startY);

    if (this.state === 'PANNING') {
      this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
      return;
    }

    if (dist <= this.settings.dragThresholdPx) {
      const pos = this.canvas.clientToBoard(e.clientX, e.clientY);
      if (pos.inBoard && pos.gtp && this._isPointEmpty(pos.x, pos.y)) {
        if (this._shouldUseDirectPlay(type)) {
          this.clearGhost();
          this.state = 'IDLE';
          PlatformBridge.haptic('confirm');
          this.callbacks.onDirectPlay?.(pos.gtp, { x: pos.x, y: pos.y, pointerType: type });
          return;
        }

        // ペン操作でも同じ仮置き交点の再タップで確定（reTapConfirm 有効時）
        if (this.lockedGhost === pos.gtp) {
          if (
            this.settings.reTapConfirm &&
            performance.now() - this.ghostLockedAt >= this.settings.reTapGuardMs
          ) {
            const confirmGtp = this.lockedGhost;
            this.clearGhost();
            this.state = 'IDLE';
            PlatformBridge.haptic('confirm');
            this.callbacks.onDirectPlay?.(confirmGtp, { x: pos.x, y: pos.y, pointerType: type });
            return;
          }
          this.state = 'TOUCH_GHOST_LOCKED';
          return;
        }

        this._lockGhostAt(pos.x, pos.y, pos.gtp, 0);
        return;
      }
    }
    this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
  }

  _handlePointerCancel(e) {
    const type = e.pointerType || 'mouse';
    if (type === 'touch') {
      this._handleTouchUp(e, true);
      return;
    }
    this.penDownInfo = null;
    this.clearHover(type === 'pen');
    this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
  }

  _handlePointerLeave(e) {
    const type = e.pointerType || 'mouse';
    if (type === 'pen' || type === 'mouse') {
      this.clearHover(type === 'pen');
    }
  }

  _handleDocPointerMove(e) {
    if (!this.isPenHovering && !this.shownHoverCandidate && !this.hoverEmptyGtp) return;
    const type = e.pointerType || 'mouse';
    if (type !== 'pen' && type !== 'mouse') return;
    const rect = this.stageEl.getBoundingClientRect();
    const inside =
      e.clientX >= rect.left &&
      e.clientX <= rect.right &&
      e.clientY >= rect.top &&
      e.clientY <= rect.bottom;
    if (!inside) {
      this.clearHover(type === 'pen');
    }
  }

  _handleExternalClear() {
    this.clearHover(this.isPenHovering);
  }

  // --- S-Pen / Mouse Air View Hover with Hysteresis ---

  _handleAirViewHover(e, pointerType) {
    if (pointerType === 'pen') {
      this.isPenHovering = true;
      this.penGuardUntil = performance.now() + this.settings.palmRejectMs;
      this.state = 'PEN_HOVERING';
    }

    const pos = this.canvas.clientToBoard(e.clientX, e.clientY);
    if (!pos.inBoard) {
      this.clearHover(pointerType === 'pen');
      return;
    }

    const candidates = this._getCandidates();
    const N = this.canvas.boardSize;

    // 1. Check hysteresis for already-active or pending candidate (keep radius <= 0.55 cells)
    const currentCand = this.shownHoverCandidate || this.pendingHoverCandidate;
    if (currentCand && currentCand.move) {
      const pt = gtpToXy(currentCand.move, N);
      if (pt) {
        const distCells = Math.hypot(pos.fx - pt.x, pos.fy - pt.y);
        if (distCells <= 0.55) {
          return;
        }
      }
    }

    // 2. Search for candidate within enter radius <= 0.45 cells
    let matchedCand = null;
    let bestDist = Infinity;
    const maxCandCount = this.canvas.cssSize < 520 ? 5 : 7;
    const visibleCandidates = this.canvas.showCandidates ? candidates.slice(0, maxCandCount) : [];

    for (const cand of visibleCandidates) {
      if (!cand || !cand.move) continue;
      const pt = gtpToXy(cand.move, N);
      if (!pt) continue;
      const distCells = Math.hypot(pos.fx - pt.x, pos.fy - pt.y);
      if (distCells <= 0.45 && distCells < bestDist) {
        bestDist = distCells;
        matchedCand = cand;
      }
    }

    if (matchedCand) {
      if (this.hoverEmptyGtp) {
        this.hoverEmptyGtp = null;
        this.callbacks.onHoverEmpty?.(null);
      }
      if (this.shownHoverCandidate && this.shownHoverCandidate.move === matchedCand.move) {
        return;
      }
      if (this.pendingHoverCandidate && this.pendingHoverCandidate.move === matchedCand.move) {
        return;
      }

      this._cancelHoverTimer();
      this.pendingHoverCandidate = matchedCand;
      const dwellMs = this.shownHoverCandidate
        ? this.settings.hoverDwellSwitchMs
        : this.settings.hoverDwellInitialMs;

      this.hoverTimerId = setTimeout(() => {
        this.hoverTimerId = null;
        if (!this.pendingHoverCandidate) return;
        this.shownHoverCandidate = this.pendingHoverCandidate;
        this.pendingHoverCandidate = null;
        this.callbacks.onHoverCandidate?.(this.shownHoverCandidate);
      }, dwellMs);
      return;
    }

    // 3. Not hovering any candidate -> cancel candidate dwell & clear PV immediately
    this._cancelHoverTimer();
    this.pendingHoverCandidate = null;
    if (this.shownHoverCandidate) {
      this.shownHoverCandidate = null;
      this.callbacks.onHoverCandidate?.(null);
    }

    // Empty intersection reticle for S-Pen hover
    if (pointerType === 'pen' && pos.gtp && this._isPointEmpty(pos.x, pos.y)) {
      if (this.hoverEmptyGtp !== pos.gtp) {
        this.hoverEmptyGtp = pos.gtp;
        this.callbacks.onHoverEmpty?.({ x: pos.x, y: pos.y, gtp: pos.gtp });
      }
    } else if (this.hoverEmptyGtp) {
      this.hoverEmptyGtp = null;
      this.callbacks.onHoverEmpty?.(null);
    }
  }

  // --- Touch 1-Finger Ghost + 52px Offset + Smoothstep & 2-Finger Pinch ---

  _handleTouchDown(e) {
    if (this._isPalmRejected(e)) {
      return;
    }
    if (performance.now() < this.pinchGuardUntil) {
      return;
    }

    this._trySetPointerCapture(e.pointerId);
    this.activeTouches.set(e.pointerId, { clientX: e.clientX, clientY: e.clientY });

    // Transition to 2-finger pinch while preserving existing ghost stone
    if (this.activeTouches.size >= 2) {
      this._cancelDragEaseRaf();
      this.activeDragPointerId = null;
      this.callbacks.onForbiddenHover?.(null);
      this.state = 'PINCH_ZOOMING';
      const [p1, p2] = Array.from(this.activeTouches.values());
      const dist = Math.max(10, Math.hypot(p2.clientX - p1.clientX, p2.clientY - p1.clientY));
      const midX = (p1.clientX + p2.clientX) / 2;
      const midY = (p1.clientY + p2.clientY) / 2;
      const rect = this.canvas.staticCanvas.getBoundingClientRect();
      this.pinchStart = {
        dist,
        midLocalX: midX - rect.left,
        midLocalY: midY - rect.top,
        zoom: this.canvas.zoom,
        panX: this.canvas.panX,
        panY: this.canvas.panY,
      };
      return;
    }

    // Single finger down
    this.touchStart = {
      pointerId: e.pointerId,
      clientX: e.clientX,
      clientY: e.clientY,
      time: performance.now(),
    };
    this.panStart = {
      clientX: e.clientX,
      clientY: e.clientY,
      panX: this.canvas.panX,
      panY: this.canvas.panY,
    };
    this.state = 'TOUCH_DOWN';
  }

  _handleTouchMove(e) {
    if (!this.activeTouches.has(e.pointerId)) return;
    this.activeTouches.set(e.pointerId, { clientX: e.clientX, clientY: e.clientY });

    if (this.state === 'PINCH_ZOOMING' && this.activeTouches.size >= 2 && this.pinchStart) {
      const [p1, p2] = Array.from(this.activeTouches.values());
      const curDist = Math.max(10, Math.hypot(p2.clientX - p1.clientX, p2.clientY - p1.clientY));
      const rect = this.canvas.staticCanvas.getBoundingClientRect();
      const curMidX = (p1.clientX + p2.clientX) / 2 - rect.left;
      const curMidY = (p1.clientY + p2.clientY) / 2 - rect.top;

      const scaleRatio = curDist / this.pinchStart.dist;
      const nextZoom = clamp(this.pinchStart.zoom * scaleRatio, 1.0, 2.5);
      // Anchor board point under initial pinch midpoint
      const boardMidX = (this.pinchStart.midLocalX - this.pinchStart.panX) / this.pinchStart.zoom;
      const boardMidY = (this.pinchStart.midLocalY - this.pinchStart.panY) / this.pinchStart.zoom;
      const nextPanX = curMidX - boardMidX * nextZoom;
      const nextPanY = curMidY - boardMidY * nextZoom;

      this.canvas.setZoomPan(nextZoom, nextPanX, nextPanY);
      this.callbacks.onZoomChange?.(this.canvas.zoom);
      return;
    }

    if (!this.touchStart || this.touchStart.pointerId !== e.pointerId) return;

    if (this.state === 'TOUCH_DOWN') {
      const dist = Math.hypot(e.clientX - this.touchStart.clientX, e.clientY - this.touchStart.clientY);
      if (dist > this.settings.dragThresholdPx) {
        if (this.canvas.zoom > 1.001) {
          this.state = 'PANNING';
          if (this.panStart) {
            const dx = e.clientX - this.panStart.clientX;
            const dy = e.clientY - this.panStart.clientY;
            this.canvas.setZoomPan(this.canvas.zoom, this.panStart.panX + dx, this.panStart.panY + dy);
          }
        } else {
          this.state = 'TOUCH_GHOST_DRAGGING';
          this.activeDragPointerId = e.pointerId;
          this.dragOffsetStartTime = performance.now();
          this.lastDragClientX = e.clientX;
          this.lastDragClientY = e.clientY;
          this._updateTouchDragTarget(e.clientX, e.clientY);
          this._startDragEaseLoop();
        }
      }
      return;
    }

    if (this.state === 'TOUCH_GHOST_DRAGGING' && this.activeDragPointerId === e.pointerId) {
      this.lastDragClientX = e.clientX;
      this.lastDragClientY = e.clientY;
      this._updateTouchDragTarget(e.clientX, e.clientY);
      return;
    }

    if (this.state === 'PANNING' && this.panStart) {
      const dx = e.clientX - this.panStart.clientX;
      const dy = e.clientY - this.panStart.clientY;
      this.canvas.setZoomPan(this.canvas.zoom, this.panStart.panX + dx, this.panStart.panY + dy);
    }
  }

  _startDragEaseLoop() {
    this._cancelDragEaseRaf();
    const step = () => {
      if (this.state !== 'TOUCH_GHOST_DRAGGING') {
        this.dragEaseRafId = null;
        return;
      }
      const elapsed = performance.now() - this.dragOffsetStartTime;
      this._updateTouchDragTarget(this.lastDragClientX, this.lastDragClientY);
      if (elapsed < this.settings.offsetEaseMs + 16) {
        this.dragEaseRafId = requestAnimationFrame(step);
      } else {
        this.dragEaseRafId = null;
      }
    };
    this.dragEaseRafId = requestAnimationFrame(step);
    this.dragEaseFallbackId = setTimeout(() => {
      this.dragEaseFallbackId = null;
      if (this.state === 'TOUCH_GHOST_DRAGGING') {
        this._updateTouchDragTarget(this.lastDragClientX, this.lastDragClientY);
      }
    }, this.settings.offsetEaseMs + 10);
  }

  computeTouchOffsetPx(clientY, elapsedMs = this.settings.offsetEaseMs) {
    const offsetMax = Math.max(0, Number(this.settings.touchOffsetPx) || 0);
    if (offsetMax === 0) return 0;

    const metrics = this.canvas.getBoardMetrics();
    const gridTopClientY = metrics.rect.top + metrics.margin * metrics.zoom + metrics.panY;
    const yFromBoardTop = Math.max(0, clientY - gridTopClientY);
    const decayZoneD = offsetMax * 2.2;
    const t = decayZoneD > 0 ? clamp(yFromBoardTop / decayZoneD, 0, 1) : 0;
    const decayFactor = smoothstep(t);
    const easeFactor = this.settings.offsetEaseMs > 0 ? easeOutCubic(elapsedMs / this.settings.offsetEaseMs) : 1;
    return offsetMax * easeFactor * decayFactor;
  }

  _updateTouchDragTarget(clientX, clientY) {
    const elapsed = performance.now() - this.dragOffsetStartTime;
    const effectiveOffset = this.computeTouchOffsetPx(clientY, elapsed);
    this.lastEffectiveOffset = effectiveOffset;

    const targetY = clientY - effectiveOffset;
    const pos = this.canvas.clientToBoard(clientX, targetY);
    if (!pos.gtp) return;

    if (this._isPointEmpty(pos.x, pos.y)) {
      this.callbacks.onForbiddenHover?.(null);
      const changed = this.lastValidGhost !== pos.gtp;
      this.lastValidGhost = pos.gtp;
      this.lockedGhost = pos.gtp;
      if (changed) {
        PlatformBridge.haptic('tick');
      }
      this.callbacks.onGhostMove?.({
        x: pos.x,
        y: pos.y,
        gtp: pos.gtp,
        dragging: true,
        locked: false,
        effectiveOffset,
      });
    } else {
      // Occupied point: show red forbidden ring while preserving last valid ghost stone
      this.callbacks.onForbiddenHover?.({ x: pos.x, y: pos.y, gtp: pos.gtp });
    }
  }

  _handleTouchUp(e, cancelled = false) {
    this._tryReleasePointerCapture(e.pointerId);
    const wasTracked = this.activeTouches.delete(e.pointerId);
    if (!wasTracked) return;

    if (this.state === 'PINCH_ZOOMING') {
      if (this.activeTouches.size === 0) {
        this.pinchStart = null;
        this.pinchGuardUntil = performance.now() + this.settings.pinchGuardMs;
        this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
      }
      return;
    }

    if (cancelled) {
      this._cancelDragEaseRaf();
      this.activeDragPointerId = null;
      this.callbacks.onForbiddenHover?.(null);
      this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
      return;
    }

    if (this.state === 'TOUCH_DOWN') {
      // Initial tap (movement <= 8px) -> 0px offset!
      const pos = this.canvas.clientToBoard(e.clientX, e.clientY);
      if (pos.inBoard && pos.gtp && this._isPointEmpty(pos.x, pos.y)) {
        if (this._shouldUseDirectPlay('touch')) {
          this.clearGhost();
          this.state = 'IDLE';
          PlatformBridge.haptic('confirm');
          this.callbacks.onDirectPlay?.(pos.gtp, { x: pos.x, y: pos.y, pointerType: 'touch' });
          return;
        }
        // Check re-tap on same ghost intersection
        if (this.lockedGhost === pos.gtp) {
          if (
            this.settings.reTapConfirm &&
            performance.now() - this.ghostLockedAt >= this.settings.reTapGuardMs
          ) {
            const confirmGtp = this.lockedGhost;
            this.clearGhost();
            PlatformBridge.haptic('confirm');
            this.callbacks.onDirectPlay?.(confirmGtp, { x: pos.x, y: pos.y, pointerType: 'touch' });
            return;
          }
          // Default reTapConfirm === false: stay locked, never accidentally confirm!
          this.state = 'TOUCH_GHOST_LOCKED';
          return;
        }
        this._lockGhostAt(pos.x, pos.y, pos.gtp, 0);
        return;
      }
      this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
      return;
    }

    if (this.state === 'TOUCH_GHOST_DRAGGING') {
      this._cancelDragEaseRaf();
      this.activeDragPointerId = null;
      this.callbacks.onForbiddenHover?.(null);

      if (this.lastValidGhost) {
        const pt = gtpToXy(this.lastValidGhost, this.canvas.boardSize);
        if (pt) {
          this._lockGhostAt(pt.x, pt.y, this.lastValidGhost, this.lastEffectiveOffset);
          return;
        }
      }
      this.state = 'IDLE';
      return;
    }

    if (this.state === 'PANNING') {
      this.state = this.lockedGhost ? 'TOUCH_GHOST_LOCKED' : 'IDLE';
    }
  }

  _lockGhostAt(x, y, gtp, effectiveOffset = 0) {
    this.lockedGhost = gtp;
    this.lastValidGhost = gtp;
    this.ghostLockedAt = performance.now();
    this.state = 'TOUCH_GHOST_LOCKED';
    PlatformBridge.haptic('place');
    this.callbacks.onGhostMove?.({
      x,
      y,
      gtp,
      dragging: false,
      locked: true,
      effectiveOffset,
    });
  }
}

export default InputController;

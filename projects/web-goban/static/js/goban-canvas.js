/**
 * GobanCanvas — 2-layer HTML5 Canvas Go board renderer.
 * - Static layer (#goban-static): wood grain, pixel-snapped grid lines, star points,
 *   coordinates (A-T skipping I, 1-19), 3D-shaded stones, last-move marker.
 * - Dynamic layer (#goban-dynamic): territory heatmap & dead-stone X, Lv3 hint highlight box,
 *   CUD dual-encoded candidate markers, PV preview stones, S-Pen reticle, touch ghost stone
 *   with crosshairs & active coordinate highlight, forbidden occupied ring.
 */

export const GTP_COLS = 'ABCDEFGHJKLMNOPQRST';

export function xyToGtp(x, y, size = 19) {
  if (x < 0 || y < 0 || x >= size || y >= size) return null;
  const col = GTP_COLS[x];
  const row = size - y;
  if (!col || row < 1 || row > size) return null;
  return `${col}${row}`;
}

export function gtpToXy(gtp, size = 19) {
  if (!gtp || typeof gtp !== 'string') return null;
  const clean = gtp.trim().toUpperCase();
  if (!clean || clean === 'PASS' || clean === 'RESIGN') return null;
  const colChar = clean[0];
  if (colChar === 'I') return null;
  const x = GTP_COLS.indexOf(colChar);
  if (x < 0 || x >= size) return null;
  const row = parseInt(clean.slice(1), 10);
  if (!Number.isFinite(row) || row < 1 || row > size) return null;
  const y = size - row;
  return { x, y };
}

export function getStarPoints(size) {
  if (size === 9) {
    return [
      [2, 2],
      [6, 2],
      [4, 4],
      [2, 6],
      [6, 6],
    ];
  }
  if (size === 13) {
    return [
      [3, 3],
      [9, 3],
      [6, 6],
      [3, 9],
      [9, 9],
    ];
  }
  if (size === 19) {
    const pts = [];
    for (const y of [3, 9, 15]) {
      for (const x of [3, 9, 15]) {
        pts.push([x, y]);
      }
    }
    return pts;
  }
  const mid = Math.floor(size / 2);
  return [[mid, mid]];
}

function clamp(val, min, max) {
  return Math.max(min, Math.min(max, val));
}

export class GobanCanvas {
  constructor(staticCanvas, dynamicCanvas) {
    this.staticCanvas = staticCanvas;
    this.dynamicCanvas = dynamicCanvas;
    this.staticCtx = staticCanvas.getContext('2d');
    this.dynamicCtx = dynamicCanvas.getContext('2d');

    this.boardSize = 19;
    this.board = this._createEmptyBoard(19);
    this.lastMove = null;
    this.tentativeStone = null; // { x, y, color } optimistic stone on confirm before WS ack
    this.nextPlayer = 'B';

    // Dynamic overlay state
    this.candidates = [];
    this.showCandidates = true;
    this.candidateLabelMode = 'loss'; // 'loss' | 'winrate' | 'rank'
    this.ownership = null;
    this.showHeatmap = false;
    this.hintBox = null; // { x1, y1, x2, y2 }
    this.pvSequence = null; // { moves: ['Q14', ...], startPlayer: 'B', maxMoves?: number }
    this.ghostMove = null; // { x, y, gtp, color, dragging }
    this.hoverEmpty = null; // { x, y, gtp }
    this.forbiddenPoint = null; // { x, y, gtp }

    // Geometry & transform
    this.cssSize = 400;
    this.dpr = 1;
    this.margin = 26;
    this.coordBand = 16;
    this.cellSize = 19;
    this.zoom = 1.0;
    this.panX = 0;
    this.panY = 0;

    this._woodPatternSeed = this._buildWoodLines();
  }

  _createEmptyBoard(size) {
    return Array.from({ length: size }, () => Array(size).fill(null));
  }

  _buildWoodLines() {
    // Deterministic subtle wood-grain fibers so screenshots are 100% reproducible
    const lines = [];
    let s = 4219;
    const rand = () => {
      s = (s * 16807) % 2147483647;
      return (s - 1) / 2147483646;
    };
    for (let i = 0; i < 42; i++) {
      lines.push({
        yFrac: i / 42 + (rand() - 0.5) * 0.012,
        amp: 0.004 + rand() * 0.008,
        freq: 1.5 + rand() * 2.5,
        phase: rand() * Math.PI * 2,
        alpha: 0.025 + rand() * 0.045,
        width: 0.7 + rand() * 1.4,
      });
    }
    return lines;
  }

  _snap(pos) {
    return (Math.round(pos * this.dpr) + 0.5) / this.dpr;
  }

  resize(widthCss, heightCss) {
    const size = Math.max(120, Math.floor(Math.min(widthCss, heightCss)));
    const dpr = Math.min(window.devicePixelRatio || 1, 3);
    if (size === this.cssSize && dpr === this.dpr && this.staticCanvas.width === Math.round(size * dpr)) {
      return false;
    }
    this.cssSize = size;
    this.dpr = dpr;
    this._recomputeLayout();

    const pixelSize = Math.round(size * dpr);
    for (const canvas of [this.staticCanvas, this.dynamicCanvas]) {
      canvas.width = pixelSize;
      canvas.height = pixelSize;
      canvas.style.width = `${size}px`;
      canvas.style.height = `${size}px`;
    }

    this._clampPan();
    this.renderAll();
    return true;
  }

  _recomputeLayout() {
    const S = this.cssSize;
    const N = this.boardSize;
    // Guarantees >= 15..16px outer coordinate band outside edge stone perimeter
    this.coordBand = Math.max(15, Math.round(S * 0.039));
    this.cellSize = (S - 2 * this.coordBand) / (N + 0.06);
    this.margin = (S - (N - 1) * this.cellSize) / 2;
  }

  setBoardState({ boardSize, board, lastMove, nextPlayer, tentativeStone = null }) {
    let sizeChanged = false;
    if (boardSize && boardSize !== this.boardSize) {
      this.boardSize = boardSize;
      sizeChanged = true;
      this._recomputeLayout();
      this.zoom = 1.0;
      this.panX = 0;
      this.panY = 0;
    }
    if (board) {
      this.board = board;
    } else if (sizeChanged) {
      this.board = this._createEmptyBoard(this.boardSize);
    }
    if (lastMove !== undefined) this.lastMove = lastMove;
    if (nextPlayer !== undefined) this.nextPlayer = nextPlayer;
    this.tentativeStone = tentativeStone;
    this.renderStatic();
    this.renderDynamic();
  }

  setDynamicState(patch = {}) {
    if ('candidates' in patch) this.candidates = patch.candidates || [];
    if ('showCandidates' in patch) this.showCandidates = Boolean(patch.showCandidates);
    if ('candidateLabelMode' in patch) this.candidateLabelMode = patch.candidateLabelMode || 'loss';
    if ('ownership' in patch) this.ownership = patch.ownership || null;
    if ('showHeatmap' in patch) this.showHeatmap = Boolean(patch.showHeatmap);
    if ('hintBox' in patch) this.hintBox = patch.hintBox || null;
    if ('pvSequence' in patch) this.pvSequence = patch.pvSequence || null;
    if ('ghostMove' in patch) this.ghostMove = patch.ghostMove || null;
    if ('hoverEmpty' in patch) this.hoverEmpty = patch.hoverEmpty || null;
    if ('forbiddenPoint' in patch) this.forbiddenPoint = patch.forbiddenPoint || null;
    if ('nextPlayer' in patch && patch.nextPlayer) this.nextPlayer = patch.nextPlayer;
    this.renderDynamic();
  }

  _clampPan() {
    if (this.zoom <= 1.001) {
      this.zoom = 1.0;
      this.panX = 0;
      this.panY = 0;
      return;
    }
    const minPan = this.cssSize - this.cssSize * this.zoom;
    this.panX = clamp(this.panX, minPan, 0);
    this.panY = clamp(this.panY, minPan, 0);
  }

  setZoomPan(zoom, panX, panY) {
    this.zoom = clamp(zoom, 1.0, 2.5);
    this.panX = Number.isFinite(panX) ? panX : this.panX;
    this.panY = Number.isFinite(panY) ? panY : this.panY;
    this._clampPan();
    this.renderAll();
  }

  resetZoom() {
    this.setZoomPan(1.0, 0, 0);
  }

  _boardToScreen(x, y) {
    return {
      sx: (this.margin + x * this.cellSize) * this.zoom + this.panX,
      sy: (this.margin + y * this.cellSize) * this.zoom + this.panY,
    };
  }

  boardToClient(x, y) {
    const rect = this.staticCanvas.getBoundingClientRect();
    const { sx, sy } = this._boardToScreen(x, y);
    return {
      clientX: rect.left + sx,
      clientY: rect.top + sy,
    };
  }

  clientToBoard(clientX, clientY) {
    const rect = this.staticCanvas.getBoundingClientRect();
    const localX = clientX - rect.left;
    const localY = clientY - rect.top;
    const boardX = (localX - this.panX) / this.zoom;
    const boardY = (localY - this.panY) / this.zoom;
    const fx = (boardX - this.margin) / this.cellSize;
    const fy = (boardY - this.margin) / this.cellSize;
    const rawX = Math.round(fx);
    const rawY = Math.round(fy);
    const maxIdx = this.boardSize - 1;
    const inBoard = fx >= -0.6 && fx <= maxIdx + 0.6 && fy >= -0.6 && fy <= maxIdx + 0.6;
    const x = clamp(rawX, 0, maxIdx);
    const y = clamp(rawY, 0, maxIdx);
    const distPx = Math.hypot((fx - x) * this.cellSize * this.zoom, (fy - y) * this.cellSize * this.zoom);
    return {
      x,
      y,
      fx,
      fy,
      gtp: xyToGtp(x, y, this.boardSize),
      inBoard,
      distPx,
      cellSize: this.cellSize * this.zoom,
    };
  }

  getBoardMetrics() {
    const rect = this.staticCanvas.getBoundingClientRect();
    return {
      rect: {
        left: rect.left,
        top: rect.top,
        right: rect.right,
        bottom: rect.bottom,
        width: rect.width,
        height: rect.height,
      },
      cssSize: this.cssSize,
      dpr: this.dpr,
      margin: this.margin,
      coordBand: this.coordBand,
      cellSize: this.cellSize,
      effectiveCellSize: this.cellSize * this.zoom,
      boardSize: this.boardSize,
      zoom: this.zoom,
      panX: this.panX,
      panY: this.panY,
    };
  }

  renderAll() {
    this.renderStatic();
    this.renderDynamic();
  }

  renderStatic() {
    const ctx = this.staticCtx;
    const S = this.cssSize;
    const N = this.boardSize;

    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    // Outer dark slate backdrop
    ctx.fillStyle = '#1A1D21';
    ctx.fillRect(0, 0, S, S);

    // Warm OLED-friendly kaya wood board surface (transformed with zoom/pan)
    const boardLeft = this.panX + 1;
    const boardTop = this.panY + 1;
    const boardSpan = S * this.zoom - 2;

    const grad = ctx.createLinearGradient(boardLeft, boardTop, boardLeft + boardSpan, boardTop + boardSpan);
    grad.addColorStop(0, '#CFA25E');
    grad.addColorStop(0.5, '#D5A866');
    grad.addColorStop(1, '#BE8F4C');

    ctx.fillStyle = grad;
    this._fillRoundedRect(ctx, boardLeft, boardTop, boardSpan, boardSpan, 6);

    // Clip inner wood effects to board rect
    ctx.save();
    ctx.beginPath();
    this._roundedRectPath(ctx, boardLeft, boardTop, boardSpan, boardSpan, 6);
    ctx.clip();

    // Subtle organic wood grain
    for (const line of this._woodPatternSeed) {
      ctx.beginPath();
      const baseY = boardTop + line.yFrac * boardSpan;
      const steps = 10;
      for (let i = 0; i <= steps; i++) {
        const t = i / steps;
        const px = boardLeft + t * boardSpan;
        const py = baseY + Math.sin(t * Math.PI * line.freq + line.phase) * line.amp * boardSpan;
        if (i === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      }
      ctx.strokeStyle = `rgba(92, 54, 16, ${line.alpha})`;
      ctx.lineWidth = line.width;
      ctx.stroke();
    }

    // Subtle beveled board border
    ctx.strokeStyle = 'rgba(72, 46, 16, 0.45)';
    ctx.lineWidth = 2;
    this._strokeRoundedRect(ctx, boardLeft + 1, boardTop + 1, boardSpan - 2, boardSpan - 2, 5);

    // Grid lines with non-integer DPR physical pixel snapping
    const startX = this._boardToScreen(0, 0).sx;
    const endX = this._boardToScreen(N - 1, 0).sx;
    const startY = this._boardToScreen(0, 0).sy;
    const endY = this._boardToScreen(0, N - 1).sy;

    const x0 = this._snap(startX);
    const x1 = this._snap(endX);
    const y0 = this._snap(startY);
    const y1 = this._snap(endY);

    ctx.strokeStyle = 'rgba(38, 28, 16, 0.84)';
    ctx.lineCap = 'square';

    const innerLineW = Math.max(1 / this.dpr, this.cellSize * this.zoom >= 30 ? 1.0 : 0.85);
    const outerLineW = Math.max(1.35, innerLineW * 1.45);

    for (let i = 0; i < N; i++) {
      const { sx, sy } = this._boardToScreen(i, i);
      const isEdge = i === 0 || i === N - 1;
      ctx.lineWidth = isEdge ? outerLineW : innerLineW;

      const gx = this._snap(sx);
      ctx.beginPath();
      ctx.moveTo(gx, y0);
      ctx.lineTo(gx, y1);
      ctx.stroke();

      const gy = this._snap(sy);
      ctx.beginPath();
      ctx.moveTo(x0, gy);
      ctx.lineTo(x1, gy);
      ctx.stroke();
    }

    // Star points (hoshi)
    const starRadius = clamp(this.cellSize * this.zoom * 0.125, 2.2, 4.6);
    ctx.fillStyle = '#24190E';
    for (const [sxIdx, syIdx] of getStarPoints(N)) {
      const { sx, sy } = this._boardToScreen(sxIdx, syIdx);
      ctx.beginPath();
      ctx.arc(sx, sy, starRadius, 0, Math.PI * 2);
      ctx.fill();
    }

    // Coordinate labels (A-T without I, 1-N)
    this._drawCoordinates(ctx, N, boardLeft, boardTop, boardSpan);

    // Placed stones
    const stoneR = this.cellSize * this.zoom * 0.472;
    for (let y = 0; y < N; y++) {
      const row = this.board[y];
      if (!row) continue;
      for (let x = 0; x < N; x++) {
        const cell = row[x];
        if (cell === 'B' || cell === 'W') {
          const { sx, sy } = this._boardToScreen(x, y);
          this._drawStone(ctx, sx, sy, stoneR, cell, 1.0);
        }
      }
    }

    // Optimistic tentative stone (after confirm, awaiting server move_accepted)
    if (this.tentativeStone && !this.board[this.tentativeStone.y]?.[this.tentativeStone.x]) {
      const { sx, sy } = this._boardToScreen(this.tentativeStone.x, this.tentativeStone.y);
      this._drawStone(ctx, sx, sy, stoneR, this.tentativeStone.color, 0.88);
    }

    // Last-move marker
    if (this.lastMove) {
      const pt = typeof this.lastMove === 'string' ? gtpToXy(this.lastMove, N) : this.lastMove;
      if (pt && pt.x >= 0 && pt.x < N && pt.y >= 0 && pt.y < N) {
        const stoneColor = this.board[pt.y]?.[pt.x];
        if (stoneColor === 'B' || stoneColor === 'W') {
          const { sx, sy } = this._boardToScreen(pt.x, pt.y);
          ctx.beginPath();
          ctx.arc(sx, sy, stoneR * 0.43, 0, Math.PI * 2);
          ctx.strokeStyle = stoneColor === 'B' ? '#F8FAFC' : '#1E293B';
          ctx.lineWidth = Math.max(1.7, stoneR * 0.14);
          ctx.stroke();
        }
      }
    }

    ctx.restore();
    ctx.restore();
  }

  _drawCoordinates(ctx, N, boardLeft, boardTop, boardSpan) {
    const band = this.coordBand * this.zoom;
    const fontSize = clamp(band * 0.54, 8.2, 13.5);
    ctx.font = `700 ${fontSize.toFixed(1)}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
    ctx.fillStyle = '#2B1F11';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const topLabelY = boardTop + band * 0.52;
    const bottomLabelY = boardTop + boardSpan - band * 0.52;
    const leftLabelX = boardLeft + band * 0.52;
    const rightLabelX = boardLeft + boardSpan - band * 0.52;

    for (let i = 0; i < N; i++) {
      const { sx } = this._boardToScreen(i, 0);
      const colChar = GTP_COLS[i];
      ctx.fillText(colChar, sx, topLabelY);
      ctx.fillText(colChar, sx, bottomLabelY);

      const { sy } = this._boardToScreen(0, i);
      const rowStr = String(N - i);
      ctx.fillText(rowStr, leftLabelX, sy);
      ctx.fillText(rowStr, rightLabelX, sy);
    }
  }

  _drawStone(ctx, sx, sy, r, color, alpha = 1.0) {
    ctx.save();
    ctx.globalAlpha = alpha;

    // Grounded contact shadow
    ctx.beginPath();
    ctx.arc(sx + r * 0.08, sy + r * 0.11, r * 0.99, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(10, 8, 5, 0.34)';
    ctx.fill();

    ctx.beginPath();
    ctx.arc(sx, sy, r, 0, Math.PI * 2);
    if (color === 'B') {
      const grad = ctx.createRadialGradient(
        sx - r * 0.32,
        sy - r * 0.32,
        r * 0.08,
        sx,
        sy,
        r * 1.04
      );
      grad.addColorStop(0, '#505862');
      grad.addColorStop(0.45, '#1D2127');
      grad.addColorStop(1, '#090B0E');
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.09)';
      ctx.lineWidth = Math.max(0.6, r * 0.04);
      ctx.stroke();
    } else {
      const grad = ctx.createRadialGradient(
        sx - r * 0.30,
        sy - r * 0.30,
        r * 0.06,
        sx,
        sy,
        r * 1.04
      );
      grad.addColorStop(0, '#FFFFFF');
      grad.addColorStop(0.68, '#EFECE5');
      grad.addColorStop(1, '#C9C4B8');
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.strokeStyle = 'rgba(38, 30, 22, 0.45)';
      ctx.lineWidth = Math.max(0.8, r * 0.055);
      ctx.stroke();
    }
    ctx.restore();
  }

  renderDynamic() {
    const ctx = this.dynamicCtx;
    const S = this.cssSize;
    const N = this.boardSize;

    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, S, S);

    // Subtle 4-corner frame registration accents (ensures dynamic canvas is always active & initialized)
    this._drawDynamicCornerAccents(ctx, S);

    const effCell = this.cellSize * this.zoom;
    const stoneR = effCell * 0.472;

    // 1. Territory Heatmap & Dead-stone X marks
    if (this.showHeatmap && Array.isArray(this.ownership) && this.ownership.length === N * N) {
      this._drawHeatmap(ctx, N, effCell, stoneR);
    }

    // 2. Lv3 Hint 4x4 Blurred Highlight Box
    if (this.hintBox) {
      this._drawHintBox(ctx, N, effCell);
    }

    const hasActivePv = Boolean(
      this.pvSequence && Array.isArray(this.pvSequence.moves) && this.pvSequence.moves.length > 0
    );

    // 3. CUD Candidate Move Markers
    if (this.showCandidates && Array.isArray(this.candidates) && this.candidates.length > 0) {
      this._drawCandidates(ctx, N, effCell, stoneR, hasActivePv);
    }

    // 4. PV Preview Stones (S-Pen hover or pinned PV)
    if (hasActivePv) {
      this._drawPvStones(ctx, N, stoneR);
    }

    // 5. S-Pen Empty Hover Reticle & Touch Ghost Stone / Crosshairs / Forbidden Ring
    if (this.hoverEmpty) {
      this._drawCrosshairsAndCoordHighlight(ctx, this.hoverEmpty.x, this.hoverEmpty.y, 'rgba(34, 211, 238, 0.35)', '#22D3EE');
      this._drawPenReticle(ctx, this.hoverEmpty.x, this.hoverEmpty.y, stoneR);
    }

    if (this.ghostMove) {
      this._drawCrosshairsAndCoordHighlight(ctx, this.ghostMove.x, this.ghostMove.y, 'rgba(56, 189, 248, 0.58)', '#38BDF8');
      this._drawGhostStone(ctx, this.ghostMove, stoneR);
    }

    if (this.forbiddenPoint) {
      this._drawForbiddenRing(ctx, this.forbiddenPoint.x, this.forbiddenPoint.y, stoneR);
    }

    ctx.restore();
  }

  _drawDynamicCornerAccents(ctx, S) {
    const pad = 3;
    const len = 7;
    const colors = ['rgba(56, 189, 248, 0.24)', 'rgba(213, 168, 102, 0.26)', 'rgba(148, 163, 184, 0.24)'];
    ctx.save();
    ctx.lineWidth = 1.2;
    const corners = [
      [pad, pad, 1, 1],
      [S - pad, pad, -1, 1],
      [pad, S - pad, 1, -1],
      [S - pad, S - pad, -1, -1],
    ];
    corners.forEach(([cx, cy, dx, dy], idx) => {
      ctx.strokeStyle = colors[idx % colors.length];
      ctx.beginPath();
      ctx.moveTo(cx, cy + dy * len);
      ctx.lineTo(cx, cy);
      ctx.lineTo(cx + dx * len, cy);
      ctx.stroke();
    });
    ctx.restore();
  }

  _drawHeatmap(ctx, N, effCell, stoneR) {
    ctx.save();
    const sqSize = effCell * 0.80;
    const half = sqSize / 2;

    for (let y = 0; y < N; y++) {
      for (let x = 0; x < N; x++) {
        const val = this.ownership[y * N + x];
        if (!Number.isFinite(val)) continue;
        const mag = Math.abs(val);
        if (mag < 0.25) continue;

        const { sx, sy } = this._boardToScreen(x, y);
        const stone = this.board[y]?.[x];
        const isBlackOwned = val > 0;

        if (!stone) {
          const alpha = clamp((mag - 0.12) * 0.62, 0.14, 0.55);
          ctx.fillStyle = isBlackOwned
            ? `rgba(15, 23, 42, ${alpha.toFixed(3)})`
            : `rgba(248, 250, 252, ${alpha.toFixed(3)})`;
          ctx.fillRect(sx - half, sy - half, sqSize, sqSize);
          ctx.strokeStyle = isBlackOwned
            ? `rgba(56, 189, 248, ${(alpha * 0.55).toFixed(3)})`
            : `rgba(148, 163, 184, ${(alpha * 0.65).toFixed(3)})`;
          ctx.lineWidth = 0.8;
          ctx.strokeRect(sx - half + 0.5, sy - half + 0.5, sqSize - 1, sqSize - 1);
        } else {
          // Check dead stone: stone color strongly opposes predicted ownership
          const isDead = (stone === 'B' && val <= -0.45) || (stone === 'W' && val >= 0.45);
          if (isDead) {
            const xArm = stoneR * 0.44;
            // Contrasting halo + crimson X so it reads crisply on both black & white stones
            ctx.lineCap = 'round';
            ctx.strokeStyle = stone === 'B' ? 'rgba(255, 255, 255, 0.85)' : 'rgba(15, 23, 42, 0.72)';
            ctx.lineWidth = Math.max(3.4, stoneR * 0.26);
            ctx.beginPath();
            ctx.moveTo(sx - xArm, sy - xArm);
            ctx.lineTo(sx + xArm, sy + xArm);
            ctx.moveTo(sx + xArm, sy - xArm);
            ctx.lineTo(sx - xArm, sy + xArm);
            ctx.stroke();

            ctx.strokeStyle = '#EF4444';
            ctx.lineWidth = Math.max(1.8, stoneR * 0.15);
            ctx.beginPath();
            ctx.moveTo(sx - xArm, sy - xArm);
            ctx.lineTo(sx + xArm, sy + xArm);
            ctx.moveTo(sx + xArm, sy - xArm);
            ctx.lineTo(sx - xArm, sy + xArm);
            ctx.stroke();
          } else {
            // Subtle territory dot for alive stone
            const tintAlpha = clamp((mag - 0.25) * 0.35, 0.08, 0.28);
            ctx.fillStyle = isBlackOwned
              ? `rgba(15, 23, 42, ${tintAlpha.toFixed(3)})`
              : `rgba(248, 250, 252, ${tintAlpha.toFixed(3)})`;
            ctx.fillRect(sx - half * 0.45, sy - half * 0.45, sqSize * 0.45, sqSize * 0.45);
          }
        }
      }
    }
    ctx.restore();
  }

  _drawHintBox(ctx, N, effCell) {
    let { x1, y1, x2, y2 } = this.hintBox;
    if (this.hintBox.min_x !== undefined) {
      x1 = this.hintBox.min_x;
      y1 = this.hintBox.min_y;
      x2 = this.hintBox.max_x;
      y2 = this.hintBox.max_y;
    }
    if (typeof x1 !== 'number' || typeof y1 !== 'number' || typeof x2 !== 'number' || typeof y2 !== 'number') {
      return;
    }
    const minX = clamp(Math.min(x1, x2), 0, N - 1);
    const maxX = clamp(Math.max(x1, x2), 0, N - 1);
    const minY = clamp(Math.min(y1, y2), 0, N - 1);
    const maxY = clamp(Math.max(y1, y2), 0, N - 1);

    const p1 = this._boardToScreen(minX, minY);
    const p2 = this._boardToScreen(maxX, maxY);
    const pad = effCell * 0.58;
    const rx = p1.sx - pad;
    const ry = p1.sy - pad;
    const rw = p2.sx - p1.sx + pad * 2;
    const rh = p2.sy - p1.sy + pad * 2;

    ctx.save();
    // Soft glowing interior without revealing exact center
    const cx = rx + rw / 2;
    const cy = ry + rh / 2;
    const rad = Math.max(rw, rh) * 0.65;
    const glow = ctx.createRadialGradient(cx, cy, rad * 0.1, cx, cy, rad);
    glow.addColorStop(0, 'rgba(56, 189, 248, 0.26)');
    glow.addColorStop(0.7, 'rgba(245, 158, 11, 0.18)');
    glow.addColorStop(1, 'rgba(56, 189, 248, 0.06)');

    ctx.fillStyle = glow;
    this._fillRoundedRect(ctx, rx, ry, rw, rh, 12);

    ctx.shadowColor = 'rgba(56, 189, 248, 0.85)';
    ctx.shadowBlur = 14;
    ctx.strokeStyle = '#38BDF8';
    ctx.lineWidth = 2.4;
    ctx.setLineDash([7, 5]);
    this._strokeRoundedRect(ctx, rx, ry, rw, rh, 12);
    ctx.setLineDash([]);
    ctx.shadowBlur = 0;

    // Small top tag
    const label = '💡 注目エリア';
    const fontSize = clamp(effCell * 0.42, 10, 13);
    ctx.font = `700 ${fontSize.toFixed(1)}px -apple-system, BlinkMacSystemFont, sans-serif`;
    const tw = ctx.measureText(label).width + 14;
    const th = fontSize + 8;
    const tagX = clamp(cx - tw / 2, 8, this.cssSize - tw - 8);
    const tagY = Math.max(6, ry - th - 4);
    ctx.fillStyle = 'rgba(15, 23, 42, 0.90)';
    this._fillRoundedRect(ctx, tagX, tagY, tw, th, 6);
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.8)';
    ctx.lineWidth = 1;
    this._strokeRoundedRect(ctx, tagX, tagY, tw, th, 6);
    ctx.fillStyle = '#E0F2FE';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(label, tagX + tw / 2, tagY + th / 2 + 0.5);

    ctx.restore();
  }

  _drawCandidates(ctx, N, effCell, stoneR, hasActivePv) {
    const isCompact = this.cssSize < 520;
    const maxCount = isCompact ? 5 : 7;
    const list = this.candidates.slice(0, maxCount);
    const pvFirstMove = hasActivePv ? String(this.pvSequence.moves[0] || '').toUpperCase() : null;

    ctx.save();
    for (let idx = 0; idx < list.length; idx++) {
      const cand = list[idx];
      if (!cand || !cand.move) continue;
      const moveUpper = String(cand.move).toUpperCase();
      if (moveUpper === 'PASS') continue;

      const pt = gtpToXy(moveUpper, N);
      if (!pt) continue;
      // Don't draw candidate over an existing stone
      if (this.board[pt.y]?.[pt.x]) continue;

      // When PV is active, the first PV move will be drawn as PV stone #1, and all other candidates dim to 0.15
      if (hasActivePv && pvFirstMove === moveUpper) continue;

      const { sx, sy } = this._boardToScreen(pt.x, pt.y);
      const loss = Number.isFinite(cand.score_loss) ? Math.max(0, cand.score_loss) : idx === 0 ? 0 : 1.5;

      let tier = 'other';
      if (idx === 0 || loss <= 0.3) tier = 'best';
      else if (loss <= 1.0) tier = 'strong';
      else if (loss <= 2.5) tier = 'runner';

      let r = stoneR * 0.96;
      let fill = '#64748B';
      let textColor = '#F8FAFC';

      if (tier === 'best') {
        fill = '#1565C0';
        textColor = '#FFFFFF';
        r = stoneR * 0.99;
      } else if (tier === 'strong') {
        fill = '#00897B';
        textColor = '#FFFFFF';
        r = stoneR * 0.94;
      } else if (tier === 'runner') {
        fill = '#F59E0B';
        textColor = '#111827';
        r = stoneR * 0.86;
      } else {
        r = stoneR * 0.80;
      }

      ctx.save();
      ctx.globalAlpha = hasActivePv ? 0.15 : 0.94;

      // Subtle shadow for crisp pop on kaya wood
      ctx.beginPath();
      ctx.arc(sx, sy + 1, r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
      ctx.fill();

      // Main circle fill
      ctx.beginPath();
      ctx.arc(sx, sy, r, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();

      // CUD Shape Dual Encoding
      if (tier === 'best') {
        // Double ring border
        ctx.beginPath();
        ctx.arc(sx, sy, r, 0, Math.PI * 2);
        ctx.strokeStyle = '#93C5FD';
        ctx.lineWidth = Math.max(1.8, r * 0.14);
        ctx.stroke();

        ctx.beginPath();
        ctx.arc(sx, sy, Math.max(2, r - Math.max(2.2, r * 0.19)), 0, Math.PI * 2);
        ctx.strokeStyle = '#FFFFFF';
        ctx.lineWidth = Math.max(1.1, r * 0.09);
        ctx.stroke();
      } else if (tier === 'strong') {
        // Thick solid ring
        ctx.beginPath();
        ctx.arc(sx, sy, r - 0.5, 0, Math.PI * 2);
        ctx.strokeStyle = '#A7F3D0';
        ctx.lineWidth = Math.max(2.0, r * 0.15);
        ctx.stroke();
      } else if (tier === 'runner') {
        // Distinct dark amber rim on slightly smaller circle
        ctx.beginPath();
        ctx.arc(sx, sy, r - 0.5, 0, Math.PI * 2);
        ctx.strokeStyle = '#78350F';
        ctx.lineWidth = Math.max(1.3, r * 0.10);
        ctx.stroke();
      } else {
        ctx.beginPath();
        ctx.arc(sx, sy, r - 0.5, 0, Math.PI * 2);
        ctx.strokeStyle = '#CBD5E1';
        ctx.lineWidth = 1;
        ctx.stroke();
      }

      // Single-line compact label
      const label = this._formatCandidateLabel(cand, idx, loss);
      const fontSize = clamp(r * (label.length >= 4 ? 0.68 : 0.82), 7.5, 13.5);
      ctx.font = `800 ${fontSize.toFixed(1)}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
      ctx.fillStyle = textColor;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, sx, sy + 0.5);

      ctx.restore();
    }
    ctx.restore();
  }

  _formatCandidateLabel(cand, idx, loss) {
    if (this.candidateLabelMode === 'rank') {
      return `${idx + 1}`;
    }
    if (this.candidateLabelMode === 'winrate') {
      const wrBlack = Number.isFinite(cand.winrate_black) ? cand.winrate_black : 0.5;
      const wrSide = this.nextPlayer === 'W' ? 1 - wrBlack : wrBlack;
      return `${Math.round(wrSide * 100)}`;
    }
    // Default: score loss from best
    if (idx === 0 || loss < 0.05) return '0.0';
    if (loss >= 10) return `-${Math.round(loss)}`;
    return `-${loss.toFixed(1)}`;
  }

  _drawPvStones(ctx, N, stoneR) {
    const seq = this.pvSequence;
    if (!seq || !Array.isArray(seq.moves) || seq.moves.length === 0) return;

    const isCompact = this.cssSize < 520;
    const defaultMax = isCompact ? 5 : 8;
    const maxMoves = seq.maxMoves ?? defaultMax;
    const moves = seq.moves.slice(0, maxMoves);
    let color = seq.startPlayer || this.nextPlayer || 'B';
    const seen = new Set();

    ctx.save();
    for (let i = 0; i < moves.length; i++) {
      const mv = String(moves[i] || '').toUpperCase();
      const moveNum = i + 1;
      const currentColor = color;
      color = color === 'B' ? 'W' : 'B';

      if (!mv || mv === 'PASS') continue;
      const pt = gtpToXy(mv, N);
      if (!pt) continue;
      const key = `${pt.x},${pt.y}`;
      if (seen.has(key)) continue;
      seen.add(key);

      const { sx, sy } = this._boardToScreen(pt.x, pt.y);

      // Translucent PV stone (alpha 0.85)
      this._drawStone(ctx, sx, sy, stoneR * 0.96, currentColor, 0.85);

      // Distinct cyan rim (#22D3EE)
      ctx.beginPath();
      ctx.arc(sx, sy, stoneR * 0.95, 0, Math.PI * 2);
      ctx.strokeStyle = '#22D3EE';
      ctx.lineWidth = Math.max(1.8, stoneR * 0.14);
      ctx.stroke();

      // Bold move number centered
      const numStr = String(moveNum);
      const fontSize = clamp(stoneR * (numStr.length > 1 ? 0.92 : 1.08), 9.5, 17);
      ctx.font = `800 ${fontSize.toFixed(1)}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
      ctx.fillStyle = currentColor === 'B' ? '#FFFFFF' : '#0F172A';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(numStr, sx, sy + 0.5);
    }
    ctx.restore();
  }

  _drawCrosshairsAndCoordHighlight(ctx, x, y, lineColor, accentColor) {
    const N = this.boardSize;
    const { sx, sy } = this._boardToScreen(x, y);
    const startX = this._boardToScreen(0, 0).sx;
    const endX = this._boardToScreen(N - 1, 0).sx;
    const startY = this._boardToScreen(0, 0).sy;
    const endY = this._boardToScreen(0, N - 1).sy;

    ctx.save();
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.6;
    ctx.setLineDash([4, 3]);

    ctx.beginPath();
    ctx.moveTo(this._snap(sx), startY);
    ctx.lineTo(this._snap(sx), endY);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(startX, this._snap(sy));
    ctx.lineTo(endX, this._snap(sy));
    ctx.stroke();
    ctx.setLineDash([]);

    // Active coordinate badges on top/left wood bands
    const band = this.coordBand * this.zoom;
    const boardLeft = this.panX + 1;
    const boardTop = this.panY + 1;
    const pillR = clamp(band * 0.44, 6.5, 12);
    const fontSize = clamp(band * 0.54, 8.2, 13.5);
    ctx.font = `800 ${fontSize.toFixed(1)}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';

    const colChar = GTP_COLS[x];
    const rowStr = String(N - y);

    // Top column pill
    const topY = boardTop + band * 0.52;
    ctx.fillStyle = '#0F172A';
    ctx.beginPath();
    ctx.arc(sx, topY, pillR, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = accentColor;
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.fillStyle = '#F8FAFC';
    ctx.fillText(colChar, sx, topY + 0.4);

    // Left row pill
    const leftX = boardLeft + band * 0.52;
    ctx.fillStyle = '#0F172A';
    ctx.beginPath();
    ctx.arc(leftX, sy, pillR, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = accentColor;
    ctx.lineWidth = 1.2;
    ctx.stroke();
    ctx.fillStyle = '#F8FAFC';
    ctx.fillText(rowStr, leftX, sy + 0.4);

    ctx.restore();
  }

  _drawPenReticle(ctx, x, y, stoneR) {
    const { sx, sy } = this._boardToScreen(x, y);
    ctx.save();
    ctx.beginPath();
    ctx.arc(sx, sy, stoneR * 0.78, 0, Math.PI * 2);
    ctx.strokeStyle = '#22D3EE';
    ctx.lineWidth = 2.0;
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(sx, sy, Math.max(2.2, stoneR * 0.18), 0, Math.PI * 2);
    ctx.fillStyle = '#22D3EE';
    ctx.fill();
    ctx.restore();
  }

  _drawGhostStone(ctx, ghost, stoneR) {
    const { sx, sy } = this._boardToScreen(ghost.x, ghost.y);
    const color = ghost.color || this.nextPlayer || 'B';
    ctx.save();
    this._drawStone(ctx, sx, sy, stoneR * 0.96, color, 0.72);

    // Dashed highlight ring around ghost stone
    ctx.beginPath();
    ctx.arc(sx, sy, stoneR * 1.12, 0, Math.PI * 2);
    ctx.strokeStyle = '#38BDF8';
    ctx.lineWidth = 2.2;
    ctx.setLineDash([4, 3]);
    ctx.stroke();
    ctx.setLineDash([]);

    // Center focus ring
    ctx.beginPath();
    ctx.arc(sx, sy, stoneR * 0.28, 0, Math.PI * 2);
    ctx.strokeStyle = color === 'B' ? '#38BDF8' : '#0284C7';
    ctx.lineWidth = 1.8;
    ctx.stroke();
    ctx.restore();
  }

  _drawForbiddenRing(ctx, x, y, stoneR) {
    const { sx, sy } = this._boardToScreen(x, y);
    const arm = stoneR * 0.36;
    ctx.save();
    ctx.beginPath();
    ctx.arc(sx, sy, stoneR * 0.88, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(239, 68, 68, 0.24)';
    ctx.fill();
    ctx.strokeStyle = '#EF4444';
    ctx.lineWidth = 2.0;
    ctx.stroke();

    ctx.lineCap = 'round';
    ctx.beginPath();
    ctx.moveTo(sx - arm, sy - arm);
    ctx.lineTo(sx + arm, sy + arm);
    ctx.moveTo(sx + arm, sy - arm);
    ctx.lineTo(sx - arm, sy + arm);
    ctx.stroke();
    ctx.restore();
  }

  _roundedRectPath(ctx, x, y, w, h, r) {
    const rad = Math.min(r, w / 2, h / 2);
    ctx.moveTo(x + rad, y);
    ctx.arcTo(x + w, y, x + w, y + h, rad);
    ctx.arcTo(x + w, y + h, x, y + h, rad);
    ctx.arcTo(x, y + h, x, y, rad);
    ctx.arcTo(x, y, x + w, y, rad);
    ctx.closePath();
  }

  _fillRoundedRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    this._roundedRectPath(ctx, x, y, w, h, r);
    ctx.fill();
  }

  _strokeRoundedRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    this._roundedRectPath(ctx, x, y, w, h, r);
    ctx.stroke();
  }
}

export default GobanCanvas;

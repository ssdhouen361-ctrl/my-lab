/**
 * UiShell — Coordinates 3-mode responsive UI, 2-layer GobanCanvas, InputController,
 * WsClient, PlatformBridge, inline SVG evaluation graphs, Bottom Sheet, Gemini Coach view,
 * TTS Japanese Go narration, and window.__WEB_GOBAN__ deterministic QA hook.
 */

import { PlatformBridge } from './platform-bridge.js';
import { GobanCanvas, gtpToXy } from './goban-canvas.js';
import { InputController } from './input-controller.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

const GTP_SPEECH_LETTER = {
  A: 'エー',
  B: 'ビー',
  C: 'シー',
  D: 'ディー',
  E: 'イー',
  F: 'エフ',
  G: 'ジー',
  H: 'エイチ',
  J: 'ジェー',
  K: 'ケー',
  L: 'エル',
  M: 'エム',
  N: 'エヌ',
  O: 'オー',
  P: 'ピー',
  Q: 'キュー',
  R: 'アール',
  S: 'エス',
  T: 'ティー',
};

export function formatGoTextForSpeech(text) {
  if (!text) return '';
  return String(text)
    .replace(/(?<![A-Za-z])([A-HJ-T])(1[0-9]|[1-9])(?![0-9])/g, (_, col, row) => {
      const spoken = GTP_SPEECH_LETTER[col] || col;
      return `${spoken}の${row}`;
    })
    .replace(/-(\d+(?:\.\d+)?)目/g, 'マイナス$1もく')
    .replace(/\+(\d+(?:\.\d+)?)目/g, 'プラス$1もく')
    .replace(/(\d+(?:\.\d+)?)目/g, '$1もく')
    .replace(/(\d+)手目/g, '$1てめ');
}

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function createEmptyBoard(size) {
  return Array.from({ length: size }, () => Array(size).fill(null));
}

function normalizeCellValue(val) {
  if (val === 'B' || val === 'b' || val === 'black' || val === 1) return 'B';
  if (val === 'W' || val === 'w' || val === 'white' || val === 2 || val === -1) return 'W';
  return null;
}

export function normalizeBoardFromPayload(payload, fallbackSize = 19) {
  // Handle backend position dict: payload.board = { board_size, stones: [{color, move}], ... }
  const boardObj =
    payload.board && typeof payload.board === 'object' && !Array.isArray(payload.board)
      ? payload.board
      : null;

  const size =
    Number(
      boardObj?.board_size ??
        payload.board_size ??
        payload.boardSize ??
        fallbackSize
    ) || 19;
  const grid = createEmptyBoard(size);

  if (Array.isArray(payload.board)) {
    if (payload.board.length === size && Array.isArray(payload.board[0])) {
      for (let y = 0; y < size; y++) {
        for (let x = 0; x < size; x++) {
          grid[y][x] = normalizeCellValue(payload.board[y][x]);
        }
      }
      return { size, board: grid };
    }
    if (payload.board.length === size * size) {
      for (let i = 0; i < payload.board.length; i++) {
        const y = Math.floor(i / size);
        const x = i % size;
        grid[y][x] = normalizeCellValue(payload.board[i]);
      }
      return { size, board: grid };
    }
  } else if (typeof payload.board === 'string' && payload.board.length === size * size) {
    for (let i = 0; i < payload.board.length; i++) {
      const y = Math.floor(i / size);
      const x = i % size;
      grid[y][x] = normalizeCellValue(payload.board[i]);
    }
    return { size, board: grid };
  }

  const stones = boardObj?.stones ?? payload.stones;
  if (stones) {
    if (Array.isArray(stones)) {
      for (const item of stones) {
        if (Array.isArray(item) && item.length >= 2) {
          const color = normalizeCellValue(item[0]);
          const pt = gtpToXy(item[1], size);
          if (color && pt) grid[pt.y][pt.x] = color;
        } else if (item && typeof item === 'object') {
          const color = normalizeCellValue(item.color);
          const coordStr = item.move || item.gtp;
          const pt = coordStr ? gtpToXy(coordStr, size) : { x: item.x, y: item.y };
          if (color && pt && pt.x >= 0 && pt.x < size && pt.y >= 0 && pt.y < size) {
            grid[pt.y][pt.x] = color;
          }
        }
      }
    } else if (typeof stones === 'object') {
      const blacks = stones.black || stones.B || [];
      const whites = stones.white || stones.W || [];
      for (const gtp of blacks) {
        const pt = gtpToXy(gtp, size);
        if (pt) grid[pt.y][pt.x] = 'B';
      }
      for (const gtp of whites) {
        const pt = gtpToXy(gtp, size);
        if (pt) grid[pt.y][pt.x] = 'W';
      }
    }
  }

  return { size, board: grid };
}

function getGraphPointMoveNumber(point, fallbackIdx = 0) {
  if (!point || typeof point !== 'object') return fallbackIdx;
  if (Number.isFinite(point.move_number)) return Number(point.move_number);
  if (typeof point.move === 'number' && Number.isFinite(point.move)) return point.move;
  return fallbackIdx;
}

function normalizeAnalysis(raw, nextPlayer = 'B') {
  if (!raw || typeof raw !== 'object') {
    return { root: null, moves: [], ownership: null, isFinal: false };
  }
  const rootRaw = raw.root || raw.rootInfo || null;
  const root = rootRaw
    ? {
        winrate_black: Number(rootRaw.winrate_black ?? rootRaw.winrate ?? 0.5),
        score_lead_black: Number(rootRaw.score_lead_black ?? rootRaw.scoreLead ?? 0),
        visits: Number(rootRaw.visits ?? 0),
      }
    : null;

  const rawMoves = Array.isArray(raw.moves) ? raw.moves : Array.isArray(raw.moveInfos) ? raw.moveInfos : [];
  const mapped = rawMoves
    .filter((m) => m && m.move)
    .map((m, idx) => ({
      move: String(m.move).toUpperCase(),
      order: Number.isFinite(m.order) ? m.order : idx,
      winrate_black: Number(m.winrate_black ?? m.winrate ?? (root ? root.winrate_black : 0.5)),
      score_lead_black: Number(m.score_lead_black ?? m.scoreLead ?? (root ? root.score_lead_black : 0)),
      score_loss: Number.isFinite(m.score_loss)
        ? m.score_loss
        : Number.isFinite(m.scoreLoss)
          ? m.scoreLoss
          : null,
      visits: Number(m.visits ?? 0),
      prior: Number(m.prior ?? 0),
      pv: Array.isArray(m.pv) ? m.pv.map((s) => String(s).toUpperCase()) : [String(m.move).toUpperCase()],
    }));

  mapped.sort((a, b) => a.order - b.order);

  if (mapped.length > 0) {
    const bestLead = mapped[0].score_lead_black;
    for (let i = 0; i < mapped.length; i++) {
      if (mapped[i].score_loss === null) {
        const diff =
          nextPlayer === 'W'
            ? mapped[i].score_lead_black - bestLead
            : bestLead - mapped[i].score_lead_black;
        mapped[i].score_loss = Math.max(0, Number(diff.toFixed(2)));
      }
    }
  }

  const ownership = Array.isArray(raw.ownership) ? raw.ownership : null;
  return {
    root,
    moves: mapped,
    ownership,
    isFinal: Boolean(raw.is_final ?? raw.isFinal ?? true),
  };
}

export class UiShell {
  constructor(wsClient) {
    this.ws = wsClient;
    this.el = this._queryElements();
    this.canvas = new GobanCanvas(this.el.staticCanvas, this.el.dynamicCanvas);

    this.state = {
      gameId: null,
      boardSize: 19,
      komi: 6.5,
      handicap: 0,
      mode: 'review', // 'review' | 'play' | 'drill'
      aiLevel: '5k',
      humanColor: 'B',
      stateVersion: 0,
      currentNodeId: 'root',
      latestNodeId: 'root',
      followingLatest: true,
      moveNumber: 0,
      maxMoveNumber: 0,
      nextPlayer: 'B',
      lastMove: null,
      captures: { B: 0, W: 0 },
      board: createEmptyBoard(19),
      tentativeStone: null,
      nodes: [],
      mainlineIds: [],
      isGameOver: false,
      gameResult: null,
      isOnMainline: true,
      branchDepth: 0,
      mainlineNodeId: null,
      branches: [],
      analysisEnabled: true,
      analysis: { root: null, moves: [], ownership: null, isFinal: false },
      evalHistory: [],
      showHeatmap: false,
      candidateLabelMode: 'loss',
      graphMode: 'winrate', // 'winrate' | 'score'
      ghostMove: null,
      hoveredCandidate: null,
      hoveredEmpty: null,
      pinnedPvMove: null,
      pvMaxMovesOverride: null,
      hintBox: null,
      hintState: null,
      coachCard: null,
      coachReport: null,
      flashNote: null,
      sheetSnap: 'closed', // 'closed' | 'half' | 'full'
      sheetTab: 'candidates',
      sideTab: 'candidates',
      menuOpen: false,
      handedLeft: false,
      wsConnected: false,
      connectionBanner: null,
      externalKatagoBanner: null,
      engineStatus: { state: 'STOPPED', idle_remaining_sec: null, external_katago_detected: false },
      fullReviewProgress: null,
      zoom: 1.0,
      ttsRate: 1.0,
      ttsSpeaking: false,
      swRegistered: false,
      fixtureActive: false,
    };

    this._toastTimer = null;
    this._sheetDrag = null;
    this._resizeObserver = null;

    this.SETTINGS_STORAGE_KEY = 'webgoban_user_settings_v1';
    const savedSettings = this._loadSavedSettings();

    this.input = new InputController(
      this.el.boardStage,
      this.canvas,
      {
        isPointEmpty: (x, y) => !this.state.board[y]?.[x],
        getCandidates: () => this.state.analysis.moves || [],
        onGhostMove: (info) => this._onGhostMove(info),
        onGhostClear: () => this._onGhostClear(),
        onForbiddenHover: (pt) => this.canvas.setDynamicState({ forbiddenPoint: pt }),
        onHoverCandidate: (cand) => this._onHoverCandidate(cand),
        onHoverEmpty: (pt) => this._onHoverEmpty(pt),
        onHoverClear: () => this._onHoverClear(),
        onDirectPlay: (gtp) => this.submitMove(gtp),
        onZoomChange: (zoom) => this._onZoomChange(zoom),
      },
      {
        inputMode: savedSettings.inputMode || 'auto',
        penGhostOnMobile: !!savedSettings.penGhostOnMobile,
        touchOffsetPx: savedSettings.touchOffsetPx ?? 52,
        reTapConfirm: savedSettings.reTapConfirm ?? true, // 初期値を①「再タップ確定」にする
        hapticsEnabled: savedSettings.hapticsEnabled ?? true,
      }
    );

    this._bindEvents();
    this._applySettingsToUi(savedSettings);
    this._setupResizeObserver();
    this._wirePlatformBridge();
    this.syncLayoutMode();
    this.renderAll();
  }

  _queryElements() {
    const byId = (id) => document.getElementById(id);
    return {
      app: byId('app'),
      topBar: byId('top-bar'),
      connDot: byId('conn-dot'),
      topMoveText: byId('top-move-text'),
      topWinrateFill: byId('top-winrate-fill'),
      topScoreText: byId('top-score-text'),
      btnSettings: byId('btn-settings'),

      boardColumn: byId('board-column'),
      boardStage: byId('board-stage'),
      staticCanvas: byId('goban-static'),
      dynamicCanvas: byId('goban-dynamic'),
      connectionBanner: byId('connection-banner'),
      connectionBannerText: byId('connection-banner-text'),
      externalKatagoBanner: byId('external-katago-banner'),
      externalKatagoBannerText: byId('external-katago-banner-text'),
      branchPill: byId('branch-pill'),
      branchPillText: byId('branch-pill-text'),
      btnReturnMain: byId('btn-return-main'),
      zoomPill: byId('zoom-pill'),
      btnZoomReset: byId('btn-zoom-reset'),

      miniInfoStrip: byId('mini-info-strip'),
      btnMiniSparkline: byId('btn-mini-sparkline'),
      miniSparklineWr: byId('mini-sparkline-wr'),
      miniSparklineSvg: byId('mini-sparkline-svg'),
      miniCandRow: byId('mini-cand-row'),
      miniCapturesText: byId('mini-captures-text'),
      miniFlashNote: byId('mini-flash-note'),

      actionBar: byId('action-bar'),
      actionBarNormal: byId('action-bar-normal'),
      actionNormalText: byId('action-normal-text'),
      actionReviewControls: byId('action-review-controls'),
      actionPlayControls: byId('action-play-controls'),
      btnHeatmapMobile: byId('btn-heatmap-mobile'),
      btnPlayPass: byId('btn-play-pass'),
      btnPlayUndo: byId('btn-play-undo'),
      btnPlayResign: byId('btn-play-resign'),
      actionBarHover: byId('action-bar-hover'),
      actionHoverText: byId('action-hover-text'),
      actionBarGhost: byId('action-bar-ghost'),
      ghostLabel: byId('ghost-label'),
      btnGhostCancel: byId('btn-ghost-cancel'),
      btnGhostConfirm: byId('btn-ghost-confirm'),

      bottomToolbar: byId('bottom-toolbar'),
      btnPrev: byId('btn-prev'),
      btnNext: byId('btn-next'),
      btnToggleAnalyze: byId('btn-toggle-analyze'),
      analyzeBtnIcon: byId('analyze-btn-icon'),
      analyzeBtnLabel: byId('analyze-btn-label'),
      btnOpenSheet: byId('btn-open-sheet'),
      btnMenu: byId('btn-menu'),

      sidePanel: byId('side-panel'),
      sideConnDot: byId('side-conn-dot'),
      sideMoveText: byId('side-move-text'),
      sideWinrateFill: byId('side-winrate-fill'),
      sideScoreText: byId('side-score-text'),
      btnSideMenu: byId('btn-side-menu'),
      sideGraphMeta: byId('side-graph-meta'),
      btnGraphModeSide: byId('btn-graph-mode-side'),
      btnHeatmapSide: byId('btn-heatmap-side'),
      evalGraphSvg: byId('eval-graph-svg'),
      sideTabs: byId('side-tabs'),
      sidePaneCandidates: byId('side-pane-candidates'),
      sidePaneCoach: byId('side-pane-coach'),
      sidePaneGame: byId('side-pane-game'),
      sideActionNormal: byId('side-action-normal'),
      sideActionText: byId('side-action-text'),
      sidePlayControls: byId('side-play-controls'),
      btnSidePass: byId('btn-side-pass'),
      btnSideUndo: byId('btn-side-undo'),
      btnSideResign: byId('btn-side-resign'),
      sideActionHover: byId('side-action-hover'),
      sideHoverText: byId('side-hover-text'),
      sideActionGhost: byId('side-action-ghost'),
      sideGhostLabel: byId('side-ghost-label'),
      btnSideGhostCancel: byId('btn-side-ghost-cancel'),
      btnSideGhostConfirm: byId('btn-side-ghost-confirm'),
      btnSideStart: byId('btn-side-start'),
      btnSideBack5: byId('btn-side-back5'),
      btnSidePrev: byId('btn-side-prev'),
      btnSideNext: byId('btn-side-next'),
      btnSideFwd5: byId('btn-side-fwd5'),
      btnSideEnd: byId('btn-side-end'),
      btnSideAnalyze: byId('btn-side-analyze'),

      bottomSheet: byId('bottom-sheet'),
      sheetHandle: byId('sheet-handle'),
      sheetTitle: byId('sheet-title'),
      btnSheetExpand: byId('btn-sheet-expand'),
      btnSheetClose: byId('btn-sheet-close'),
      sheetTabs: byId('sheet-tabs'),
      sheetPaneCandidates: byId('sheet-pane-candidates'),
      sheetPaneGraph: byId('sheet-pane-graph'),
      sheetPaneCoach: byId('sheet-pane-coach'),
      sheetPaneBranches: byId('sheet-pane-branches'),
      btnGraphModeSheet: byId('btn-graph-mode-sheet'),
      btnHeatmapSheet: byId('btn-heatmap-sheet'),
      sheetEvalGraphSvg: byId('sheet-eval-graph-svg'),

      menuModal: byId('menu-modal'),
      btnMenuClose: byId('btn-menu-close'),
      selBoardSize: byId('sel-board-size'),
      selGameMode: byId('sel-game-mode'),
      selHandicap: byId('sel-handicap'),
      inputKomi: byId('input-komi'),
      selAiLevel: byId('sel-ai-level'),
      selHumanColor: byId('sel-human-color'),
      btnNewGame: byId('btn-new-game'),
      inputSgfFile: byId('input-sgf-file'),
      inputSgfText: byId('input-sgf-text'),
      btnImportSgfText: byId('btn-import-sgf-text'),
      btnExportSgf: byId('btn-export-sgf'),
      btnCopySgf: byId('btn-copy-sgf'),
      selInputMode: byId('sel-input-mode'),
      selTouchOffset: byId('sel-touch-offset'),
      selCandLabel: byId('sel-cand-label'),
      chkPenGhostMobile: byId('chk-pen-ghost-mobile'),
      chkRetapConfirm: byId('chk-retap-confirm'),
      chkHaptics: byId('chk-haptics'),
      chkHandedLeft: byId('chk-handed-left'),
      chkKeepScreen: byId('chk-keep-screen'),
      engineStatusSummary: byId('engine-status-summary'),
      btnEngineWarmup: byId('btn-engine-warmup'),
      btnFullReview: byId('btn-full-review'),
      btnEngineStop: byId('btn-engine-stop'),

      toast: byId('toast'),
    };
  }

  getLayoutMode() {
    if (typeof window === 'undefined' || !window.matchMedia) return 'mobile-portrait';
    if (window.matchMedia('(min-width: 900px) and (orientation: landscape), (min-width: 1024px)').matches) {
      return 'tablet-landscape';
    }
    if (window.matchMedia('(min-width: 768px) and (orientation: portrait)').matches) {
      return 'tablet-portrait';
    }
    return 'mobile-portrait';
  }

  syncLayoutMode() {
    const mode = this.getLayoutMode();
    this.el.app.dataset.layout = mode;
    this.el.app.classList.toggle('handed-left', Boolean(this.state.handedLeft));
    this._resizeBoardFromStage();
  }

  _resizeBoardFromStage() {
    const rect = this.el.boardStage.getBoundingClientRect();
    if (rect.width > 0 && rect.height > 0) {
      this.canvas.resize(rect.width, rect.height);
      PlatformBridge.updateBoardExclusionZone(rect);
    }
  }

  _setupResizeObserver() {
    if (typeof ResizeObserver !== 'undefined') {
      this._resizeObserver = new ResizeObserver(() => {
        this.syncLayoutMode();
      });
      this._resizeObserver.observe(this.el.boardStage);
    }
    window.addEventListener('resize', () => this.syncLayoutMode());
    window.addEventListener('orientationchange', () => {
      setTimeout(() => this.syncLayoutMode(), 60);
    });
  }

  _wirePlatformBridge() {
    PlatformBridge.setSystemBarTheme('#1A1D21', false);

    // Multi-stage hardware back handler:
    // 1. menu modal -> 2. bottom sheet -> 3. zoom reset -> 4. ghost cancel -> 5. false
    PlatformBridge.registerBackHandler(() => {
      if (this.state.menuOpen) {
        this.setMenuOpen(false);
        return true;
      }
      if (this.state.sheetSnap !== 'closed') {
        this.setSheetSnap('closed');
        return true;
      }
      if (this.state.zoom > 1.01) {
        this.resetZoom();
        return true;
      }
      if (this.state.ghostMove) {
        this.cancelGhost();
        return true;
      }
      return false;
    });

    PlatformBridge.onIncomingPayload((payload) => {
      this._handleIncomingPayload(payload);
    });
  }

  async _handleIncomingPayload(payload) {
    if (!payload || typeof payload !== 'object') return;
    if (payload.type === 'sgf' && payload.sgf_text) {
      await this.importSgfText(payload.sgf_text);
      return;
    }
    if (payload.type === 'deeplink') {
      await this.handleDeepLink(payload);
    }
  }

  _bindEvents() {
    const { el } = this;

    // Ghost Confirm & Cancel (Mobile + Tablet)
    el.btnGhostCancel.addEventListener('click', () => this.cancelGhost());
    el.btnGhostConfirm.addEventListener('click', () => this.confirmGhost());
    el.btnSideGhostCancel.addEventListener('click', () => this.cancelGhost());
    el.btnSideGhostConfirm.addEventListener('click', () => this.confirmGhost());

    // Board Overlays
    el.btnReturnMain.addEventListener('click', () => this.returnToMainline());
    el.btnZoomReset.addEventListener('click', () => this.resetZoom());

    // Mobile Toolbar
    el.btnPrev.addEventListener('click', () => this.navigateRelative(-1));
    el.btnNext.addEventListener('click', () => this.navigateRelative(1));
    el.btnToggleAnalyze.addEventListener('click', () => this._onPrimaryAnalyzeOrHintClick());
    el.btnOpenSheet.addEventListener('click', () => {
      this.setSheetSnap(this.state.sheetSnap === 'closed' ? 'half' : 'closed');
    });
    el.btnMenu.addEventListener('click', () => this.setMenuOpen(true));
    el.btnSettings.addEventListener('click', () => this.setMenuOpen(true));

    // Mini Sparkline opens sheet to Graph tab
    el.btnMiniSparkline.addEventListener('click', () => {
      this.setSheetTab('graph');
      this.setSheetSnap('half');
    });

    // Play Mode Controls
    el.btnPlayPass.addEventListener('click', () => this.submitMove('pass'));
    el.btnPlayUndo.addEventListener('click', () => this.requestUndo());
    el.btnPlayResign.addEventListener('click', () => this.requestResign());
    el.btnSidePass.addEventListener('click', () => this.submitMove('pass'));
    el.btnSideUndo.addEventListener('click', () => this.requestUndo());
    el.btnSideResign.addEventListener('click', () => this.requestResign());

    // Heatmap & Graph Mode Toggles
    const toggleHeatmap = () => {
      this.state.showHeatmap = !this.state.showHeatmap;
      this.canvas.setDynamicState({ showHeatmap: this.state.showHeatmap });
      this._renderToggles();
    };
    el.btnHeatmapMobile.addEventListener('click', toggleHeatmap);
    el.btnHeatmapSide.addEventListener('click', toggleHeatmap);
    el.btnHeatmapSheet.addEventListener('click', toggleHeatmap);

    const toggleGraphMode = () => {
      this.state.graphMode = this.state.graphMode === 'winrate' ? 'score' : 'winrate';
      this._renderToggles();
      this._renderAllGraphs();
    };
    el.btnGraphModeSide.addEventListener('click', toggleGraphMode);
    el.btnGraphModeSheet.addEventListener('click', toggleGraphMode);

    // Tablet Navigation Footer
    el.btnSideMenu.addEventListener('click', () => this.setMenuOpen(true));
    el.btnSideStart.addEventListener('click', () => this.navigateToMove(0));
    el.btnSideBack5.addEventListener('click', () => this.navigateRelative(-5));
    el.btnSidePrev.addEventListener('click', () => this.navigateRelative(-1));
    el.btnSideNext.addEventListener('click', () => this.navigateRelative(1));
    el.btnSideFwd5.addEventListener('click', () => this.navigateRelative(5));
    el.btnSideEnd.addEventListener('click', () => this.navigateToMove(this.state.maxMoveNumber));
    el.btnSideAnalyze.addEventListener('click', () => this._onPrimaryAnalyzeOrHintClick());

    // Side Panel Tabs
    el.sideTabs.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-side-tab]');
      if (!btn) return;
      this.setSideTab(btn.dataset.sideTab);
    });

    // Bottom Sheet Tabs & Controls
    el.sheetTabs.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-sheet-tab]');
      if (!btn) return;
      this.setSheetTab(btn.dataset.sheetTab);
    });
    el.btnSheetExpand.addEventListener('click', () => {
      this.setSheetSnap(this.state.sheetSnap === 'full' ? 'half' : 'full');
    });
    el.btnSheetClose.addEventListener('click', () => this.setSheetSnap('closed'));
    this._bindSheetHandleDrag();

    // SVG Graph click & drag scrubbing
    this._bindGraphScrub(el.evalGraphSvg);
    this._bindGraphScrub(el.sheetEvalGraphSvg);

    // Menu Modal Controls
    el.btnMenuClose.addEventListener('click', () => this.setMenuOpen(false));
    el.menuModal.addEventListener('click', (e) => {
      if (e.target === el.menuModal) this.setMenuOpen(false);
    });

    el.selHandicap.addEventListener('change', () => {
      const h = parseInt(el.selHandicap.value, 10) || 0;
      el.inputKomi.value = h >= 2 ? '0.5' : '6.5';
    });

    el.btnNewGame.addEventListener('click', () => this._handleNewGameSubmit());
    el.btnImportSgfText.addEventListener('click', () => {
      const text = el.inputSgfText.value.trim();
      if (!text) {
        this.showToast('SGFテキストを入力してください');
        return;
      }
      this.importSgfText(text);
    });
    el.inputSgfFile.addEventListener('change', async (e) => {
      const file = e.target.files && e.target.files[0];
      if (!file) return;
      await this.importSgfFile(file);
      el.inputSgfFile.value = '';
    });
    el.btnExportSgf.addEventListener('click', () => this.exportSgf(false));
    el.btnCopySgf.addEventListener('click', () => this.exportSgf(true));

    // Settings Controls
    el.selInputMode.addEventListener('change', () => {
      const mode = el.selInputMode.value;
      if (mode === 'retap') {
        this.input.updateSettings({ inputMode: 'auto', reTapConfirm: true });
      } else if (mode === 'always_direct') {
        this.input.updateSettings({ inputMode: 'always_direct', reTapConfirm: false });
      } else if (mode === 'always_ghost') {
        this.input.updateSettings({ inputMode: 'always_ghost', reTapConfirm: false });
      } else {
        this.input.updateSettings({ inputMode: mode });
      }
      this._saveCurrentSettings();
    });
    el.selTouchOffset.addEventListener('change', () => {
      this.input.updateSettings({ touchOffsetPx: parseInt(el.selTouchOffset.value, 10) || 0 });
      this._saveCurrentSettings();
    });
    el.selCandLabel.addEventListener('change', () => {
      this.state.candidateLabelMode = el.selCandLabel.value;
      this.canvas.setDynamicState({ candidateLabelMode: this.state.candidateLabelMode });
      this._saveCurrentSettings();
    });
    el.chkPenGhostMobile.addEventListener('change', () => {
      this.input.updateSettings({ penGhostOnMobile: el.chkPenGhostMobile.checked });
      this._saveCurrentSettings();
    });
    el.chkRetapConfirm.addEventListener('change', () => {
      this.input.updateSettings({ reTapConfirm: el.chkRetapConfirm.checked });
      this._saveCurrentSettings();
    });
    el.chkHaptics.addEventListener('change', () => {
      this.input.updateSettings({ hapticsEnabled: el.chkHaptics.checked });
      this._saveCurrentSettings();
    });
    el.chkHandedLeft.addEventListener('change', () => {
      this.state.handedLeft = el.chkHandedLeft.checked;
      this.el.app.classList.toggle('handed-left', this.state.handedLeft);
      this._resizeBoardFromStage();
      this._saveCurrentSettings();
    });
    el.chkKeepScreen.addEventListener('change', () => {
      PlatformBridge.setKeepScreenOn(el.chkKeepScreen.checked);
      this._saveCurrentSettings();
    });

    // Engine Controls
    el.btnEngineWarmup.addEventListener('click', async () => {
      const res = await this.ws.engineWarmup();
      if (res.ok) {
        this.showToast('KataGo ウォームアップを開始しました');
        await this.refreshEngineStatus();
      } else {
        this.showToast(`起動要求エラー: ${res.error}`);
      }
    });
    el.btnEngineStop.addEventListener('click', async () => {
      const res = await this.ws.engineStop();
      if (res.ok) {
        this.showToast('KataGo を停止しました');
        await this.refreshEngineStatus();
      } else {
        this.showToast(`停止エラー: ${res.error}`);
      }
    });
    el.btnFullReview.addEventListener('click', () => {
      if (this.ws.send('request_full_review', { max_visits: 150 }, this.state.stateVersion)) {
        this.showToast('1局一括検討を開始しました');
        this.setMenuOpen(false);
      } else {
        this.showToast('サーバー未接続のため一括検討できません');
      }
    });
  }

  _loadSavedSettings() {
    try {
      const raw = window.localStorage.getItem(this.SETTINGS_STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch {
      return {};
    }
  }

  _saveCurrentSettings() {
    try {
      const s = {
        inputMode: this.el.selInputMode.value,
        touchOffsetPx: parseInt(this.el.selTouchOffset.value, 10) || 0,
        candidateLabelMode: this.state.candidateLabelMode,
        penGhostOnMobile: this.el.chkPenGhostMobile.checked,
        reTapConfirm: this.input.settings.reTapConfirm,
        hapticsEnabled: this.el.chkHaptics.checked,
        handedLeft: this.state.handedLeft,
        keepScreenOn: this.el.chkKeepScreen.checked,
      };
      window.localStorage.setItem(this.SETTINGS_STORAGE_KEY, JSON.stringify(s));
    } catch {}
  }

  _applySettingsToUi(s) {
    if (!s) return;
    if (s.inputMode && this.el.selInputMode) {
      this.el.selInputMode.value = s.inputMode;
    }
    if (s.touchOffsetPx !== undefined && this.el.selTouchOffset) {
      this.el.selTouchOffset.value = String(s.touchOffsetPx);
    }
    if (s.candidateLabelMode && this.el.selCandLabel) {
      this.el.selCandLabel.value = s.candidateLabelMode;
      this.state.candidateLabelMode = s.candidateLabelMode;
      this.canvas.setDynamicState({ candidateLabelMode: s.candidateLabelMode });
    }
    if (s.penGhostOnMobile !== undefined && this.el.chkPenGhostMobile) {
      this.el.chkPenGhostMobile.checked = !!s.penGhostOnMobile;
    }
    if (s.reTapConfirm !== undefined && this.el.chkRetapConfirm) {
      this.el.chkRetapConfirm.checked = !!s.reTapConfirm;
    }
    if (s.hapticsEnabled !== undefined && this.el.chkHaptics) {
      this.el.chkHaptics.checked = !!s.hapticsEnabled;
    }
    if (s.handedLeft !== undefined && this.el.chkHandedLeft) {
      this.el.chkHandedLeft.checked = !!s.handedLeft;
      this.state.handedLeft = !!s.handedLeft;
      this.el.app.classList.toggle('handed-left', this.state.handedLeft);
    }
    if (s.keepScreenOn !== undefined && this.el.chkKeepScreen) {
      this.el.chkKeepScreen.checked = !!s.keepScreenOn;
      PlatformBridge.setKeepScreenOn(this.el.chkKeepScreen.checked);
    }
  }

  _bindSheetHandleDrag() {
    const handle = this.el.sheetHandle;
    handle.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button')) return;
      this._sheetDrag = {
        pointerId: e.pointerId,
        startY: e.clientY,
        startSnap: this.state.sheetSnap,
      };
      try {
        handle.setPointerCapture(e.pointerId);
      } catch {
        // Ignore synthetic event errors
      }
    });
    handle.addEventListener('pointerup', (e) => {
      if (!this._sheetDrag || this._sheetDrag.pointerId !== e.pointerId) return;
      const dy = e.clientY - this._sheetDrag.startY;
      const startSnap = this._sheetDrag.startSnap;
      this._sheetDrag = null;
      if (dy < -42) {
        this.setSheetSnap('full');
      } else if (dy > 48) {
        this.setSheetSnap(startSnap === 'full' ? 'half' : 'closed');
      }
    });
    handle.addEventListener('pointercancel', () => {
      this._sheetDrag = null;
    });
  }

  _bindGraphScrub(svgEl) {
    let scrubbing = false;
    const pickMove = (clientX) => {
      const hist = this.state.evalHistory;
      if (!hist || hist.length === 0) return;
      const rect = svgEl.getBoundingClientRect();
      if (rect.width <= 0) return;
      const padLeft = 28;
      const padRight = 10;
      const innerW = Math.max(10, rect.width - padLeft - padRight);
      const ratio = Math.max(0, Math.min(1, (clientX - rect.left - padLeft) / innerW));
      const idx = Math.round(ratio * (hist.length - 1));
      const point = hist[idx];
      if (point) {
        if (point.node_id) {
          this.navigateToNode(point.node_id);
        } else {
          this.navigateToMove(getGraphPointMoveNumber(point, idx));
        }
      }
    };
    svgEl.addEventListener('pointerdown', (e) => {
      scrubbing = true;
      pickMove(e.clientX);
    });
    svgEl.addEventListener('pointermove', (e) => {
      if (scrubbing) pickMove(e.clientX);
    });
    window.addEventListener('pointerup', () => {
      scrubbing = false;
    });
  }

  // --- Input Callbacks ---

  _onGhostMove(info) {
    this.state.ghostMove = {
      x: info.x,
      y: info.y,
      gtp: info.gtp,
      color: this.state.nextPlayer,
      dragging: Boolean(info.dragging),
    };
    this.canvas.setDynamicState({ ghostMove: this.state.ghostMove });
    this._renderActionBars();
  }

  _onGhostClear() {
    this.state.ghostMove = null;
    this.canvas.setDynamicState({ ghostMove: null, forbiddenPoint: null });
    this._renderActionBars();
  }

  cancelGhost() {
    this.input.clearGhost();
    this._onGhostClear();
  }

  confirmGhost() {
    if (!this.state.ghostMove || !this.state.ghostMove.gtp) return;
    const move = this.state.ghostMove.gtp;
    this.input.clearGhost();
    PlatformBridge.haptic('confirm');
    this.submitMove(move);
  }

  _onHoverCandidate(cand) {
    this.state.hoveredCandidate = cand || null;
    this.state.hoveredEmpty = null;
    this._syncPvAndHoverCanvas();
    this._renderActionBars();
  }

  _onHoverEmpty(pt) {
    this.state.hoveredEmpty = pt || null;
    this._syncPvAndHoverCanvas();
    this._renderActionBars();
  }

  _onHoverClear() {
    this.state.hoveredCandidate = null;
    this.state.hoveredEmpty = null;
    this._syncPvAndHoverCanvas();
    this._renderActionBars();
  }

  _onZoomChange(zoom) {
    this.state.zoom = zoom;
    this._renderBoardOverlays();
  }

  resetZoom() {
    this.canvas.resetZoom();
    this.state.zoom = 1.0;
    this._renderBoardOverlays();
  }

  _syncPvAndHoverCanvas() {
    let pvSequence = null;
    if (this.state.hoveredCandidate && Array.isArray(this.state.hoveredCandidate.pv)) {
      pvSequence = {
        moves: this.state.hoveredCandidate.pv,
        startPlayer: this.state.nextPlayer,
        maxMoves: this.state.pvMaxMovesOverride ?? undefined,
      };
    } else if (this.state.pinnedPvMove) {
      const cand = (this.state.analysis.moves || []).find(
        (m) => m.move === String(this.state.pinnedPvMove).toUpperCase()
      );
      if (cand && Array.isArray(cand.pv) && cand.pv.length > 0) {
        pvSequence = {
          moves: cand.pv,
          startPlayer: this.state.nextPlayer,
          maxMoves: this.state.pvMaxMovesOverride ?? undefined,
        };
      }
    }

    this.canvas.setDynamicState({
      pvSequence,
      hoverEmpty: this.state.hoveredEmpty,
    });
  }

  pinCandidatePv(moveGtp) {
    const upper = String(moveGtp || '').toUpperCase();
    if (!upper) return;
    if (this.state.pinnedPvMove === upper) {
      this.state.pinnedPvMove = null;
    } else {
      this.state.pinnedPvMove = upper;
      // If mobile bottom sheet is in full state, collapse to half so user sees PV on board
      if (this.state.sheetSnap === 'full') {
        this.setSheetSnap('half');
      }
    }
    this._syncPvAndHoverCanvas();
    this._renderCandidates();
    this._renderMiniInfoStrip();
  }

  // --- Sheet & Modal Navigation ---

  setSheetSnap(snap) {
    const valid = snap === 'half' || snap === 'full' ? snap : 'closed';
    const wasClosed = this.state.sheetSnap === 'closed';
    this.state.sheetSnap = valid;
    this.el.bottomSheet.dataset.snap = valid;
    this.el.btnSheetExpand.textContent = valid === 'full' ? '⤡' : '⤢';
    if (wasClosed && valid !== 'closed') {
      PlatformBridge.pushUiOverlayHistory('sheet');
    }
    if (valid !== 'closed') {
      this._renderSheetPanes();
    }
  }

  setSheetTab(tab) {
    this.state.sheetTab = tab;
    const buttons = this.el.sheetTabs.querySelectorAll('[data-sheet-tab]');
    buttons.forEach((btn) => {
      const active = btn.dataset.sheetTab === tab;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    this.el.sheetPaneCandidates.hidden = tab !== 'candidates';
    this.el.sheetPaneGraph.hidden = tab !== 'graph';
    this.el.sheetPaneCoach.hidden = tab !== 'coach';
    this.el.sheetPaneBranches.hidden = tab !== 'branches';
    this._renderSheetPanes();
  }

  setSideTab(tab) {
    this.state.sideTab = tab;
    const buttons = this.el.sideTabs.querySelectorAll('[data-side-tab]');
    buttons.forEach((btn) => {
      const active = btn.dataset.sideTab === tab;
      btn.classList.toggle('is-active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    this.el.sidePaneCandidates.hidden = tab !== 'candidates';
    this.el.sidePaneCoach.hidden = tab !== 'coach';
    this.el.sidePaneGame.hidden = tab !== 'game';
    this._renderSidePanes();
  }

  setMenuOpen(open) {
    this.state.menuOpen = Boolean(open);
    this.el.menuModal.hidden = !this.state.menuOpen;
    if (this.state.menuOpen) {
      PlatformBridge.pushUiOverlayHistory('menu');
      this.refreshEngineStatus();
    }
  }

  // --- Game Actions & WS Commands ---

  submitMove(moveGtp) {
    const move = String(moveGtp || '').trim();
    if (!move) return;
    this.state.fixtureActive = false;
    const upper = move.toLowerCase() === 'pass' ? 'pass' : move.toUpperCase();

    // Optimistic tentative stone on canvas while awaiting server move_accepted
    if (upper !== 'pass') {
      const pt = gtpToXy(upper, this.state.boardSize);
      if (pt && !this.state.board[pt.y]?.[pt.x]) {
        this.state.tentativeStone = { x: pt.x, y: pt.y, color: this.state.nextPlayer };
        this.canvas.setBoardState({
          boardSize: this.state.boardSize,
          board: this.state.board,
          lastMove: this.state.lastMove,
          nextPlayer: this.state.nextPlayer,
          tentativeStone: this.state.tentativeStone,
        });
      }
    }

    this.state.pinnedPvMove = null;
    this.state.hoveredCandidate = null;
    this.state.hintBox = null;
    this.canvas.setDynamicState({ pvSequence: null, hintBox: null });

    const sent = this.ws.send(
      'play_move',
      {
        parent_node_id: this.state.currentNodeId,
        move: upper,
        expected_version: this.state.stateVersion,
      },
      this.state.stateVersion
    );
    if (!sent) {
      this.state.tentativeStone = null;
      this.canvas.setBoardState({
        boardSize: this.state.boardSize,
        board: this.state.board,
        lastMove: this.state.lastMove,
        nextPlayer: this.state.nextPlayer,
        tentativeStone: null,
      });
      this.showToast('サーバー未接続のため着手できません');
    }
  }

  navigateRelative(delta) {
    if (delta === -1 || delta === 1) {
      const curNode = (this.state.nodes || []).find((n) => n.node_id === this.state.currentNodeId);
      if (curNode) {
        if (delta === -1 && curNode.parent_id) {
          this.navigateToNode(curNode.parent_id);
          return;
        }
        if (delta === 1 && Array.isArray(curNode.children_ids) && curNode.children_ids.length > 0) {
          // Prefer mainline child if available
          const mainlineSet = new Set(this.state.mainlineIds || []);
          const nextId =
            curNode.children_ids.find((cid) => mainlineSet.has(cid)) || curNode.children_ids[0];
          this.navigateToNode(nextId);
          return;
        }
      }
    }
    const maxMv = Math.max(
      this.state.maxMoveNumber,
      this.state.mainlineIds.length > 0 ? this.state.mainlineIds.length - 1 : 0
    );
    const targetMove = Math.max(0, Math.min(maxMv, this.state.moveNumber + delta));
    this.navigateToMove(targetMove, delta);
  }

  navigateToMove(targetMove, delta = null) {
    this.state.fixtureActive = false;
    this.cancelGhost();
    this.state.pinnedPvMove = null;
    this.canvas.setDynamicState({ pvSequence: null });

    const maxMv = Math.max(
      this.state.maxMoveNumber,
      this.state.mainlineIds.length > 0 ? this.state.mainlineIds.length - 1 : 0
    );
    const clampedMove = Math.max(0, Math.min(maxMv, Number(targetMove) || 0));
    const payload = { move_number: clampedMove };
    if (delta !== null) payload.delta = delta;

    if (Array.isArray(this.state.mainlineIds) && this.state.mainlineIds[clampedMove]) {
      payload.node_id = this.state.mainlineIds[clampedMove];
    } else if (Array.isArray(this.state.nodes) && this.state.nodes.length > 0) {
      const found = this.state.nodes.find((n) => n.move_number === clampedMove);
      if (found && found.node_id) {
        payload.node_id = found.node_id;
      }
    }

    this.ws.send('navigate', payload, this.state.stateVersion);
  }

  navigateToNode(nodeId) {
    if (!nodeId) return;
    this.state.fixtureActive = false;
    this.cancelGhost();
    this.state.pinnedPvMove = null;
    this.canvas.setDynamicState({ pvSequence: null });
    this.ws.send('navigate', { node_id: nodeId }, this.state.stateVersion);
  }

  returnToMainline() {
    if (this.state.mainlineNodeId) {
      this.navigateToNode(this.state.mainlineNodeId);
    } else if (this.state.mainlineIds && this.state.mainlineIds.length > 0) {
      this.navigateToNode(this.state.mainlineIds[this.state.mainlineIds.length - 1]);
    }
  }

  requestUndo() {
    this.cancelGhost();
    this.ws.send('undo', { expected_version: this.state.stateVersion }, this.state.stateVersion);
  }

  requestResign() {
    this.cancelGhost();
    this.ws.send(
      'resign',
      { color: this.state.nextPlayer, expected_version: this.state.stateVersion },
      this.state.stateVersion
    );
  }

  _onPrimaryAnalyzeOrHintClick() {
    if (this.state.mode === 'play') {
      // Progressive hint toggle or info
      this.showToast('💡 対局ヒント機能は Phase 2 Gemini コーチ連携で有効化されます');
      return;
    }
    this.state.analysisEnabled = !this.state.analysisEnabled;
    this.canvas.setDynamicState({ showCandidates: this.state.analysisEnabled });
    if (this.state.analysisEnabled) {
      this.ws.send(
        'request_analysis',
        { node_id: this.state.currentNodeId, include_ownership: true },
        this.state.stateVersion
      );
    } else {
      this.state.pinnedPvMove = null;
      this.canvas.setDynamicState({ pvSequence: null });
      this.ws.send('cancel_analysis', { scope: 'interactive' }, this.state.stateVersion);
    }
    this._renderToggles();
  }

  async _handleNewGameSubmit() {
    const boardSize = parseInt(this.el.selBoardSize.value, 10) || 19;
    const mode = this.el.selGameMode.value || 'review';
    const handicap = parseInt(this.el.selHandicap.value, 10) || 0;
    const komi = parseFloat(this.el.inputKomi.value);
    const aiLevel = this.el.selAiLevel.value || '5k';
    const humanColor = this.el.selHumanColor.value || 'B';

    const res = await this.ws.createGame({
      board_size: boardSize,
      mode,
      handicap,
      komi: Number.isFinite(komi) ? komi : handicap >= 2 ? 0.5 : 6.5,
      ai_level: aiLevel,
      human_color: humanColor,
    });
    if (!res.ok || !res.data) {
      this.showToast(`新規作成エラー: ${res.error || '失敗'}`);
      return;
    }
    const newGameId = res.data.game_id || res.data.id;
    this.setMenuOpen(false);
    if (newGameId) {
      this.openGame(newGameId, res.data);
      this.showToast(`${boardSize}路盤 (${mode === 'play' ? 'AI対局' : '検討'}) を開始しました`);
    }
  }

  async importSgfText(sgfText) {
    this.state.fixtureActive = false;
    if (!this.state.gameId) {
      const created = await this.ws.createGame({ board_size: 19, mode: 'review' });
      if (created.ok && created.data) {
        this.state.gameId = created.data.game_id || created.data.id;
      }
    }
    if (!this.state.gameId) {
      this.showToast('SGF読込先セッションを作成できませんでした');
      return;
    }
    const res = await this.ws.importSgfText(this.state.gameId, sgfText);
    if (res.ok) {
      if (res.data && (res.data.board || res.data.stones)) {
        this.applyStateSync(res.data);
      } else {
        this.ws.send('sync_request', { last_seen_version: 0 });
      }
      this.setMenuOpen(false);
      this.showToast('SGF棋譜を読み込みました');
    } else {
      this.showToast(`SGF読込エラー: ${res.error || '形式エラー'}`);
    }
  }

  async importSgfFile(file) {
    if (!this.state.gameId) {
      const created = await this.ws.createGame({ board_size: 19, mode: 'review' });
      if (created.ok && created.data) {
        this.state.gameId = created.data.game_id || created.data.id;
      }
    }
    if (!this.state.gameId) return;
    const res = await this.ws.importSgfFile(this.state.gameId, file);
    if (res.ok) {
      if (res.data && (res.data.board || res.data.stones)) {
        this.applyStateSync(res.data);
      } else {
        this.ws.send('sync_request', { last_seen_version: 0 });
      }
      this.setMenuOpen(false);
      this.showToast(`${file.name} を読み込みました`);
    } else {
      this.showToast(`SGFファイル読込エラー: ${res.error || '失敗'}`);
    }
  }

  async exportSgf(copyOnly = false) {
    if (!this.state.gameId) return;
    const res = await this.ws.exportSgfJson(this.state.gameId);
    if (!res.ok || !res.data) {
      this.showToast(`SGF出力エラー: ${res.error || '失敗'}`);
      return;
    }
    const sgfText = typeof res.data === 'string' ? res.data : res.data.sgf_text || '';
    const filename = (typeof res.data === 'object' && res.data.filename) || `web-goban-${this.state.gameId}.sgf`;
    if (copyOnly) {
      const copied = await PlatformBridge.copyText(sgfText);
      this.showToast(copied ? 'SGFをクリップボードへコピーしました' : 'コピーに失敗しました');
    } else {
      await PlatformBridge.shareOrDownloadFile({
        filename,
        content: sgfText,
        mimeType: 'application/x-go-sgf',
      });
      this.showToast('SGFを書き出しました');
    }
  }

  async refreshEngineStatus() {
    const res = await this.ws.engineStatus();
    if (res.ok && res.data) {
      this.applyEngineStatus(res.data);
    }
  }

  openGame(gameId, initialData = null) {
    this.state.gameId = gameId;
    this.state.fixtureActive = false;
    if (initialData && (initialData.board || initialData.stones || initialData.board_size)) {
      this.applyStateSync(initialData);
    }
    this.ws.connect(gameId, this.state.stateVersion);
  }

  async handleDeepLink({ game, sgf, move, mode } = {}) {
    if (game) {
      const res = await this.ws.getGame(game);
      if (res.ok && res.data) {
        this.openGame(game, res.data);
        if (Number.isFinite(Number(move))) {
          setTimeout(() => this.navigateToMove(Number(move)), 150);
        }
        return true;
      }
    }
    if (sgf) {
      const res = await this.ws.getSgf(sgf);
      if (res.ok && res.data && res.data.sgf_text) {
        const created = await this.ws.createGame({ mode: mode || 'review' });
        if (created.ok && created.data) {
          const gid = created.data.game_id || created.data.id;
          this.openGame(gid, created.data);
          await this.importSgfText(res.data.sgf_text);
          if (Number.isFinite(Number(move))) {
            setTimeout(() => this.navigateToMove(Number(move)), 150);
          }
          return true;
        }
      }
    }
    return false;
  }

  // --- Server Event Handlers ---

  handleConnectionChange({ connected, reconnecting }) {
    if (this.state.fixtureActive) return;
    this.state.wsConnected = Boolean(connected);
    if (connected) {
      this.state.connectionBanner = null;
    } else if (reconnecting) {
      this.state.connectionBanner = '⚠️ サーバーへ再接続中…';
    }
    this._renderStatusHeaders();
    this._renderBoardOverlays();
  }

  handleWsEvent(msg) {
    if (!msg || typeof msg !== 'object') return;
    if (this.state.fixtureActive) return;

    const payload = msg.payload && typeof msg.payload === 'object' ? msg.payload : msg;
    if (typeof msg.state_version === 'number') {
      this.state.stateVersion = msg.state_version;
    }

    switch (msg.type) {
      case 'state_sync':
        this.applyStateSync(payload);
        break;
      case 'move_accepted': {
        this.state.tentativeStone = null;
        const fromSelfOrAi =
          !payload.actor_client_id ||
          payload.actor_client_id === this.ws.clientId ||
          payload.actor_client_id === 'ai';
        if (fromSelfOrAi || this.state.followingLatest) {
          this.applyStateSync(payload);
        } else {
          // Non-following terminal: keep local viewed board & move untouched, only update tree metadata
          if (payload.latest_node_id !== undefined) this.state.latestNodeId = payload.latest_node_id;
          if (Array.isArray(payload.mainline_ids)) {
            this.state.mainlineIds = payload.mainline_ids;
            this.state.maxMoveNumber = Math.max(0, payload.mainline_ids.length - 1);
          }
          if (payload.node && payload.node.node_id) {
            const existsIdx = this.state.nodes.findIndex((n) => n.node_id === payload.node.node_id);
            if (existsIdx >= 0) this.state.nodes[existsIdx] = payload.node;
            else this.state.nodes.push(payload.node);
            if (payload.parent_node_id) {
              const parent = this.state.nodes.find((n) => n.node_id === payload.parent_node_id);
              if (parent && Array.isArray(parent.children_ids) && !parent.children_ids.includes(payload.node.node_id)) {
                parent.children_ids.push(payload.node.node_id);
              }
            }
          }
          if (Array.isArray(payload.graph_points)) {
            this.state.evalHistory = payload.graph_points;
            this._renderAllGraphs();
          }
          this._renderBranchesAndGame();
        }
        if (
          this.state.mode === 'play' &&
          !this.state.isGameOver &&
          payload.actor_client_id === this.ws.clientId &&
          this.state.nextPlayer !== this.state.humanColor
        ) {
          this.ws.send(
            'request_ai_move',
            {
              parent_node_id: this.state.currentNodeId,
              ai_level: this.state.aiLevel,
              expected_version: this.state.stateVersion,
            },
            this.state.stateVersion
          );
        }
        break;
      }
      case 'ai_move':
        if (payload.resigned) {
          this.showToast(`AI が投了しました (${payload.game_result || ''})`);
        }
        break;
      case 'move_rejected':
        this.state.tentativeStone = null;
        this.canvas.setBoardState({
          boardSize: this.state.boardSize,
          board: this.state.board,
          lastMove: this.state.lastMove,
          nextPlayer: this.state.nextPlayer,
          tentativeStone: null,
        });
        PlatformBridge.haptic('error');
        this.showToast(payload.message || payload.reason || `着手できません (${payload.code || 'ILLEGAL'})`);
        if (payload.code === 'VERSION_CONFLICT') {
          this.ws.send('sync_request', { last_seen_version: this.state.stateVersion });
        }
        break;
      case 'analysis_update':
        this.applyAnalysisUpdate(payload);
        break;
      case 'full_review_progress':
        this.state.fullReviewProgress = payload;
        if (Array.isArray(payload.graph_points || payload.eval_history)) {
          this.state.evalHistory = payload.graph_points || payload.eval_history;
          this._renderAllGraphs();
        }
        if (payload.status === 'completed') {
          this.showToast('1局一括検討が完了しました');
        }
        break;
      case 'engine_status':
        this.applyEngineStatus(payload);
        break;
      case 'error':
        this.showToast(payload.message || '通信エラーが発生しました');
        break;
      default:
        break;
    }
  }

  applyStateSync(payload) {
    if (!payload || typeof payload !== 'object') return;
    const boardObj =
      payload.board && typeof payload.board === 'object' && !Array.isArray(payload.board)
        ? payload.board
        : null;

    if (payload.game_id) this.state.gameId = payload.game_id;
    if (typeof payload.state_version === 'number') this.state.stateVersion = payload.state_version;
    if (payload.komi !== undefined) this.state.komi = Number(payload.komi);
    else if (boardObj && boardObj.komi !== undefined) this.state.komi = Number(boardObj.komi);
    if (payload.handicap !== undefined) this.state.handicap = Number(payload.handicap);
    if (payload.mode) this.state.mode = payload.mode;
    if (payload.ai_level) this.state.aiLevel = payload.ai_level;
    if (payload.player_color || payload.human_color) {
      this.state.humanColor = payload.player_color || payload.human_color;
    }

    if (payload.board || payload.stones || payload.board_size) {
      const { size, board } = normalizeBoardFromPayload(payload, this.state.boardSize);
      this.state.boardSize = size;
      this.state.board = board;
    }

    if (payload.current_node_id !== undefined) this.state.currentNodeId = payload.current_node_id;
    else if (payload.node_id !== undefined) this.state.currentNodeId = payload.node_id;
    if (payload.latest_node_id !== undefined) this.state.latestNodeId = payload.latest_node_id;
    if (payload.following_latest !== undefined) {
      this.state.followingLatest = Boolean(payload.following_latest);
    } else if (this.state.currentNodeId && this.state.latestNodeId) {
      this.state.followingLatest = this.state.currentNodeId === this.state.latestNodeId;
    }
    if (payload.move_number !== undefined) this.state.moveNumber = Number(payload.move_number);

    if (Array.isArray(payload.mainline_ids)) {
      this.state.mainlineIds = payload.mainline_ids;
      this.state.maxMoveNumber = Math.max(0, payload.mainline_ids.length - 1);
    } else if (payload.total_mainline_moves !== undefined) {
      this.state.maxMoveNumber = Number(payload.total_mainline_moves);
    } else if (payload.max_move_number !== undefined) {
      this.state.maxMoveNumber = Number(payload.max_move_number);
    } else {
      this.state.maxMoveNumber = Math.max(this.state.maxMoveNumber, this.state.moveNumber);
    }

    const nextP = payload.next_player ?? boardObj?.next_player;
    if (nextP) this.state.nextPlayer = nextP;

    // Normalize last_move (supports null, GTP string, or { color, move } object)
    const rawLastMove =
      payload.last_move !== undefined
        ? payload.last_move
        : boardObj && boardObj.last_move !== undefined
          ? boardObj.last_move
          : payload.move !== undefined
            ? payload.move
            : undefined;
    if (rawLastMove !== undefined) {
      if (rawLastMove && typeof rawLastMove === 'object') {
        this.state.lastMove = rawLastMove.move || null;
      } else {
        this.state.lastMove = rawLastMove || null;
      }
    }

    const rawCaptures = payload.captures ?? boardObj?.captures;
    if (rawCaptures) {
      this.state.captures = {
        B: Number(rawCaptures.B ?? rawCaptures.black ?? 0),
        W: Number(rawCaptures.W ?? rawCaptures.white ?? 0),
      };
    }

    if (boardObj && boardObj.is_game_over !== undefined) {
      this.state.isGameOver = Boolean(boardObj.is_game_over);
      this.state.gameResult = boardObj.game_result || null;
    }

    if (Array.isArray(payload.nodes)) {
      this.state.nodes = payload.nodes;
    } else if (payload.node && payload.node.node_id) {
      // Incremental node insertion on move_accepted
      const existsIdx = this.state.nodes.findIndex((n) => n.node_id === payload.node.node_id);
      if (existsIdx >= 0) this.state.nodes[existsIdx] = payload.node;
      else this.state.nodes.push(payload.node);
      if (payload.parent_node_id) {
        const parent = this.state.nodes.find((n) => n.node_id === payload.parent_node_id);
        if (parent && Array.isArray(parent.children_ids) && !parent.children_ids.includes(payload.node.node_id)) {
          parent.children_ids.push(payload.node.node_id);
        }
      }
    }

    // Derive child variations for current node
    const curNode = (this.state.nodes || []).find((n) => n.node_id === this.state.currentNodeId);
    if (curNode && Array.isArray(curNode.children_ids) && curNode.children_ids.length > 0) {
      const nodeMap = new Map(this.state.nodes.map((n) => [n.node_id, n]));
      this.state.branches = curNode.children_ids
        .map((cid) => nodeMap.get(cid))
        .filter(Boolean)
        .map((child, idx) => ({
          node_id: child.node_id,
          move: child.move || 'pass',
          label: `${idx === 0 ? '本譜' : `変化${idx}`}: ${child.color === 'W' ? '白' : '黒'} ${child.move || 'pass'}`,
        }));
    } else if (Array.isArray(payload.branches)) {
      this.state.branches = payload.branches;
    } else {
      this.state.branches = [];
    }

    // Branch info from backend GameTree.get_branch_info()
    if (payload.branch_info && typeof payload.branch_info === 'object') {
      const bi = payload.branch_info;
      this.state.isOnMainline = !Boolean(bi.is_branch);
      this.state.branchDepth = Number(bi.branch_depth ?? 0);
      this.state.mainlineNodeId = bi.divergence_node_id || null;
    } else {
      if (payload.is_on_mainline !== undefined) this.state.isOnMainline = Boolean(payload.is_on_mainline);
      if (payload.branch_depth !== undefined) this.state.branchDepth = Number(payload.branch_depth);
      if (payload.mainline_node_id !== undefined) this.state.mainlineNodeId = payload.mainline_node_id;
    }

    if (payload.analysis !== undefined) {
      this.state.analysis = normalizeAnalysis(payload.analysis, this.state.nextPlayer);
    }
    if (Array.isArray(payload.eval_history || payload.graph_points)) {
      this.state.evalHistory = payload.eval_history || payload.graph_points;
    }
    if (payload.engine_status) {
      this.applyEngineStatus(payload.engine_status);
    }

    this.state.tentativeStone = null;
    this.canvas.setBoardState({
      boardSize: this.state.boardSize,
      board: this.state.board,
      lastMove: this.state.lastMove,
      nextPlayer: this.state.nextPlayer,
      tentativeStone: null,
    });
    this.canvas.setDynamicState({
      candidates: this.state.analysis.moves,
      ownership: this.state.analysis.ownership,
      showCandidates: this.state.analysisEnabled && this.state.mode !== 'play',
      showHeatmap: this.state.showHeatmap,
      nextPlayer: this.state.nextPlayer,
    });

    this.renderAll();
  }

  applyAnalysisUpdate(payload) {
    if (!payload) return;
    if (payload.node_id && this.state.currentNodeId && payload.node_id !== this.state.currentNodeId) {
      return;
    }
    this.state.analysis = normalizeAnalysis(payload, this.state.nextPlayer);
    this.canvas.setDynamicState({
      candidates: this.state.analysis.moves,
      ownership: this.state.analysis.ownership,
      showCandidates: this.state.analysisEnabled && this.state.mode !== 'play',
      nextPlayer: this.state.nextPlayer,
    });

    if (Array.isArray(payload.graph_points) && payload.graph_points.length > 0) {
      this.state.evalHistory = payload.graph_points;
    } else if (this.state.analysis.root) {
      const m = this.state.moveNumber;
      const idx = this.state.evalHistory.findIndex((p, i) => getGraphPointMoveNumber(p, i) === m);
      const entry = {
        move_number: m,
        node_id: this.state.currentNodeId,
        winrate_black: this.state.analysis.root.winrate_black,
        score_lead_black: this.state.analysis.root.score_lead_black,
        badge: payload.badge || (idx >= 0 ? this.state.evalHistory[idx].badge : null),
      };
      if (idx >= 0) this.state.evalHistory[idx] = entry;
      else {
        this.state.evalHistory.push(entry);
        this.state.evalHistory.sort((a, b) => getGraphPointMoveNumber(a) - getGraphPointMoveNumber(b));
      }
    }

    this._syncPvAndHoverCanvas();
    this._renderStatusHeaders();
    this._renderMiniInfoStrip();
    this._renderActionBars();
    this._renderCandidates();
    this._renderAllGraphs();
  }

  applyEngineStatus(status) {
    if (!status || typeof status !== 'object') return;
    this.state.engineStatus = status;
    const extDetected = Boolean(status.external_katago_detected);
    if (extDetected) {
      const rss = status.external_katago_rss_mb ? ` (${Math.round(status.external_katago_rss_mb)}MB)` : '';
      this.state.externalKatagoBanner = `外部 KataGo (KaTrain等)${rss} を検知中 — 自動起動を抑制中`;
    } else {
      this.state.externalKatagoBanner = null;
    }
    const idleText =
      typeof status.idle_remaining_sec === 'number'
        ? ` / 自動停止まで ${Math.ceil(status.idle_remaining_sec / 60)}分`
        : '';
    this.el.engineStatusSummary.textContent = `状態: ${status.state || 'UNKNOWN'}${idleText}`;
    this._renderBoardOverlays();
  }

  // --- Deterministic Visual QA Fixture Loader ---

  applyVisualFixture(fixture = {}) {
    this.state.fixtureActive = true;
    this.input.clearHover(false);
    this.input.clearGhost();

    if (fixture.boardSize !== undefined) this.state.boardSize = Number(fixture.boardSize);
    if (fixture.komi !== undefined) this.state.komi = Number(fixture.komi);
    if (fixture.handicap !== undefined) this.state.handicap = Number(fixture.handicap);
    if (fixture.mode !== undefined) this.state.mode = fixture.mode;
    if (fixture.moveNumber !== undefined) this.state.moveNumber = Number(fixture.moveNumber);
    if (fixture.maxMoveNumber !== undefined) {
      this.state.maxMoveNumber = Number(fixture.maxMoveNumber);
    } else {
      this.state.maxMoveNumber = Math.max(this.state.moveNumber, (fixture.evalHistory?.length || 0));
    }
    if (fixture.nextPlayer !== undefined) this.state.nextPlayer = fixture.nextPlayer;
    if (fixture.lastMove !== undefined) this.state.lastMove = fixture.lastMove;
    if (fixture.captures !== undefined) {
      this.state.captures = {
        B: Number(fixture.captures.B ?? fixture.captures.black ?? 0),
        W: Number(fixture.captures.W ?? fixture.captures.white ?? 0),
      };
    }

    if (fixture.board || fixture.stones) {
      const { size, board } = normalizeBoardFromPayload(
        { board_size: this.state.boardSize, board: fixture.board, stones: fixture.stones },
        this.state.boardSize
      );
      this.state.boardSize = size;
      this.state.board = board;
    } else if (fixture.boardSize !== undefined) {
      this.state.board = createEmptyBoard(this.state.boardSize);
    }

    if (fixture.analysis !== undefined) {
      this.state.analysis = normalizeAnalysis(fixture.analysis, this.state.nextPlayer);
    }
    if (fixture.evalHistory !== undefined) {
      this.state.evalHistory = Array.isArray(fixture.evalHistory) ? fixture.evalHistory : [];
    }
    if (fixture.showHeatmap !== undefined) this.state.showHeatmap = Boolean(fixture.showHeatmap);
    if (fixture.showCandidates !== undefined) this.state.analysisEnabled = Boolean(fixture.showCandidates);
    if (fixture.candidateLabelMode !== undefined) this.state.candidateLabelMode = fixture.candidateLabelMode;
    if (fixture.graphMode !== undefined) this.state.graphMode = fixture.graphMode;
    if (fixture.pvMaxMoves !== undefined) this.state.pvMaxMovesOverride = fixture.pvMaxMoves;
    if (fixture.hintBox !== undefined) this.state.hintBox = fixture.hintBox;
    if (fixture.hintState !== undefined) this.state.hintState = fixture.hintState;
    if (fixture.coachCard !== undefined) this.state.coachCard = fixture.coachCard;
    if (fixture.coachReport !== undefined) this.state.coachReport = fixture.coachReport;
    if (fixture.flashNote !== undefined) this.state.flashNote = fixture.flashNote;
    if (fixture.handedLeft !== undefined) this.state.handedLeft = Boolean(fixture.handedLeft);
    if (fixture.wsConnected !== undefined) this.state.wsConnected = Boolean(fixture.wsConnected);

    if (fixture.branchInfo !== undefined) {
      if (fixture.branchInfo) {
        this.state.isOnMainline = Boolean(fixture.branchInfo.isOnMainline);
        this.state.branchDepth = Number(fixture.branchInfo.branchDepth ?? 1);
      } else {
        this.state.isOnMainline = true;
        this.state.branchDepth = 0;
      }
    }

    if (fixture.connectionBanner !== undefined) {
      this.state.connectionBanner =
        typeof fixture.connectionBanner === 'string'
          ? fixture.connectionBanner
          : fixture.connectionBanner
            ? '⚠️ サーバーへ再接続中…'
            : null;
    }
    if (fixture.externalKatagoBanner !== undefined) {
      this.state.externalKatagoBanner =
        typeof fixture.externalKatagoBanner === 'string'
          ? fixture.externalKatagoBanner
          : fixture.externalKatagoBanner
            ? '外部 KataGo (KaTrain等) を検知中 — 自動起動を抑制中'
            : null;
    }

    // Ghost state
    if (fixture.ghostMove) {
      const pt = gtpToXy(fixture.ghostMove, this.state.boardSize);
      if (pt) {
        this.state.ghostMove = {
          x: pt.x,
          y: pt.y,
          gtp: String(fixture.ghostMove).toUpperCase(),
          color: this.state.nextPlayer,
          dragging: Boolean(fixture.ghostDragging),
        };
        this.input.setGhostExternal(this.state.ghostMove.gtp, { dragging: this.state.ghostMove.dragging });
      }
    } else if ('ghostMove' in fixture) {
      this.state.ghostMove = null;
    }

    // Hovered candidate / empty / pinned PV
    if (fixture.hoveredCandidate) {
      if (typeof fixture.hoveredCandidate === 'string') {
        const upper = fixture.hoveredCandidate.toUpperCase();
        this.state.hoveredCandidate =
          (this.state.analysis.moves || []).find((m) => m.move === upper) || null;
      } else {
        this.state.hoveredCandidate = fixture.hoveredCandidate;
      }
    } else if ('hoveredCandidate' in fixture) {
      this.state.hoveredCandidate = null;
    }

    if (fixture.hoveredEmpty) {
      const pt = gtpToXy(fixture.hoveredEmpty, this.state.boardSize);
      this.state.hoveredEmpty = pt ? { x: pt.x, y: pt.y, gtp: String(fixture.hoveredEmpty).toUpperCase() } : null;
    } else if ('hoveredEmpty' in fixture) {
      this.state.hoveredEmpty = null;
    }

    if ('pinnedPvMove' in fixture) {
      this.state.pinnedPvMove = fixture.pinnedPvMove ? String(fixture.pinnedPvMove).toUpperCase() : null;
    }

    // Zoom/pan
    if (fixture.zoom !== undefined) {
      this.state.zoom = Number(fixture.zoom);
      this.canvas.setZoomPan(this.state.zoom, fixture.panX ?? 0, fixture.panY ?? 0);
    }

    // Tabs & sheet snap
    this.syncLayoutMode();
    if (fixture.sheetTab) this.setSheetTab(fixture.sheetTab);
    if (fixture.sheetSnap) this.setSheetSnap(fixture.sheetSnap);
    if (fixture.sideTab) this.setSideTab(fixture.sideTab);
    if (fixture.menuOpen !== undefined) this.setMenuOpen(fixture.menuOpen);

    // Push board & dynamic state to Canvas synchronously
    this.canvas.setBoardState({
      boardSize: this.state.boardSize,
      board: this.state.board,
      lastMove: this.state.lastMove,
      nextPlayer: this.state.nextPlayer,
      tentativeStone: null,
    });
    this.canvas.setDynamicState({
      candidates: this.state.analysis.moves,
      ownership: this.state.analysis.ownership,
      showCandidates:
        fixture.showCandidates !== undefined
          ? Boolean(fixture.showCandidates)
          : this.state.analysisEnabled && this.state.mode !== 'play',
      candidateLabelMode: this.state.candidateLabelMode,
      showHeatmap: this.state.showHeatmap,
      hintBox: this.state.hintBox,
      ghostMove: this.state.ghostMove,
      hoverEmpty: this.state.hoveredEmpty,
      nextPlayer: this.state.nextPlayer,
    });
    this._syncPvAndHoverCanvas();
    this.renderAll();
  }

  // --- Full UI Renderers ---

  renderAll() {
    this._renderStatusHeaders();
    this._renderBoardOverlays();
    this._renderMiniInfoStrip();
    this._renderActionBars();
    this._renderToggles();
    this._renderAllGraphs();
    this._renderCandidates();
    this._renderCoach();
    this._renderBranchesAndGame();
  }

  _formatScoreLead(scoreLeadBlack) {
    if (!Number.isFinite(scoreLeadBlack)) return '互角';
    if (Math.abs(scoreLeadBlack) < 0.05) return '互角';
    const side = scoreLeadBlack > 0 ? '黒' : '白';
    return `${side}+${Math.abs(scoreLeadBlack).toFixed(1)}目`;
  }

  _renderStatusHeaders() {
    const { el, state } = this;
    const turnStr = state.nextPlayer === 'W' ? '白番' : '黒番';
    const moveLabel = `${state.moveNumber}手目(${turnStr})`;
    el.topMoveText.textContent = moveLabel;
    el.sideMoveText.textContent = moveLabel;

    const wrBlack = state.analysis.root ? state.analysis.root.winrate_black : 0.5;
    const wrPct = Math.max(2, Math.min(98, wrBlack * 100));
    el.topWinrateFill.style.width = `${wrPct.toFixed(1)}%`;
    el.sideWinrateFill.style.width = `${wrPct.toFixed(1)}%`;

    const scoreStr = state.analysis.root ? this._formatScoreLead(state.analysis.root.score_lead_black) : '互角';
    el.topScoreText.textContent = scoreStr;
    el.sideScoreText.textContent = scoreStr;

    for (const dot of [el.connDot, el.sideConnDot]) {
      dot.classList.remove('is-connected', 'is-connecting', 'is-offline');
      if (state.wsConnected) dot.classList.add('is-connected');
      else if (state.connectionBanner) dot.classList.add('is-offline');
      else dot.classList.add('is-connecting');
    }

    const handicapTag = state.handicap >= 2 ? ` ・ ${state.handicap}子局` : '';
    const metaStr = `アゲハマ 黒:${state.captures.B} 白:${state.captures.W} ・ コミ ${state.komi}${handicapTag}`;
    el.miniCapturesText.textContent = metaStr;
    el.sideGraphMeta.textContent = `黒アゲ:${state.captures.B} 白アゲ:${state.captures.W} ・ コミ${state.komi}${handicapTag}`;
  }

  _renderBoardOverlays() {
    const { el, state } = this;
    const hasConnBanner = Boolean(state.connectionBanner);
    el.connectionBanner.hidden = !hasConnBanner;
    if (hasConnBanner) {
      el.connectionBannerText.textContent = state.connectionBanner;
    }
    el.boardStage.classList.toggle('has-conn-banner', hasConnBanner);

    const hasExtBanner = Boolean(state.externalKatagoBanner);
    el.externalKatagoBanner.hidden = !hasExtBanner;
    if (hasExtBanner) {
      el.externalKatagoBannerText.textContent = state.externalKatagoBanner;
    }

    const showBranch = !state.isOnMainline && state.branchDepth > 0;
    el.branchPill.hidden = !showBranch;
    if (showBranch) {
      el.branchPillText.textContent = `🌿分岐 +${state.branchDepth}手`;
    }

    const showZoom = state.zoom > 1.02;
    el.zoomPill.hidden = !showZoom;
    if (showZoom) {
      el.btnZoomReset.textContent = `🔍${Math.round(state.zoom * 100)}%`;
    }
  }

  _renderMiniInfoStrip() {
    const { el, state } = this;
    const wrBlack = state.analysis.root ? state.analysis.root.winrate_black : 0.5;
    el.miniSparklineWr.textContent = `黒 ${(wrBlack * 100).toFixed(1)}%`;

    // Mini sparkline SVG
    this._renderMiniSparklineSvg(el.miniSparklineSvg, state.evalHistory);

    // Top 3 candidate chips
    const top3 = (state.analysis.moves || []).slice(0, 3);
    if (top3.length === 0) {
      el.miniCandRow.innerHTML = '';
    } else {
      el.miniCandRow.innerHTML = top3
        .map((c, idx) => {
          const loss = Number.isFinite(c.score_loss) ? c.score_loss : 0;
          const dotClass = idx === 0 || loss <= 0.3 ? 'is-best' : loss <= 1.0 ? 'is-strong' : 'is-runner';
          const scoreLead = this._formatScoreLead(c.score_lead_black).replace('目', '');
          const pinned = state.pinnedPvMove === c.move ? ' is-pinned' : '';
          return `
            <button type="button" class="mini-cand-chip${pinned}" data-mini-cand="${escapeHtml(c.move)}">
              <span class="mini-cand-top"><span class="cud-dot ${dotClass}"></span>${escapeHtml(c.move)}</span>
              <span class="mini-cand-sub">${escapeHtml(scoreLead)}</span>
            </button>
          `;
        })
        .join('');
      el.miniCandRow.querySelectorAll('[data-mini-cand]').forEach((btn) => {
        btn.addEventListener('click', () => this.pinCandidatePv(btn.dataset.miniCand));
      });
    }

    if (state.flashNote) {
      el.miniFlashNote.hidden = false;
      el.miniFlashNote.textContent = state.flashNote;
    } else {
      el.miniFlashNote.hidden = true;
    }
  }

  _renderActionBars() {
    const { el, state } = this;
    const isGhost = Boolean(state.ghostMove);
    const isHover = !isGhost && Boolean(state.hoveredCandidate || state.hoveredEmpty);
    const isPlay = state.mode === 'play';

    // Mobile action bar (strictly 52px)
    el.actionBarGhost.hidden = !isGhost;
    el.actionBarHover.hidden = !isHover;
    el.actionBarNormal.hidden = isGhost || isHover;

    // Tablet action bar (strictly 48px)
    el.sideActionGhost.hidden = !isGhost;
    el.sideActionHover.hidden = !isHover;
    el.sideActionNormal.hidden = isGhost || isHover;

    if (isGhost) {
      const colorText = state.nextPlayer === 'W' ? '白' : '黒';
      const label = `${colorText} ${state.ghostMove.gtp}`;
      el.ghostLabel.textContent = label;
      el.sideGhostLabel.textContent = label;
      return;
    }

    if (isHover) {
      let text = '';
      if (state.hoveredCandidate) {
        const c = state.hoveredCandidate;
        const wr = ((state.nextPlayer === 'W' ? 1 - c.winrate_black : c.winrate_black) * 100).toFixed(1);
        const lead = this._formatScoreLead(c.score_lead_black);
        const visits = c.visits ? `・${c.visits}v` : '';
        text = `👁 ${c.move}: ${wr}% (${lead}${visits})`;
      } else if (state.hoveredEmpty) {
        text = `✒ 照準 ${state.hoveredEmpty.gtp}`;
      }
      el.actionHoverText.textContent = text;
      el.sideHoverText.textContent = text;
      return;
    }

    // Normal mode text
    el.actionReviewControls.hidden = isPlay;
    el.actionPlayControls.hidden = !isPlay;
    el.sidePlayControls.hidden = !isPlay;

    if (isPlay) {
      const playText = state.hintState
        ? `💡 ヒント Lv${state.hintState.level}: ${state.hintState.lv1_macro || ''}`
        : `対局中 (${state.nextPlayer === 'W' ? '白番' : '黒番'})`;
      el.actionNormalText.textContent = playText;
      el.sideActionText.textContent = playText;
    } else {
      const best = state.analysis.moves && state.analysis.moves[0];
      if (best) {
        const wr = ((state.nextPlayer === 'W' ? 1 - best.winrate_black : best.winrate_black) * 100).toFixed(1);
        const lead = this._formatScoreLead(best.score_lead_black);
        const summary = `最善 ${best.move} (${lead} / ${wr}%)`;
        el.actionNormalText.textContent = summary;
        el.sideActionText.textContent = `${summary}${best.visits ? `・${best.visits}v` : ''}`;
      } else {
        el.actionNormalText.textContent = '盤面タップで仮置き・ドラッグ微調整';
        el.sideActionText.textContent = 'Sペン直接着手 / 指タップ仮置き';
      }
    }
  }

  _renderToggles() {
    const { el, state } = this;
    for (const btn of [el.btnHeatmapMobile, el.btnHeatmapSide, el.btnHeatmapSheet]) {
      btn.classList.toggle('is-active', state.showHeatmap);
      btn.setAttribute('aria-pressed', String(state.showHeatmap));
    }

    const modeLabel = state.graphMode === 'score' ? '目数' : '勝率';
    el.btnGraphModeSide.textContent = modeLabel;
    el.btnGraphModeSheet.textContent = modeLabel;

    if (state.mode === 'play') {
      el.analyzeBtnIcon.textContent = '💡';
      el.analyzeBtnLabel.textContent = 'ヒント';
      el.btnToggleAnalyze.classList.remove('is-active');
      el.btnSideAnalyze.textContent = '💡ヒント';
      el.btnSideAnalyze.classList.remove('is-active');
    } else {
      el.analyzeBtnIcon.textContent = '✨';
      el.analyzeBtnLabel.textContent = state.analysisEnabled ? '検討ON' : '検討OFF';
      el.btnToggleAnalyze.classList.toggle('is-active', state.analysisEnabled);
      el.btnToggleAnalyze.setAttribute('aria-pressed', String(state.analysisEnabled));
      el.btnSideAnalyze.textContent = state.analysisEnabled ? '✨検討' : '検討OFF';
      el.btnSideAnalyze.classList.toggle('is-active', state.analysisEnabled);
      el.btnSideAnalyze.setAttribute('aria-pressed', String(state.analysisEnabled));
    }
  }

  _renderSheetPanes() {
    if (this.state.sheetTab === 'candidates') this._renderCandidates();
    else if (this.state.sheetTab === 'graph') this._renderAllGraphs();
    else if (this.state.sheetTab === 'coach') this._renderCoach();
    else if (this.state.sheetTab === 'branches') this._renderBranchesAndGame();
  }

  _renderSidePanes() {
    if (this.state.sideTab === 'candidates') this._renderCandidates();
    else if (this.state.sideTab === 'coach') this._renderCoach();
    else if (this.state.sideTab === 'game') this._renderBranchesAndGame();
  }

  _renderCandidates() {
    const moves = this.state.analysis.moves || [];
    const html = this._buildCandidateListHtml(moves);
    this.el.sidePaneCandidates.innerHTML = html;
    this.el.sheetPaneCandidates.innerHTML = html;

    for (const container of [this.el.sidePaneCandidates, this.el.sheetPaneCandidates]) {
      container.querySelectorAll('[data-pin-pv]').forEach((btn) => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          this.pinCandidatePv(btn.dataset.pinPv);
        });
      });
    }
  }

  _buildCandidateListHtml(moves) {
    if (!moves || moves.length === 0) {
      return '<div class="empty-state">解析データ待機中…（✨検討ONでKataGo候補手を表示）</div>';
    }
    return moves
      .slice(0, 7)
      .map((c, idx) => {
        const loss = Number.isFinite(c.score_loss) ? c.score_loss : 0;
        const dotClass =
          idx === 0 || loss <= 0.3
            ? 'is-best'
            : loss <= 1.0
              ? 'is-strong'
              : loss <= 2.5
                ? 'is-runner'
                : 'is-other';
        const wrSide = (this.state.nextPlayer === 'W' ? 1 - c.winrate_black : c.winrate_black) * 100;
        const leadStr = this._formatScoreLead(c.score_lead_black);
        const lossStr = idx === 0 || loss < 0.05 ? '最善' : `-${loss.toFixed(1)}目`;
        const pvStr = (c.pv || []).slice(0, 6).join('→');
        const isPinned = this.state.pinnedPvMove === c.move;
        const isHovered = this.state.hoveredCandidate && this.state.hoveredCandidate.move === c.move;
        return `
          <div class="cand-row${isPinned || isHovered ? ' is-active' : ''}">
            <div class="cand-row-main">
              <div class="cand-row-top">
                <span class="cand-rank">${idx + 1}.</span>
                <span class="cud-dot ${dotClass}"></span>
                <span class="cand-move">${escapeHtml(c.move)}</span>
                <span class="cand-metric">${wrSide.toFixed(1)}%</span>
                <span class="cand-metric is-score">${escapeHtml(leadStr)}</span>
                <span class="cand-visits">${escapeHtml(lossStr)}${c.visits ? ` (${c.visits}v)` : ''}</span>
              </div>
              <div class="cand-pv-text">${escapeHtml(pvStr)}</div>
            </div>
            <button type="button" class="cand-pv-btn${isPinned ? ' is-pinned' : ''}" data-pin-pv="${escapeHtml(c.move)}">
              ${isPinned ? 'PV中' : 'PV▶'}
            </button>
          </div>
        `;
      })
      .join('');
  }

  _renderCoach() {
    const html = this._buildCoachHtml({ includeInlineGraph: false });
    const mobileHtml = this._buildCoachHtml({ includeInlineGraph: true });
    this.el.sidePaneCoach.innerHTML = html;
    this.el.sheetPaneCoach.innerHTML = mobileHtml;

    // If mobile coach tab contains inline SVG eval graph, draw it cleanly
    const inlineSvg = this.el.sheetPaneCoach.querySelector('#coach-inline-graph-svg');
    if (inlineSvg) {
      this._renderEvalGraphSvg(inlineSvg, this.state.evalHistory, { width: 360, height: 108 });
      this._bindGraphScrub(inlineSvg);
    }

    for (const container of [this.el.sidePaneCoach, this.el.sheetPaneCoach]) {
      const ttsBtn = container.querySelector('[data-tts-speak]');
      if (ttsBtn) {
        ttsBtn.addEventListener('click', () => this._toggleCoachSpeech());
      }
      const rateBtn = container.querySelector('[data-tts-rate]');
      if (rateBtn) {
        rateBtn.addEventListener('click', () => {
          const rates = [1.0, 1.25, 1.5];
          const nextIdx = (rates.indexOf(this.state.ttsRate) + 1) % rates.length;
          this.state.ttsRate = rates[nextIdx];
          this._renderCoach();
        });
      }
      const nextHintBtn = container.querySelector('[data-next-hint]');
      if (nextHintBtn) {
        nextHintBtn.addEventListener('click', () => {
          if (this.state.hintState && this.state.hintState.level < 3) {
            this.state.hintState.level += 1;
            this._renderCoach();
            this._renderActionBars();
          }
        });
      }
    }
  }

  _buildCoachHtml({ includeInlineGraph = false } = {}) {
    const { coachReport, coachCard, hintState, evalHistory, ttsRate, ttsSpeaking } = this.state;

    const inlineGraphMarkup =
      includeInlineGraph && Array.isArray(evalHistory) && evalHistory.length > 1
        ? `
          <div class="coach-inline-graph">
            <svg id="coach-inline-graph-svg" class="eval-graph-svg is-compact" viewBox="0 0 360 108" preserveAspectRatio="none" role="img" aria-label="勝率推移グラフ"></svg>
          </div>
        `
        : '';

    const ttsBar = `
      <div class="coach-tts-row">
        <button type="button" class="coach-tts-btn" data-tts-speak="1">${ttsSpeaking ? '⏹ 読み上げ停止' : '🔊 読み上げ'}</button>
        <button type="button" class="coach-rate-btn" data-tts-rate="1">${ttsRate.toFixed(ttsRate === 1 ? 1 : 2)}x</button>
      </div>
    `;

    // 1. Full-game review report
    if (coachReport) {
      const praises = (coachReport.praise_points || [])
        .map((p) => `<li>${escapeHtml(p)}</li>`)
        .join('');
      const blunders = (coachReport.blunder_comments || [])
        .map((b) => {
          if (typeof b === 'string') return `<div class="coach-blunder-item">${escapeHtml(b)}</div>`;
          const header = b.move_label || (b.move_number ? `${b.move_number}手目 ${b.move || ''}` : '');
          return `<div class="coach-blunder-item"><strong>${escapeHtml(header)}</strong> ${escapeHtml(b.comment || b.text || '')}</div>`;
        })
        .join('');
      const theme = coachReport.next_game_theme || null;
      return `
        ${inlineGraphMarkup}
        <article class="coach-card coach-selectable">
          <div class="coach-card-header">
            <span class="coach-badge">🤖 Gemini 1局振り返りレポート</span>
          </div>
          <h3 class="coach-headline">${escapeHtml(coachReport.title || '対局振り返りレポート')}</h3>
          ${ttsBar}
          ${coachReport.overall_summary ? `<div class="coach-plan-box">${escapeHtml(coachReport.overall_summary)}</div>` : ''}
          ${praises ? `<div><div class="coach-section-label">✨ 良かったポイント</div><ul class="coach-reasons">${praises}</ul></div>` : ''}
          ${coachReport.turning_point_comment ? `<div><div class="coach-section-label">⚡ 勝敗の分岐点</div><div class="coach-blunder-item">${escapeHtml(coachReport.turning_point_comment)}</div></div>` : ''}
          ${blunders ? `<div><div class="coach-section-label">🔴 重要ミス振り返り</div>${blunders}</div>` : ''}
          ${coachReport.pattern_diagnosis ? `<div><div class="coach-section-label">🧭 棋風・傾向メモ</div><div class="coach-blunder-item">${escapeHtml(coachReport.pattern_diagnosis)}</div></div>` : ''}
          ${
            theme
              ? `<div class="coach-theme-box">
                   <div class="coach-section-label">🎯 次局の重点テーマ（1点集中）</div>
                   <div class="coach-theme-title">${escapeHtml(theme.theme_title || '')}</div>
                   <div class="coach-theme-rule">${escapeHtml(theme.action_rule || '')}</div>
                 </div>`
              : ''
          }
        </article>
      `;
    }

    // 2. Single-move explain card ("Why was this a blunder?")
    if (coachCard) {
      const reasonsHtml = (coachCard.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join('');
      const lossBadge = Number.isFinite(coachCard.score_loss)
        ? `🔴 ${coachCard.move_label || '着手解説'} (-${Math.abs(coachCard.score_loss).toFixed(1)}目)`
        : '🤖 Gemini コーチ解説';
      const isBlunder = Number.isFinite(coachCard.score_loss) && coachCard.score_loss >= 2.5;
      return `
        ${inlineGraphMarkup}
        <article class="coach-card coach-selectable">
          <div class="coach-card-header">
            <span class="coach-badge${isBlunder ? ' is-blunder' : ''}">${escapeHtml(lossBadge)}</span>
          </div>
          <h3 class="coach-headline">${escapeHtml(coachCard.headline || '')}</h3>
          ${ttsBar}
          ${reasonsHtml ? `<div><div class="coach-section-label">📌 理由・根拠</div><ul class="coach-reasons">${reasonsHtml}</ul></div>` : ''}
          ${coachCard.recommended_plan ? `<div><div class="coach-section-label">💡 推奨プラン</div><div class="coach-plan-box">${escapeHtml(coachCard.recommended_plan)}</div></div>` : ''}
          ${coachCard.one_point_tip ? `<div class="coach-tip-box">✨ ワンポイント：${escapeHtml(coachCard.one_point_tip)}</div>` : ''}
        </article>
      `;
    }

    // 3. 3-Lock progressive hint state (play mode)
    if (hintState) {
      const lvl = Number(hintState.level || 1);
      return `
        <article class="coach-card coach-selectable">
          <div class="coach-card-header">
            <span class="coach-badge">💡 方針ヒント Lv${lvl} / 3</span>
          </div>
          ${hintState.lv1_macro ? `<div><div class="coach-section-label">Lv1. 大局・エリア</div><div class="coach-blunder-item">${escapeHtml(hintState.lv1_macro)}</div></div>` : ''}
          ${lvl >= 2 && hintState.lv2_strategy ? `<div><div class="coach-section-label">Lv2. 採るべき方針</div><div class="coach-plan-box">${escapeHtml(hintState.lv2_strategy)}</div></div>` : ''}
          ${lvl >= 3 && hintState.lv3_narrow ? `<div><div class="coach-section-label">Lv3. 注目エリアの着眼点</div><div class="coach-plan-box">${escapeHtml(hintState.lv3_narrow)}</div></div>` : ''}
          ${hintState.thinking_question ? `<div class="coach-tip-box">❓ ${escapeHtml(hintState.thinking_question)}</div>` : ''}
          ${lvl < 3 ? `<button type="button" class="primary-btn" data-next-hint="1">もっとヒントを見る (Lv${lvl + 1})</button>` : ''}
        </article>
      `;
    }

    // 4. Phase 2 placeholder
    return `
      ${inlineGraphMarkup}
      <div class="coach-card">
        <div class="coach-card-header">
          <span class="coach-badge">🤖 Gemini AI 囲碁コーチ (Phase 2)</span>
        </div>
        <h3 class="coach-headline">KataGoの確定ファクトに基づく日本語解説</h3>
        <div class="coach-blunder-item">
          Phase 2 では悪手の理由解説・座標を出さない3段階ヒント・1局まるごと自動振り返りレポートおよび音声読み上げ（TTS）がここに表示されます。
        </div>
      </div>
    `;
  }

  _collectCoachSpeechText() {
    const { coachReport, coachCard } = this.state;
    if (coachReport) {
      const parts = [
        coachReport.title,
        coachReport.overall_summary,
        ...(coachReport.praise_points || []),
        coachReport.turning_point_comment,
        ...(coachReport.blunder_comments || []).map((b) => (typeof b === 'string' ? b : b.comment || b.text || '')),
        coachReport.next_game_theme?.theme_title,
        coachReport.next_game_theme?.action_rule,
      ].filter(Boolean);
      return formatGoTextForSpeech(parts.join('。'));
    }
    if (coachCard) {
      const parts = [
        coachCard.headline,
        ...(coachCard.reasons || []),
        coachCard.recommended_plan,
        coachCard.one_point_tip,
      ].filter(Boolean);
      return formatGoTextForSpeech(parts.join('。'));
    }
    return '';
  }

  _toggleCoachSpeech() {
    if (typeof window === 'undefined' || !window.speechSynthesis) {
      this.showToast('この環境は音声読み上げに未対応です');
      return;
    }
    if (this.state.ttsSpeaking) {
      window.speechSynthesis.cancel();
      this.state.ttsSpeaking = false;
      this._renderCoach();
      return;
    }
    const text = this._collectCoachSpeechText();
    if (!text) return;
    try {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(text);
      utter.lang = 'ja-JP';
      utter.rate = this.state.ttsRate;
      utter.onend = () => {
        this.state.ttsSpeaking = false;
        this._renderCoach();
      };
      utter.onerror = () => {
        this.state.ttsSpeaking = false;
        this._renderCoach();
      };
      this.state.ttsSpeaking = true;
      this._renderCoach();
      window.speechSynthesis.speak(utter);
    } catch {
      this.state.ttsSpeaking = false;
    }
  }

  _renderBranchesAndGame() {
    const { state } = this;
    const modeName = state.mode === 'play' ? 'AI対局' : state.mode === 'drill' ? '悪手ドリル' : '検討モード';
    const branchStatus = state.isOnMainline ? '本譜を表示中' : `変化図 (+${state.branchDepth}手)`;
    const branchButtons = (state.branches || [])
      .map(
        (b) =>
          `<button type="button" class="secondary-btn" data-nav-node="${escapeHtml(b.node_id)}">${escapeHtml(b.label || b.move || '分岐')}</button>`
      )
      .join('');

    const html = `
      <div class="info-card">
        <div class="info-kv-grid">
          <div><span class="info-kv-label">モード:</span> <span class="info-kv-val">${escapeHtml(modeName)}</span></div>
          <div><span class="info-kv-label">盤サイズ:</span> <span class="info-kv-val">${state.boardSize}路盤</span></div>
          <div><span class="info-kv-label">コミ / 置石:</span> <span class="info-kv-val">${state.komi} / ${state.handicap}子</span></div>
          <div><span class="info-kv-label">アゲハマ:</span> <span class="info-kv-val">黒${state.captures.B}・白${state.captures.W}</span></div>
          <div><span class="info-kv-label">手数 / 分岐:</span> <span class="info-kv-val">${state.moveNumber}手・${escapeHtml(branchStatus)}</span></div>
          <div><span class="info-kv-label">エンジン:</span> <span class="info-kv-val">${escapeHtml(state.engineStatus.state || 'IDLE')}</span></div>
        </div>
        <div class="branch-btn-row">
          ${!state.isOnMainline ? '<button type="button" class="primary-btn" data-action-return-main="1">🌿 本譜へ戻る</button>' : ''}
          <button type="button" class="secondary-btn" data-action-open-menu="1">⚙ 対局・棋譜設定</button>
          ${branchButtons}
        </div>
      </div>
    `;

    this.el.sidePaneGame.innerHTML = html;
    this.el.sheetPaneBranches.innerHTML = html;

    for (const container of [this.el.sidePaneGame, this.el.sheetPaneBranches]) {
      container.querySelectorAll('[data-nav-node]').forEach((btn) => {
        btn.addEventListener('click', () => this.navigateToNode(btn.dataset.navNode));
      });
      const retBtn = container.querySelector('[data-action-return-main]');
      if (retBtn) retBtn.addEventListener('click', () => this.returnToMainline());
      const menuBtn = container.querySelector('[data-action-open-menu]');
      if (menuBtn) menuBtn.addEventListener('click', () => this.setMenuOpen(true));
    }
  }

  // --- SVG Evaluation Graphs ---

  _renderAllGraphs() {
    this._renderEvalGraphSvg(this.el.evalGraphSvg, this.state.evalHistory, { width: 460, height: 110 });
    this._renderEvalGraphSvg(this.el.sheetEvalGraphSvg, this.state.evalHistory, { width: 360, height: 150 });
    this._renderMiniSparklineSvg(this.el.miniSparklineSvg, this.state.evalHistory);
  }

  _renderMiniSparklineSvg(svgEl, history) {
    if (!svgEl) return;
    const W = 320;
    const H = 26;
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

    // 50% dashed reference line
    svgEl.appendChild(
      this._svgEl('line', {
        x1: 2,
        y1: H / 2,
        x2: W - 2,
        y2: H / 2,
        stroke: 'rgba(148, 163, 184, 0.28)',
        'stroke-dasharray': '3 3',
        'stroke-width': 1,
      })
    );

    if (!history || history.length < 2) return;

    const maxIdx = history.length - 1;
    const pts = history.map((p, i) => {
      const x = 4 + (i / maxIdx) * (W - 8);
      const wr = Number.isFinite(p.winrate_black) ? p.winrate_black : 0.5;
      const y = 3 + (1 - Math.max(0, Math.min(1, wr))) * (H - 6);
      return { x, y, p };
    });

    const d = pts.map((pt, i) => `${i === 0 ? 'M' : 'L'}${pt.x.toFixed(1)},${pt.y.toFixed(1)}`).join(' ');
    svgEl.appendChild(
      this._svgEl('path', {
        d,
        fill: 'none',
        stroke: '#38BDF8',
        'stroke-width': 1.8,
        'stroke-linejoin': 'round',
      })
    );

    // Highlight blunder / mistake dots & current move
    let lastBadgeX = -20;
    for (const pt of pts) {
      if (pt.p.badge && pt.x - lastBadgeX >= 7) {
        const fill =
          pt.p.badge === 'blunder'
            ? '#EF4444'
            : pt.p.badge === 'mistake'
              ? '#F97316'
              : pt.p.badge === 'good'
                ? '#3B82F6'
                : '#EAB308';
        svgEl.appendChild(
          this._svgEl('circle', {
            cx: pt.x.toFixed(1),
            cy: pt.y.toFixed(1),
            r: 3.0,
            fill,
            stroke: '#14171B',
            'stroke-width': 1,
          })
        );
        lastBadgeX = pt.x;
      }
      if (getGraphPointMoveNumber(pt.p, -1) === this.state.moveNumber) {
        svgEl.appendChild(
          this._svgEl('circle', {
            cx: pt.x.toFixed(1),
            cy: pt.y.toFixed(1),
            r: 3.4,
            fill: '#F8FAFC',
            stroke: '#22D3EE',
            'stroke-width': 1.4,
          })
        );
      }
    }
  }

  _renderEvalGraphSvg(svgEl, history, { width = 460, height = 110 } = {}) {
    if (!svgEl) return;
    svgEl.setAttribute('viewBox', `0 0 ${width} ${height}`);
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

    const padL = 30;
    const padR = 10;
    const padT = 10;
    const padB = 18;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;
    const isScore = this.state.graphMode === 'score';

    // Gradient definition
    const defs = this._svgEl('defs');
    const gradId = `gfill-${svgEl.id || 'eval'}`;
    const grad = this._svgEl('linearGradient', { id: gradId, x1: '0', y1: '0', x2: '0', y2: '1' });
    grad.appendChild(this._svgEl('stop', { offset: '0%', 'stop-color': '#38BDF8', 'stop-opacity': '0.28' }));
    grad.appendChild(this._svgEl('stop', { offset: '100%', 'stop-color': '#38BDF8', 'stop-opacity': '0.02' }));
    defs.appendChild(grad);
    svgEl.appendChild(defs);

    // Reference grid lines & Y-axis labels
    const maxScoreRange = isScore
      ? Math.max(
          15,
          ...(history || []).map((p) => Math.abs(Number(p.score_lead_black || 0)) + 2)
        )
      : 100;

    const yTicks = isScore
      ? [
          { label: `+${Math.round(maxScoreRange)}`, y: padT },
          { label: '0', y: padT + plotH / 2, mid: true },
          { label: `-${Math.round(maxScoreRange)}`, y: padT + plotH },
        ]
      : [
          { label: '100%', y: padT },
          { label: '50%', y: padT + plotH / 2, mid: true },
          { label: '0%', y: padT + plotH },
        ];

    for (const tick of yTicks) {
      svgEl.appendChild(
        this._svgEl('line', {
          x1: padL,
          y1: tick.y,
          x2: width - padR,
          y2: tick.y,
          stroke: tick.mid ? 'rgba(148, 163, 184, 0.42)' : 'rgba(148, 163, 184, 0.16)',
          'stroke-dasharray': tick.mid ? '4 3' : '',
          'stroke-width': 1,
        })
      );
      const txt = this._svgEl('text', {
        x: padL - 4,
        y: tick.y + 3,
        'text-anchor': 'end',
        fill: '#94A3B8',
        'font-size': 9,
        'font-weight': 600,
      });
      txt.textContent = tick.label;
      svgEl.appendChild(txt);
    }

    if (!history || history.length === 0) {
      const empty = this._svgEl('text', {
        x: padL + plotW / 2,
        y: padT + plotH / 2 + 3,
        'text-anchor': 'middle',
        fill: '#64748B',
        'font-size': 11,
      });
      empty.textContent = '対局・解析が進むと推移が表示されます';
      svgEl.appendChild(empty);
      return;
    }

    const maxIdx = Math.max(1, history.length - 1);
    const points = history.map((p, i) => {
      const x = padL + (i / maxIdx) * plotW;
      let norm;
      if (isScore) {
        const s = Number.isFinite(p.score_lead_black) ? p.score_lead_black : 0;
        norm = 0.5 + (s / (2 * maxScoreRange));
      } else {
        norm = Number.isFinite(p.winrate_black) ? p.winrate_black : 0.5;
      }
      norm = Math.max(0.02, Math.min(0.98, norm));
      const y = padT + (1 - norm) * plotH;
      return { x, y, p };
    });

    // Area under curve
    const linePath = points
      .map((pt, i) => `${i === 0 ? 'M' : 'L'}${pt.x.toFixed(1)},${pt.y.toFixed(1)}`)
      .join(' ');
    const areaPath = `${linePath} L${points[points.length - 1].x.toFixed(1)},${(padT + plotH).toFixed(1)} L${points[0].x.toFixed(1)},${(padT + plotH).toFixed(1)} Z`;

    svgEl.appendChild(this._svgEl('path', { d: areaPath, fill: `url(#${gradId})` }));
    svgEl.appendChild(
      this._svgEl('path', {
        d: linePath,
        fill: 'none',
        stroke: '#38BDF8',
        'stroke-width': 2.2,
        'stroke-linejoin': 'round',
        'stroke-linecap': 'round',
      })
    );

    // X-axis labels (first, middle, last move numbers)
    const xIndices = history.length >= 3 ? [0, Math.floor(maxIdx / 2), maxIdx] : [0, maxIdx];
    const seenX = new Set();
    for (const idx of xIndices) {
      if (seenX.has(idx) || !points[idx]) continue;
      seenX.add(idx);
      const lbl = this._svgEl('text', {
        x: points[idx].x.toFixed(1),
        y: height - 4,
        'text-anchor': idx === 0 ? 'start' : idx === maxIdx ? 'end' : 'middle',
        fill: '#94A3B8',
        'font-size': 9,
      });
      lbl.textContent = String(getGraphPointMoveNumber(points[idx].p, idx));
      svgEl.appendChild(lbl);
    }

    // Current move vertical cursor
    const curPt =
      points.find((pt, i) => getGraphPointMoveNumber(pt.p, i) === this.state.moveNumber) ||
      points[points.length - 1];
    if (curPt) {
      svgEl.appendChild(
        this._svgEl('line', {
          x1: curPt.x.toFixed(1),
          y1: padT,
          x2: curPt.x.toFixed(1),
          y2: padT + plotH,
          stroke: 'rgba(248, 250, 252, 0.55)',
          'stroke-dasharray': '3 2',
          'stroke-width': 1.2,
        })
      );
    }

    // Move quality badges with collision spacing
    const badgeColor = {
      blunder: '#EF4444',
      mistake: '#F97316',
      inaccuracy: '#EAB308',
      good: '#3B82F6',
    };
    let prevBadgeX = -99;
    let staggerToggle = 0;
    for (const pt of points) {
      const b = pt.p.badge;
      if (!b || !badgeColor[b]) continue;
      let cy = pt.y;
      if (pt.x - prevBadgeX < 11) {
        staggerToggle = staggerToggle === 0 ? 1 : 0;
        cy = Math.max(padT + 5, Math.min(padT + plotH - 5, pt.y + (staggerToggle ? -7 : 7)));
      }
      prevBadgeX = pt.x;
      svgEl.appendChild(
        this._svgEl('circle', {
          cx: pt.x.toFixed(1),
          cy: cy.toFixed(1),
          r: b === 'blunder' ? 5.2 : b === 'mistake' ? 4.5 : 4.0,
          fill: badgeColor[b],
          stroke: '#14171B',
          'stroke-width': 1.5,
        })
      );
    }

    // Active move highlighted dot on top
    if (curPt) {
      svgEl.appendChild(
        this._svgEl('circle', {
          cx: curPt.x.toFixed(1),
          cy: curPt.y.toFixed(1),
          r: 4.6,
          fill: '#F8FAFC',
          stroke: '#22D3EE',
          'stroke-width': 2.0,
        })
      );
    }
  }

  _svgEl(tag, attrs = {}) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v !== '' && v !== null && v !== undefined) {
        node.setAttribute(k, String(v));
      }
    }
    return node;
  }

  showToast(message, durationMs = 2600) {
    if (!message) return;
    this.el.toast.textContent = String(message);
    this.el.toast.hidden = false;
    if (this._toastTimer) clearTimeout(this._toastTimer);
    this._toastTimer = setTimeout(() => {
      this.el.toast.hidden = true;
      this._toastTimer = null;
    }, durationMs);
  }

  // --- QA & Debug Snapshot ---

  getDebugState() {
    return {
      gameId: this.state.gameId,
      boardSize: this.state.boardSize,
      komi: this.state.komi,
      handicap: this.state.handicap,
      mode: this.state.mode,
      currentNodeId: this.state.currentNodeId,
      stateVersion: this.state.stateVersion,
      moveNumber: this.state.moveNumber,
      nextPlayer: this.state.nextPlayer,
      lastMove: this.state.lastMove,
      captures: { ...this.state.captures },
      ghostMove: this.state.ghostMove ? this.state.ghostMove.gtp : null,
      ghostDragging: Boolean(this.state.ghostMove && this.state.ghostMove.dragging),
      hoveredMove: this.state.hoveredCandidate
        ? this.state.hoveredCandidate.move
        : this.state.hoveredEmpty
          ? this.state.hoveredEmpty.gtp
          : null,
      hoveredCandidate: this.state.hoveredCandidate ? this.state.hoveredCandidate.move : null,
      hoveredEmpty: this.state.hoveredEmpty ? this.state.hoveredEmpty.gtp : null,
      pinnedPvMove: this.state.pinnedPvMove,
      showHeatmap: this.state.showHeatmap,
      zoom: this.state.zoom,
      layoutMode: this.getLayoutMode(),
      sheetSnap: this.state.sheetSnap,
      sheetTab: this.state.sheetTab,
      sideTab: this.state.sideTab,
      menuOpen: this.state.menuOpen,
      wsConnected: this.state.wsConnected,
      swRegistered: this.state.swRegistered,
      runtime: PlatformBridge.runtime,
      lastPayload: PlatformBridge.getLastPayload(),
      inputState: this.input.state,
      lastEffectiveOffset: this.input.lastEffectiveOffset,
    };
  }
}

export default UiShell;

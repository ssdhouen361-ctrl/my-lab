/**
 * Main entrypoint for Web 碁盤 (KataGo × Gemini) Frontend.
 * - Registers Service Worker ONLY when PlatformBridge.runtime !== 'android-webview'
 * - Wires WsClient, UiShell, PlatformBridge
 * - Bootstraps deep link / recent session / fresh 19x19 review game
 * - Exposes window.__WEB_GOBAN__ for deterministic E2E & Visual QA
 */

import { PlatformBridge } from './platform-bridge.js';
import { WsClient } from './ws-client.js';
import { UiShell } from './ui-shell.js';
import { gtpToXy } from './goban-canvas.js';

const ws = new WsClient({});
const shell = new UiShell(ws);

ws.onEvent = (msg) => shell.handleWsEvent(msg);
ws.onConnectionChange = (info) => shell.handleConnectionChange(info);

// Expose deterministic QA & debug hook immediately before async bootstrap
window.__WEB_GOBAN__ = {
  getState: () => shell.getDebugState(),
  getBoardMetrics: () => shell.canvas.getBoardMetrics(),
  boardToClient: (x, y) => shell.canvas.boardToClient(x, y),
  gtpToClient: (gtp) => {
    const pt = gtpToXy(gtp, shell.state.boardSize);
    return pt ? shell.canvas.boardToClient(pt.x, pt.y) : null;
  },
  applyVisualFixture: (fixture) => shell.applyVisualFixture(fixture),
  setSheetSnap: (snap) => shell.setSheetSnap(snap),
  setSheetTab: (tab) => shell.setSheetTab(tab),
  setSideTab: (tab) => shell.setSideTab(tab),
  resetZoom: () => shell.resetZoom(),
  cancelGhost: () => shell.cancelGhost(),
  confirmGhost: () => shell.confirmGhost(),
  updateInputSettings: (patch) => shell.input.updateSettings(patch),
  shell,
  ws,
  canvas: shell.canvas,
  input: shell.input,
  platform: PlatformBridge,
};

// Register Service Worker ONLY outside Android WebView wrapper
function registerServiceWorkerIfAllowed() {
  if (PlatformBridge.runtime === 'android-webview') {
    shell.state.swRegistered = false;
    return;
  }
  if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) {
    shell.state.swRegistered = false;
    return;
  }
  navigator.serviceWorker
    .register('/sw.js')
    .then(() => {
      shell.state.swRegistered = true;
    })
    .catch(() => {
      shell.state.swRegistered = false;
    });
}

async function bootstrap() {
  registerServiceWorkerIfAllowed();

  // Ensure initial layout & board canvas dimensions are synced right after first paint
  requestAnimationFrame(() => {
    shell.syncLayoutMode();
  });

  const params = new URLSearchParams(window.location.search);
  const gameParam = params.get('game');
  const nodeParam = params.get('node');
  const sgfParam = params.get('sgf');
  const moveParam = params.get('move');
  const modeParam = params.get('mode');

  if (gameParam || sgfParam) {
    const handled = await shell.handleDeepLink({
      game: gameParam,
      node: nodeParam || undefined,
      sgf: sgfParam,
      move: moveParam !== null ? Number(moveParam) : undefined,
      mode: modeParam || undefined,
    });
    if (handled || shell.state.fixtureActive) {
      return;
    }
  }

  // Try resuming the most recent game session unless a specific fresh mode is requested
  const recentRes = await ws.recentGames(5);
  if (shell.state.fixtureActive) return;

  if (recentRes.ok && recentRes.data) {
    const list = Array.isArray(recentRes.data)
      ? recentRes.data
      : Array.isArray(recentRes.data.games)
        ? recentRes.data.games
        : [];
    const latest = list[0];
    if (latest && (latest.game_id || latest.id) && !modeParam) {
      const gid = latest.game_id || latest.id;
      const detail = await ws.getGame(gid);
      if (shell.state.fixtureActive) return;
      shell.openGame(gid, detail.ok && detail.data ? detail.data : latest);
      shell.refreshEngineStatus();
      return;
    }
  }

  // Otherwise create a fresh 19x19 review game automatically so the board is immediately usable
  const created = await ws.createGame({
    board_size: 19,
    komi: 6.5,
    handicap: 0,
    mode: modeParam === 'play' ? 'play' : 'review',
  });
  if (shell.state.fixtureActive) return;

  if (created.ok && created.data) {
    const gid = created.data.game_id || created.data.id;
    if (gid) {
      shell.openGame(gid, created.data);
      shell.refreshEngineStatus();
    }
  }
}

bootstrap();

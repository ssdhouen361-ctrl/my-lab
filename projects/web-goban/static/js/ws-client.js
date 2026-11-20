/**
 * WsClient — REST + WebSocket client with 15s/5s app-layer heartbeat,
 * exponential backoff reconnection, and zero cookie dependency (X-Client-Id).
 */

const CLIENT_ID_STORAGE_KEY = 'web-goban-client-id';

function generateClientId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `c-${crypto.randomUUID()}`;
  }
  const rand = Math.random().toString(36).slice(2, 10);
  return `c-${Date.now().toString(36)}-${rand}`;
}

function getOrCreateClientId() {
  try {
    const existing = window.localStorage.getItem(CLIENT_ID_STORAGE_KEY);
    if (existing && existing.length >= 6) return existing;
    const created = generateClientId();
    window.localStorage.setItem(CLIENT_ID_STORAGE_KEY, created);
    return created;
  } catch {
    return generateClientId();
  }
}

export class WsClient {
  constructor(options = {}) {
    this.apiBaseUrl = (
      options.apiBaseUrl ??
      (typeof window !== 'undefined' && window.GOBAN_CONFIG && window.GOBAN_CONFIG.apiBaseUrl) ??
      ''
    ).replace(/\/+$/, '');
    this.clientId = options.clientId || getOrCreateClientId();
    this.onEvent = options.onEvent || (() => {});
    this.onConnectionChange = options.onConnectionChange || (() => {});

    this.ws = null;
    this.gameId = null;
    this.connected = false;
    this.manualClose = false;
    this.seq = 0;
    this.lastSeenVersion = 0;
    this.lastMessageAt = 0;

    this.backoffMs = 500;
    this.maxBackoffMs = 15000;
    this.heartbeatIntervalId = null;
    this.pongTimeoutId = null;
    this.reconnectTimerId = null;

    this._onVisibilityChange = this._handleWakeCheck.bind(this);
    this._onOnline = this._handleWakeCheck.bind(this);
    this._onOffline = () => {
      if (this.connected) {
        this.connected = false;
        this.onConnectionChange({ connected: false, reconnecting: true, reason: 'offline' });
      }
    };

    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', this._onVisibilityChange);
    }
    if (typeof window !== 'undefined') {
      window.addEventListener('online', this._onOnline);
      window.addEventListener('offline', this._onOffline);
    }
  }

  destroy() {
    this.disconnect();
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this._onVisibilityChange);
    }
    if (typeof window !== 'undefined') {
      window.removeEventListener('online', this._onOnline);
      window.removeEventListener('offline', this._onOffline);
    }
  }

  _buildHttpUrl(path) {
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    return `${this.apiBaseUrl}${cleanPath}`;
  }

  _buildWsUrl(gameId) {
    let origin = this.apiBaseUrl;
    if (!origin && typeof window !== 'undefined') {
      origin = window.location.origin;
    }
    let wsOrigin = origin;
    if (wsOrigin.startsWith('https://')) {
      wsOrigin = `wss://${wsOrigin.slice(8)}`;
    } else if (wsOrigin.startsWith('http://')) {
      wsOrigin = `ws://${wsOrigin.slice(7)}`;
    } else if (typeof window !== 'undefined') {
      const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      wsOrigin = `${proto}//${window.location.host}`;
    }
    return `${wsOrigin}/ws/games/${encodeURIComponent(gameId)}?client_id=${encodeURIComponent(this.clientId)}`;
  }

  async _request(method, path, { json = null, formData = null, signal = null } = {}) {
    const headers = {
      'X-Client-Id': this.clientId,
    };
    let body = undefined;
    if (formData instanceof FormData) {
      body = formData;
    } else if (json !== null) {
      headers['Content-Type'] = 'application/json';
      body = JSON.stringify(json);
    }

    try {
      const resp = await fetch(this._buildHttpUrl(path), {
        method,
        headers,
        body,
        signal,
      });
      const contentType = resp.headers.get('content-type') || '';
      let data = null;
      if (contentType.includes('application/json')) {
        data = await resp.json().catch(() => null);
      } else {
        data = await resp.text().catch(() => '');
      }
      return {
        ok: resp.ok,
        status: resp.status,
        data,
        error: resp.ok ? null : (data && data.detail) || `HTTP ${resp.status}`,
      };
    } catch (err) {
      return {
        ok: false,
        status: 0,
        data: null,
        error: err ? String(err.message || err) : 'Network error',
      };
    }
  }

  // --- REST API Helpers ---

  health() {
    return this._request('GET', '/api/v1/health');
  }

  engineStatus() {
    return this._request('GET', '/api/v1/engine/status');
  }

  engineWarmup() {
    return this._request('POST', '/api/v1/engine/warmup', { json: {} });
  }

  engineStop() {
    return this._request('POST', '/api/v1/engine/stop', { json: {} });
  }

  createGame(params = {}) {
    const mode = params.mode === 'play' ? 'play' : 'review';
    return this._request('POST', '/api/v1/games', {
      json: {
        board_size: params.board_size ?? 19,
        komi: params.komi ?? 6.5,
        handicap: params.handicap ?? 0,
        mode,
        ai_level: params.ai_level ?? '5k',
        player_color: params.player_color ?? params.human_color ?? 'B',
        rules: params.rules ?? 'japanese',
      },
    });
  }

  recentGames(limit = 10) {
    return this._request('GET', `/api/v1/games/recent?limit=${encodeURIComponent(limit)}`);
  }

  getGame(gameId) {
    return this._request('GET', `/api/v1/games/${encodeURIComponent(gameId)}`);
  }

  importSgfText(gameId, sgfText) {
    return this._request('POST', `/api/v1/games/${encodeURIComponent(gameId)}/import-sgf`, {
      json: { sgf_text: sgfText },
    });
  }

  importSgfFile(gameId, file) {
    const fd = new FormData();
    fd.append('file', file);
    return this._request('POST', `/api/v1/games/${encodeURIComponent(gameId)}/import-sgf`, {
      formData: fd,
    });
  }

  exportSgfJson(gameId) {
    return this._request('GET', `/api/v1/games/${encodeURIComponent(gameId)}/export-sgf?format=json`);
  }

  listSgfs() {
    return this._request('GET', '/api/v1/sgf');
  }

  saveSgf(payload) {
    return this._request('POST', '/api/v1/sgf', { json: payload });
  }

  getSgf(sgfId) {
    return this._request('GET', `/api/v1/sgf/${encodeURIComponent(sgfId)}`);
  }

  deleteSgf(sgfId) {
    return this._request('DELETE', `/api/v1/sgf/${encodeURIComponent(sgfId)}`);
  }

  // --- WebSocket Lifecycle & Heartbeat ---

  connect(gameId, lastSeenVersion = 0) {
    if (!gameId) return;
    if (this.gameId === gameId && this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return;
    }
    this.disconnect();
    this.gameId = gameId;
    this.lastSeenVersion = lastSeenVersion || 0;
    this.manualClose = false;
    this.backoffMs = 500;
    this._openSocket();
  }

  disconnect() {
    this.manualClose = true;
    this._clearTimers();
    if (this.ws) {
      const old = this.ws;
      this.ws = null;
      try {
        old.onopen = null;
        old.onmessage = null;
        old.onclose = null;
        old.onerror = null;
        old.close(1000, 'client_disconnect');
      } catch {
        // Ignore close errors
      }
    }
    this.connected = false;
  }

  _clearTimers() {
    if (this.heartbeatIntervalId !== null) {
      clearInterval(this.heartbeatIntervalId);
      this.heartbeatIntervalId = null;
    }
    if (this.pongTimeoutId !== null) {
      clearTimeout(this.pongTimeoutId);
      this.pongTimeoutId = null;
    }
    if (this.reconnectTimerId !== null) {
      clearTimeout(this.reconnectTimerId);
      this.reconnectTimerId = null;
    }
  }

  _openSocket() {
    if (!this.gameId || this.manualClose) return;
    this._clearTimers();
    const url = this._buildWsUrl(this.gameId);

    let ws;
    try {
      ws = new WebSocket(url);
    } catch {
      this._scheduleReconnect();
      return;
    }
    this.ws = ws;

    ws.onopen = () => {
      if (this.ws !== ws) return;
      this.connected = true;
      this.backoffMs = 500;
      this.lastMessageAt = Date.now();
      this.onConnectionChange({ connected: true, reconnecting: false });
      this._startHeartbeatLoop();
      this.send('sync_request', { last_seen_version: this.lastSeenVersion });
    };

    ws.onmessage = (event) => {
      if (this.ws !== ws) return;
      this.lastMessageAt = Date.now();
      if (this.pongTimeoutId !== null) {
        clearTimeout(this.pongTimeoutId);
        this.pongTimeoutId = null;
      }
      let msg;
      try {
        msg = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!msg || typeof msg !== 'object') return;
      if (typeof msg.state_version === 'number') {
        this.lastSeenVersion = Math.max(this.lastSeenVersion, msg.state_version);
      }
      if (msg.type === 'pong') {
        return;
      }
      this.onEvent(msg);
    };

    ws.onerror = () => {
      // Let onclose handle reconnection without noisy console.error
    };

    ws.onclose = () => {
      if (this.ws !== ws) return;
      this.ws = null;
      this._clearTimers();
      const wasConnected = this.connected;
      this.connected = false;
      if (!this.manualClose) {
        this.onConnectionChange({
          connected: false,
          reconnecting: true,
          wasConnected,
        });
        this._scheduleReconnect();
      } else {
        this.onConnectionChange({ connected: false, reconnecting: false });
      }
    };
  }

  _startHeartbeatLoop() {
    if (this.heartbeatIntervalId !== null) {
      clearInterval(this.heartbeatIntervalId);
    }
    this.heartbeatIntervalId = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const idleMs = Date.now() - this.lastMessageAt;
      if (idleMs >= 15000 && this.pongTimeoutId === null) {
        this._sendPing(5000);
      }
    }, 5000);
  }

  _sendPing(timeoutMs = 5000) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    this.send('ping', { client_ts: Date.now() });
    if (this.pongTimeoutId !== null) {
      clearTimeout(this.pongTimeoutId);
    }
    this.pongTimeoutId = setTimeout(() => {
      this.pongTimeoutId = null;
      if (this.ws) {
        try {
          this.ws.close(4000, 'heartbeat_timeout');
        } catch {
          // Ignore
        }
      }
    }, timeoutMs);
  }

  _handleWakeCheck() {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    if (!this.gameId || this.manualClose) return;

    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      // Immediate 0ms ping with 3000ms pong deadline per spec
      this._sendPing(3000);
    } else if (!this.ws || this.ws.readyState === WebSocket.CLOSED) {
      if (this.reconnectTimerId !== null) {
        clearTimeout(this.reconnectTimerId);
        this.reconnectTimerId = null;
      }
      this.backoffMs = 500;
      this._openSocket();
    }
  }

  _scheduleReconnect() {
    if (this.manualClose || !this.gameId) return;
    if (this.reconnectTimerId !== null) return;
    const jitter = Math.floor(Math.random() * 250);
    const delay = this.backoffMs + jitter;
    this.backoffMs = Math.min(this.backoffMs * 2, this.maxBackoffMs);
    this.reconnectTimerId = setTimeout(() => {
      this.reconnectTimerId = null;
      this._openSocket();
    }, delay);
  }

  send(type, payload = {}, stateVersion = null) {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return false;
    const envelope = {
      type,
      seq: ++this.seq,
      state_version: stateVersion ?? this.lastSeenVersion,
      ts: Date.now(),
      payload: {
        client_id: this.clientId,
        ...payload,
      },
    };
    try {
      this.ws.send(JSON.stringify(envelope));
      return true;
    } catch {
      return false;
    }
  }
}

export default WsClient;

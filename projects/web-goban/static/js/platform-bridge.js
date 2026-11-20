/**
 * PlatformBridge — Unified abstraction for PWA / Browser <-> Android WebView Wrapper.
 * App logic must NEVER call navigator.vibrate, wakeLock, clipboard, share, or history.back directly.
 */

const HAPTIC_PATTERNS = {
  tick: 8,
  place: 16,
  confirm: [12, 22, 16],
  error: [28, 36, 28],
};

let _hapticsEnabled = true;
let _keepScreenOn = false;
let _wakeLockSentinel = null;
let _backHandler = null;
let _popstateWired = false;
let _historySentinelActive = false;
const _payloadListeners = new Set();
const _pendingPayloads = [];
let _lastPayload = null;

function getNative() {
  if (typeof window !== 'undefined' && window.WebGobanNative) {
    return window.WebGobanNative;
  }
  return null;
}

function getRuntime() {
  if (getNative()) return 'android-webview';
  if (
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(display-mode: standalone)').matches
  ) {
    return 'pwa';
  }
  return 'browser';
}

async function acquireWakeLock() {
  if (!_keepScreenOn) return;
  if (getNative()) return;
  if (typeof navigator === 'undefined' || !navigator.wakeLock || typeof navigator.wakeLock.request !== 'function') {
    return;
  }
  try {
    if (_wakeLockSentinel && !_wakeLockSentinel.released) return;
    _wakeLockSentinel = await navigator.wakeLock.request('screen');
    _wakeLockSentinel.addEventListener('release', () => {
      _wakeLockSentinel = null;
    });
  } catch {
    // WakeLock may fail when page is unfocused or unsupported; fail silently
  }
}

async function releaseWakeLock() {
  if (_wakeLockSentinel) {
    try {
      await _wakeLockSentinel.release();
    } catch {
      // Ignore release errors
    }
    _wakeLockSentinel = null;
  }
}

if (typeof document !== 'undefined') {
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && _keepScreenOn && !getNative()) {
      acquireWakeLock();
    }
  });
}

function normalizePayload(raw) {
  if (raw == null) return null;
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    if (!trimmed) return null;
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      try {
        return JSON.parse(trimmed);
      } catch {
        // Fall through to treat as raw SGF if it starts with '(;'
      }
    }
    if (trimmed.startsWith('(;')) {
      return { type: 'sgf', sgf_text: trimmed };
    }
    return { type: 'raw', text: trimmed };
  }
  if (typeof raw === 'object') {
    return raw;
  }
  return null;
}

function handleHardwareBack() {
  if (typeof _backHandler === 'function') {
    try {
      return Boolean(_backHandler());
    } catch {
      return false;
    }
  }
  return false;
}

function receivePayload(rawPayload) {
  const payload = normalizePayload(rawPayload);
  if (!payload) return false;
  _lastPayload = payload;
  if (_payloadListeners.size === 0) {
    _pendingPayloads.push(payload);
    return true;
  }
  for (const listener of _payloadListeners) {
    try {
      listener(payload);
    } catch {
      // Isolate listener errors
    }
  }
  return true;
}

function ensurePopstateListener() {
  if (_popstateWired || typeof window === 'undefined') return;
  _popstateWired = true;
  window.addEventListener('popstate', () => {
    _historySentinelActive = false;
    if (getRuntime() !== 'android-webview') {
      handleHardwareBack();
    }
  });
}

export const PlatformBridge = {
  get runtime() {
    return getRuntime();
  },

  setHapticsEnabled(enabled) {
    _hapticsEnabled = Boolean(enabled);
  },

  isHapticsEnabled() {
    return _hapticsEnabled;
  },

  haptic(kind = 'tick') {
    if (!_hapticsEnabled) return;
    const native = getNative();
    if (native && typeof native.haptic === 'function') {
      try {
        native.haptic(String(kind));
      } catch {
        // Ignore bridge errors
      }
      return;
    }
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
      try {
        const pattern = HAPTIC_PATTERNS[kind] ?? HAPTIC_PATTERNS.tick;
        navigator.vibrate(pattern);
      } catch {
        // Ignore browser vibration restrictions
      }
    }
  },

  async setKeepScreenOn(enabled) {
    _keepScreenOn = Boolean(enabled);
    const native = getNative();
    if (native && typeof native.setKeepScreenOn === 'function') {
      try {
        native.setKeepScreenOn(_keepScreenOn);
      } catch {
        // Ignore bridge errors
      }
      return;
    }
    if (_keepScreenOn) {
      await acquireWakeLock();
    } else {
      await releaseWakeLock();
    }
  },

  async copyText(text) {
    const str = String(text ?? '');
    const native = getNative();
    if (native && typeof native.copyText === 'function') {
      try {
        native.copyText(str);
        return true;
      } catch {
        // Fall back to web clipboard
      }
    }
    if (typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      try {
        await navigator.clipboard.writeText(str);
        return true;
      } catch {
        // Fall through to textarea fallback
      }
    }
    if (typeof document !== 'undefined') {
      try {
        const ta = document.createElement('textarea');
        ta.value = str;
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.top = '-9999px';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        const ok = document.execCommand('copy');
        document.body.removeChild(ta);
        return Boolean(ok);
      } catch {
        return false;
      }
    }
    return false;
  },

  async shareOrDownloadFile({ filename = 'game.sgf', content = '', mimeType = 'application/x-go-sgf' } = {}) {
    const native = getNative();
    if (native && typeof native.shareFile === 'function') {
      try {
        native.shareFile(filename, String(content), mimeType);
        return true;
      } catch {
        // Fall back to web share / download
      }
    }

    if (typeof navigator !== 'undefined' && typeof navigator.share === 'function' && typeof File !== 'undefined') {
      try {
        const file = new File([content], filename, { type: mimeType });
        if (!navigator.canShare || navigator.canShare({ files: [file] })) {
          await navigator.share({ files: [file], title: filename });
          return true;
        }
      } catch (err) {
        if (err && err.name === 'AbortError') {
          return false;
        }
        // Fall back to anchor download
      }
    }

    if (typeof document !== 'undefined' && typeof Blob !== 'undefined' && typeof URL !== 'undefined') {
      try {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 1000);
        return true;
      } catch {
        return false;
      }
    }
    return false;
  },

  setSystemBarTheme(hex = '#1A1D21', darkIcons = false) {
    const native = getNative();
    if (native && typeof native.setSystemBarTheme === 'function') {
      try {
        native.setSystemBarTheme(hex, Boolean(darkIcons));
      } catch {
        // Ignore bridge errors
      }
      return;
    }
    if (typeof document !== 'undefined') {
      let meta = document.querySelector('meta[name="theme-color"]');
      if (!meta) {
        meta = document.createElement('meta');
        meta.name = 'theme-color';
        document.head.appendChild(meta);
      }
      meta.setAttribute('content', hex);
    }
  },

  updateBoardExclusionZone(rect) {
    if (!rect) return;
    const native = getNative();
    if (native && typeof native.updateBoardExclusionZone === 'function') {
      try {
        const payload = {
          left: Math.round(rect.left || 0),
          top: Math.round(rect.top || 0),
          right: Math.round(rect.right || 0),
          bottom: Math.round(rect.bottom || 0),
          width: Math.round(rect.width || 0),
          height: Math.round(rect.height || 0),
        };
        native.updateBoardExclusionZone(JSON.stringify(payload));
      } catch {
        // Ignore bridge errors
      }
    }
  },

  registerBackHandler(fn) {
    _backHandler = typeof fn === 'function' ? fn : null;
    ensurePopstateListener();
  },

  pushUiOverlayHistory(tag = 'overlay') {
    if (getRuntime() === 'android-webview') return;
    if (typeof window === 'undefined' || !window.history || typeof window.history.pushState !== 'function') return;
    if (_historySentinelActive) return;
    try {
      window.history.pushState({ webGobanOverlay: tag }, '');
      _historySentinelActive = true;
    } catch {
      // Ignore restricted history APIs
    }
  },

  clearUiOverlayHistoryFlag() {
    _historySentinelActive = false;
  },

  onIncomingPayload(fn) {
    if (typeof fn !== 'function') return () => {};
    _payloadListeners.add(fn);
    if (_pendingPayloads.length > 0) {
      const queued = _pendingPayloads.splice(0, _pendingPayloads.length);
      for (const item of queued) {
        try {
          fn(item);
        } catch {
          // Isolate listener errors
        }
      }
    }
    return () => {
      _payloadListeners.delete(fn);
    };
  },

  getLastPayload() {
    return _lastPayload;
  },

  getSafeAreaInsets() {
    const result = { top: 0, bottom: 0, left: 0, right: 0 };
    if (typeof window === 'undefined' || typeof document === 'undefined') return result;
    const style = window.getComputedStyle(document.documentElement);
    const parsePx = (v) => {
      const n = parseFloat(v);
      return Number.isFinite(n) ? n : 0;
    };
    result.top = parsePx(style.getPropertyValue('--app-inset-top'));
    result.bottom = parsePx(style.getPropertyValue('--app-inset-bottom'));
    result.left = parsePx(style.getPropertyValue('--app-inset-left'));
    result.right = parsePx(style.getPropertyValue('--app-inset-right'));
    return result;
  },
};

if (typeof window !== 'undefined') {
  window.PlatformBridge = PlatformBridge;
  window.WebGobanApp = {
    handleHardwareBack,
    receivePayload,
  };
}

export default PlatformBridge;

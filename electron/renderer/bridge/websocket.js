/**
 * WebSocket 桥接层
 * 负责：连接 Python 后端、接收状态更新、降级模式
 *
 * @typedef {Object} StatusPayload
 * @property {boolean} connected
 * @property {boolean} [error]
 *
 * @typedef {Object} StatePayload
 * @property {string} [phase]
 * @property {number} [depth_factor]
 * @property {number} [intent]
 * @property {boolean} [speaking]
 */

/** 默认重连延迟（毫秒） */
const DEFAULT_RECONNECT_DELAY_MS = 3000;
/** 最大重连延迟（毫秒） */
const MAX_RECONNECT_DELAY_MS = 30000;
/** 重连延迟增长倍数 */
const RECONNECT_BACKOFF_MULTIPLIER = 1.5;

class BackendBridge {
  /**
   * @param {function(StatePayload): void} onState - 状态更新回调
   * @param {function(StatusPayload): void} onStatus - 连接状态回调
   */
  constructor(onState, onStatus) {
    this.onState = onState;
    this.onStatus = onStatus;
    this.ws = null;
    this.url = null;
    this.reconnectTimer = null;
    this.connected = false;
    this.reconnectDelay = DEFAULT_RECONNECT_DELAY_MS;
    this.maxReconnectDelay = MAX_RECONNECT_DELAY_MS;
    this.simulateMode = false;
  }

  // ── Connection ────────────────────────────────────────

  /** Establish WebSocket connection to the backend. */
  async connect() {
    // 获取后端地址
    if (window.galaxyAPI) {
      this.url = await window.galaxyAPI.getBackendUrl();
    } else {
      // 独立运行模式（浏览器预览）
      this.url = 'ws://localhost:8765';
    }

    this._tryConnect();
  }

  _tryConnect() {
    if (this.ws) {
      try { this.ws.close(); } catch (e) {}
    }

    try {
      this.ws = new WebSocket(this.url);

      this.ws.onopen = () => {
        console.log('[BackendBridge] Connected');
        this.connected = true;
        this.reconnectDelay = 3000;
        this.simulateMode = false;
        if (this.onStatus) this.onStatus({ connected: true });
      };

      this.ws.onmessage = (evt) => {
        try {
          const state = JSON.parse(evt.data);
          if (this.onState) this.onState(state);
        } catch (e) {
          console.error('[BackendBridge] Parse error:', e);
        }
      };

      this.ws.onclose = () => {
        this.connected = false;
        if (this.onStatus) this.onStatus({ connected: false });
        this._scheduleReconnect();
      };

      this.ws.onerror = (err) => {
        console.error('[BackendBridge] WS error:', err);
        this.connected = false;
        if (this.onStatus) this.onStatus({ connected: false, error: true });
      };
    } catch (e) {
      console.error('[BackendBridge] Failed to create WS:', e);
      this._scheduleReconnect();
    }
  }

  _scheduleReconnect() {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    console.log(`[BackendBridge] Reconnecting in ${this.reconnectDelay}ms...`);
    this.reconnectTimer = setTimeout(() => {
      this.reconnectDelay = Math.min(
        this.reconnectDelay * RECONNECT_BACKOFF_MULTIPLIER,
        this.maxReconnectDelay
      );
      this._tryConnect();
    }, this.reconnectDelay);
  }

  // ── Simulation fallback ────────────────────────────────
  // When backend disconnects, enable local simulation so the animation
  // loop keeps running rather than freezing on a blank screen.

  /** Enable local simulation mode (animation continues without backend). */
  enableSimulation() {
    if (this.simulateMode) return;
    this.simulateMode = true;
    console.log('[BackendBridge] Simulation mode enabled');
  }

  isSimulating() {
    return this.simulateMode;
  }

  // ── Send ────────────────────────────────────────

  /**
   * Send data to the backend via WebSocket.
   * @param {Object} data — serialisable payload object
   */
  send(data) {
    if (this.ws && this.connected) {
      this.ws.send(JSON.stringify(data));
    }
  }

  // ── Disconnect ────────────────────────────────────────

  /** Clean up timers and close the WebSocket connection. */
  disconnect() {
    this.simulateMode = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.connected = false;
  }
}

if (typeof module !== 'undefined') module.exports = { BackendBridge };

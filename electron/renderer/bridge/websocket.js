/**
 * WebSocket 桥接层
 * 负责：连接 Python 后端、接收状态更新、降级模式
 */

class BackendBridge {
  constructor(onState, onStatus) {
    this.onState = onState;
    this.onStatus = onStatus;
    this.ws = null;
    this.url = null;
    this.reconnectTimer = null;
    this.connected = false;
    this.reconnectDelay = 3000;
    this.maxReconnectDelay = 30000;
    this.simulateMode = false;
  }

  // ── 连接 ────────────────────────────────────────

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
      this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, this.maxReconnectDelay);
      this._tryConnect();
    }, this.reconnectDelay);
  }

  // ── 降级模拟模式 ────────────────────────────────
  // 当后端断开时，启用本地模拟，确保动画不中断

  enableSimulation() {
    if (this.simulateMode) return;
    this.simulateMode = true;
    console.log('[BackendBridge] Simulation mode enabled');
  }

  isSimulating() {
    return this.simulateMode;
  }

  // ── 发送 ────────────────────────────────────────

  send(data) {
    if (this.ws && this.connected) {
      this.ws.send(JSON.stringify(data));
    }
  }

  // ── 断开 ────────────────────────────────────────

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

/**
 * Galaxy Desktop Presence Renderer
 *
 * 职责：接收 DesktopPresenceRuntime 推送的状态事件，渲染三态视觉效果。
 *
 * 不做任何状态机、不做任何 AI 决策、不模拟后端。
 * 纯粹渲染层：WebSocket 事件 → depth_factor → WebGL 渲染。
 */

class GalaxyRenderer {
  constructor() {
    this.canvas = document.getElementById('overlay');
    this.webgl = null;
    this.time = 0;
    this.lastFrame = 0;

    // 当前渲染状态（由后端驱动）
    this.depth = 0.0;
    this.intent = 0.0;
    this.speaking = false;
    this.phase = 'static';

    // Spring 物理（只用于平滑 depth 变化，不做状态切换）
    this.currentDepth = 0.0;
    this.springV = 0;

    // 灵动岛
    this.islandEl = document.getElementById('island');
    this.islandText = document.getElementById('islandText');
  }

  async init() {
    // DPI 自适应
    this._resize();
    window.addEventListener('resize', () => this._resize());

    // 初始化 WebGL
    this.webgl = new WebGLContext(this.canvas);
    await this.webgl.init();

    // 连接后端
    this._connectWebSocket();

    // 启动渲染循环
    requestAnimationFrame((t) => this._loop(t));
  }

  // ── WebSocket：接收 DesktopPresenceRuntime 事件 ──

  _connectWebSocket() {
    const url = window.lumivAPI
      ? null // 由 preload 提供
      : 'ws://localhost:9000/ws/desktop-presence';

    if (window.lumivAPI?.onBackendState) {
      // Electron 模式：通过 IPC 接收
      window.lumivAPI.onBackendState((state) => this._onStateEvent(state));
    } else {
      // 浏览器预览模式：直接 WebSocket
      this._wsConnect(url);
    }
  }

  _wsConnect(url) {
    try {
      const ws = new WebSocket(url);

      ws.onopen = () => {
        console.log('[Galaxy] WebSocket connected');
        ws.send(JSON.stringify({ type: 'register', client: 'desktop-presence', version: '2.0.0' }));
      };

      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          if (msg.type === 'state_event' && msg.payload) {
            this._onStateEvent(msg.payload);
          }
        } catch (e) {}
      };

      ws.onclose = () => {
        console.log('[Galaxy] WebSocket closed, retrying...');
        setTimeout(() => this._wsConnect(url), 3000);
      };

      ws.onerror = () => {};
    } catch (e) {
      console.error('[Galaxy] WebSocket failed:', e);
    }
  }

  // ── 状态事件处理（唯一入口） ──

  _onStateEvent(payload) {
    // payload: { phase, depth_factor, intent, speaking, source: "DesktopPresenceRuntime" }
    if (payload.depth_factor !== undefined) {
      this.depth = payload.depth_factor;
    }
    if (payload.intent !== undefined) {
      this.intent = payload.intent;
    }
    if (payload.speaking !== undefined) {
      this.speaking = payload.speaking;
    }
    if (payload.phase !== undefined) {
      this.phase = payload.phase;
    }
  }

  // ── Spring 物理（只平滑，不切换） ──

  _springUpdate(dt) {
    const target = this.depth;
    const intentBoost = 1.0 + this.intent * 1.5;
    const tension = this.currentDepth < target ? 50 * intentBoost : 70;
    const friction = 14;
    const force = -tension * (this.currentDepth - target);
    this.springV += (force + -friction * this.springV) * dt;
    this.currentDepth += this.springV * dt;
    this.currentDepth = Math.max(0, Math.min(1, this.currentDepth));
  }

  // ── 渲染循环 ──

  _loop(now) {
    const dt = Math.min((now - this.lastFrame) / 1000, 0.05);
    this.lastFrame = now;
    this.time += dt;

    // Spring 平滑（不做状态切换）
    this._springUpdate(dt);

    // 三态权重
    const silentW  = Math.max(0, 1 - this.currentDepth / 0.30);
    const liminalW = Math.max(0, Math.min(1, (this.currentDepth - 0.15) / 0.40) * Math.min(1, (0.95 - this.currentDepth) / 0.35));

    // 更新 WebGL Uniforms
    this.webgl.setUniform('u_time',       this.time);
    this.webgl.setUniform('u_resolution', [this.canvas.width, this.canvas.height]);
    this.webgl.setUniform('u_depth',      this.currentDepth);
    this.webgl.setUniform('u_intent',     this.intent);
    this.webgl.setUniform('u_speaking',   this.speaking ? 1.0 : 0.0);

    this.webgl.render();

    // 灵动岛
    this._updateIsland();

    requestAnimationFrame((t) => this._loop(t));
  }

  // ── 灵动岛 ──

  _updateIsland() {
    let progress = 0;
    let text = 'Galaxy';

    if (this.currentDepth > 0.10 && this.currentDepth < 0.90) {
      if (this.currentDepth < 0.35) {
        progress = Math.min(1, (this.currentDepth - 0.10) / 0.18);
        text = 'Galaxy';
      } else if (this.currentDepth < 0.65) {
        progress = 1;
        text = this.speaking ? '倾听中...' : 'Galaxy';
      } else {
        progress = Math.max(0, 1 - (this.currentDepth - 0.65) / 0.18);
        text = '执行中...';
      }
    }

    if (progress > 0.01) {
      this.islandEl.classList.add('visible');
      this.islandText.textContent = text;
      this.islandEl.style.opacity = Math.min(1, progress).toFixed(2);
    } else {
      this.islandEl.classList.remove('visible');
    }
  }

  // ── DPI 自适应 ──

  _resize() {
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.canvas.width  = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width  = w + 'px';
    this.canvas.style.height = h + 'px';
  }
}

// ── 启动 ──
window.addEventListener('DOMContentLoaded', () => {
  window.lumivRenderer = new GalaxyRenderer();
  window.lumivRenderer.init();
});

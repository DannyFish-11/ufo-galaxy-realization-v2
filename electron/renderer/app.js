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

    // WebGL 是否可用；不可用时走 DOM 兜底渲染
    this.webglOK = false;
    this.fallbackOrb = null;
    this.wakeHint = null;

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

    // 初始化 WebGL —— 关键加固：笔记本/无独显/驱动不支持 WebGL2 时，getContext 或
    // shader 编译会抛错。此前没有 try/catch → 整个渲染循环不启动 → 覆盖层永久空白，
    // 连唤醒(manifest)也看不到任何东西（用户「按了打不开」的根因之一）。
    // 现在 WebGL 失败时降级为 DOM 渲染兜底，渲染循环照常运行，唤醒一定有可见反馈。
    this.webgl = new WebGLContext(this.canvas);
    try {
      await this.webgl.init();
      this.webglOK = true;
    } catch (e) {
      this.webglOK = false;
      console.error('[Galaxy] WebGL 初始化失败，启用 DOM 兜底渲染:', e);
    }

    // DOM 兜底视觉（无论 WebGL 是否可用都构建，保证唤醒有可见反馈）
    this._buildFallback();

    // 连接后端
    this._connectBackend();

    // 启动渲染循环
    requestAnimationFrame((t) => this._loop(t));
  }

  // ── WebSocket：接收 DesktopPresenceRuntime 事件 ──

  _connectBackend() {
    if (window.galaxyAPI?.onBackendState) {
      // PR-IPC: Electron 模式 — 通过 IPC 接收（内存级，无 WebSocket）
      window.galaxyAPI.onBackendState((payload) => this._onStateEvent(payload));
      console.log('[Galaxy] IPC backend connected');
    } else {
      // 浏览器预览模式：fallback 到 WebSocket
      this._wsConnect('ws://localhost:9000/ws/desktop-presence');
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
    // OpenClawd 实时状态文本（后端动态生成）
    if (payload.status_text !== undefined) {
      // 可选：用于灵动岛显示
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

    // 更新 WebGL Uniforms（仅当 WebGL 可用）
    if (this.webglOK) {
      this.webgl.setUniform('u_time',       this.time);
      this.webgl.setUniform('u_resolution', [this.canvas.width, this.canvas.height]);
      this.webgl.setUniform('u_depth',      this.currentDepth);
      this.webgl.setUniform('u_intent',     this.intent);
      this.webgl.setUniform('u_speaking',   this.speaking ? 1.0 : 0.0);
      this.webgl.render();
    }

    // 灵动岛
    this._updateIsland();

    // DOM 兜底视觉（WebGL 不可用时承担主视觉；可用时仅作唤醒提示）
    this._updateFallback();

    requestAnimationFrame((t) => this._loop(t));
  }

  // ── DOM 兜底渲染 ──
  // 保证「即使 WebGL 挂了」覆盖层依然有可见反馈：silent 时右下角一颗呼吸光点，
  // 唤醒(manifest)时屏幕中央一张「Galaxy 已就绪」提示卡。这样唤醒一定看得见。

  _buildFallback() {
    const orb = document.createElement('div');
    orb.id = 'fallbackOrb';
    orb.style.cssText = [
      'position:fixed', 'right:22px', 'bottom:54px', 'width:18px', 'height:18px',
      'border-radius:50%', 'z-index:10000', 'pointer-events:none', 'opacity:0',
      'background:radial-gradient(circle, #29e1fd 0%, #6d5cff 55%, #ff2e93 100%)',
      'box-shadow:0 0 16px 4px rgba(109,92,255,0.55)',
      'transition:opacity 0.4s ease',
    ].join(';');
    document.body.appendChild(orb);
    this.fallbackOrb = orb;

    const hint = document.createElement('div');
    hint.id = 'wakeHint';
    hint.textContent = 'Galaxy — 已唤醒';
    hint.style.cssText = [
      'position:fixed', 'left:50%', 'top:46%', 'transform:translate(-50%,-50%) scale(0.9)',
      'z-index:10001', 'pointer-events:none', 'opacity:0',
      'padding:14px 30px', 'border-radius:18px', 'font-size:18px', 'letter-spacing:1px',
      'color:#eaf6ff', 'font-weight:500',
      'background:linear-gradient(135deg, rgba(41,225,253,0.18), rgba(184,61,245,0.18))',
      'backdrop-filter:blur(20px)', '-webkit-backdrop-filter:blur(20px)',
      'border:1px solid rgba(140,180,255,0.30)',
      'box-shadow:0 8px 40px rgba(80,90,200,0.35)',
      'transition:opacity 0.5s ease, transform 0.5s cubic-bezier(0.2,0.9,0.2,1)',
    ].join(';');
    document.body.appendChild(hint);
    this.wakeHint = hint;
  }

  _updateFallback() {
    const d = this.currentDepth;
    // 呼吸光点：WebGL 不可用时一直作为「系统在线」指示；可用时不抢戏（只在唤醒时亮）。
    if (this.fallbackOrb) {
      const breathe = 0.55 + 0.45 * Math.sin(this.time * 2.0);
      const base = this.webglOK ? Math.max(0, (d - 0.5) * 2) : Math.max(0.35, d);
      this.fallbackOrb.style.opacity = Math.min(1, base * breathe).toFixed(2);
    }
    // 唤醒提示卡：depth 越高越显形（manifest 态）。
    if (this.wakeHint) {
      const awake = d > 0.55;
      this.wakeHint.style.opacity = awake ? Math.min(1, (d - 0.55) / 0.30).toFixed(2) : '0';
      this.wakeHint.style.transform = awake
        ? 'translate(-50%,-50%) scale(1)'
        : 'translate(-50%,-50%) scale(0.9)';
    }
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

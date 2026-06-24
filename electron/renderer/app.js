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

    // 当前渲染状态（由后端驱动）。默认 silent(0.05) → 启动即显示暖香槟辉光(第一态)，
    // 后端 presence 事件到达后再平滑过渡到 liminal/manifest。
    this.depth = 0.05;
    this.intent = 0.0;
    this.speaking = false;
    this.phase = 'static';

    // WebGL 是否可用；不可用时走 DOM 兜底渲染
    this.webglOK = false;
    this.fallbackOrb = null;
    this.wakeHint = null;
    this._idleCleared = false;  // 静默时只清屏一次的标记

    // Spring 物理（只用于平滑 depth 变化，不做状态切换）
    this.currentDepth = 0.05;
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
    // 先排下一帧，再做限帧早退 —— 保证循环不中断。
    requestAnimationFrame((t) => this._loop(t));

    // 自适应帧率（无独显/软件渲染 SwiftShader 笔记本的关键省电闸）：
    //  - 静默第一态【休眠】（depth≈0.05、无过渡）只需慢呼吸 → 12fps，CPU 占用直降 ~60%；
    //  - 过渡中 或 已进入二/三态(liminal/manifest) → 30fps，保证连贯流畅、绝不切割。
    // 全屏片段着色器开销 ∝ 像素数 × 帧率；休眠期降帧是整机不卡死的第一道闸。
    const transitioning = Math.abs(this.springV) > 0.0015
        || Math.abs(this.currentDepth - this.depth) > 0.01;
    const lively = this.currentDepth > 0.30 || transitioning;
    const minFrameMs = 1000 / (lively ? 30 : 12);
    if (now - this.lastFrame < minFrameMs) return;
    const dt = Math.min((now - this.lastFrame) / 1000, 0.05);
    this.lastFrame = now;
    this.time += dt;

    // Spring 平滑（不做状态切换）
    this._springUpdate(dt);

    // 完整三态：真实 depth 直接喂着色器，silent→liminal→manifest 连贯过渡，绝不切割。
    // 静默(接近 0)空闲时只清屏一次，避免空跑着色器（不影响任何状态/过渡）。
    const active = this.currentDepth > 0.015 || Math.abs(this.springV) > 0.0015;
    if (this.webglOK) {
      if (active) {
        this.webgl.setUniform('u_time',       this.time);
        this.webgl.setUniform('u_resolution', [this.canvas.width, this.canvas.height]);
        this.webgl.setUniform('u_depth',      this.currentDepth);
        this.webgl.setUniform('u_intent',     this.intent);
        this.webgl.setUniform('u_speaking',   this.speaking ? 1.0 : 0.0);
        this.webgl.render();
        this._idleCleared = false;
      } else if (!this._idleCleared) {
        this.webgl.clear();        // 静默时只清一次，之后不再跑着色器
        this._idleCleared = true;
      }
    }

    // 灵动岛 + DOM 兜底视觉（都很轻）
    this._updateIsland();
    this._updateFallback();
  }

  // ── DOM 兜底渲染 ──
  // 保证「即使 WebGL 挂了」覆盖层依然有可见反馈：silent 时右下角一颗呼吸光点，
  // 唤醒(manifest)时屏幕中央一张「Galaxy 已就绪」提示卡。这样唤醒一定看得见。

  _buildFallback() {
    // 暖香槟边缘氛围光（DOM 版第一态）：当 WebGL/着色器不可用（无独显、驱动不支持
    // WebGL2、SwiftShader 失败、shader 加载失败）时，仍用纯 CSS 内阴影把屏幕四边柔和框起来，
    // 保证「覆盖层确实打开了」一眼可见——而不是只剩一颗几乎看不见的小光点（用户「打不开」的根因）。
    const glow = document.createElement('div');
    glow.id = 'fallbackGlow';
    glow.style.cssText = [
      'position:fixed', 'inset:0', 'z-index:9998', 'pointer-events:none', 'opacity:0',
      'box-shadow:inset 0 0 200px 56px rgba(255,209,153,0.34)',
      'transition:opacity 0.6s ease',
    ].join(';');
    document.body.appendChild(glow);
    this.fallbackGlow = glow;

    const orb = document.createElement('div');
    orb.id = 'fallbackOrb';
    orb.style.cssText = [
      'position:fixed', 'right:22px', 'bottom:54px', 'width:18px', 'height:18px',
      'border-radius:50%', 'z-index:10000', 'pointer-events:none', 'opacity:0',
      // 暖香槟金，与第一态主题一致（此前是冷色，跑题）
      'background:radial-gradient(circle, #ffe7c2 0%, #ffd199 55%, #d8a766 100%)',
      'box-shadow:0 0 16px 4px rgba(255,209,153,0.55)',
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
    // DOM 兜底【仅在 WebGL 不可用时】出现，绝不叠加在正常三态之上（不乱加）。
    // WebGL 正常时，画面 100% 由着色器的完整三态负责。
    const d = this.currentDepth;
    if (this.webglOK) {
      if (this.fallbackGlow) this.fallbackGlow.style.opacity = '0';
      if (this.fallbackOrb) this.fallbackOrb.style.opacity = '0';
      if (this.wakeHint) this.wakeHint.style.opacity = '0';
      return;
    }
    // 暖香槟边缘辉光：第一态(silent)即清晰可见、柔和呼吸；进入二/三态(depth 升高)时
    // 渐隐让位给空间/提示卡。这就是「不靠 WebGL 也能看见第一态」的关键兜底。
    if (this.fallbackGlow) {
      const breathe = 0.84 + 0.16 * Math.sin(this.time * 1.4);
      const base = d < 0.35 ? (0.6 + d * 0.6) : Math.max(0, 0.81 - (d - 0.35) * 1.4);
      this.fallbackGlow.style.opacity = Math.max(0, Math.min(0.92, base * breathe)).toFixed(2);
    }
    if (this.fallbackOrb) {
      const breathe = 0.55 + 0.45 * Math.sin(this.time * 2.0);
      this.fallbackOrb.style.opacity = Math.min(1, Math.max(0.35, d) * breathe).toFixed(2);
    }
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
    const w = window.innerWidth;
    const h = window.innerHeight;
    // 限制内部渲染分辨率：着色器开销 ∝ 像素数。软件渲染下 1920x1080(≈2.1M 像素/帧)
    // 会卡死；把长边压到 ≤960 像素(并忽略 devicePixelRatio)后开销降到 ~1/4~1/5，
    // 氛围模糊视觉放大铺满全屏几乎无损。CSS 尺寸仍是全屏。
    const MAX = 800;
    const scale = Math.min(1, MAX / Math.max(w, h, 1));
    this.canvas.width  = Math.max(1, Math.round(w * scale));
    this.canvas.height = Math.max(1, Math.round(h * scale));
    this.canvas.style.width  = w + 'px';
    this.canvas.style.height = h + 'px';
  }
}

// ── 启动 ──
window.addEventListener('DOMContentLoaded', () => {
  window.lumivRenderer = new GalaxyRenderer();
  window.lumivRenderer.init();
});

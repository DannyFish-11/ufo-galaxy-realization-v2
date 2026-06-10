/**
 * Lumiv Desktop — 渲染进程主逻辑
 *
 * 核心职责：
 * 1. 后端状态管理（接收或模拟）
 * 2. Spring 物理（自适应速度）
 * 3. WebGL 渲染循环 + Uniform 更新
 * 4. 灵动岛控制
 * 5. 三态权重计算
 *
 * 流转逻辑（与 Canvas 2D 版本 1:1 一致）：
 * - depth 0.0→0.30: Silent 边缘光环
 * - depth 0.15→0.95: Liminal 透视空间
 * - depth 0.90+: Manifest 透明，AI 执行操作
 */

class LumivApp {
  constructor() {
    // DOM
    this.canvas = document.getElementById('overlay');
    this.depthEl = document.getElementById('depth');

    // WebGL
    this.webgl = null;

    // 灵动岛
    this.island = null;

    // 桥接
    this.bridge = null;

    // ── 渲染状态（由后端数据驱动） ──
    this.currentDepth = 0.0;
    this.targetDepth = 0.0;
    this.springV = 0;
    this.time = 0;

    // ── 后端状态 ──
    this.backendState = {
      phase: 'silent',
      intent: 0.0,
      speaking: false,
      activeTask: null,
      taskProgress: 0,
    };

    // 状态计时器
    this.stateTimer = 0;

    // 渲染循环
    this.lastTime = 0;
    this.rafId = null;
    this.running = false;

    // 开发模式
    this.isDev = false;
  }

  // ── 初始化 ──────────────────────────────────────

  async init() {
    // 自适应 DPI
    this._setupDPI();

    // 初始化 WebGL
    try {
      this.webgl = new WebGLContext(this.canvas);
      await this.webgl.init();
      console.log('[Lumiv] WebGL initialized');
    } catch (e) {
      console.error('[Lumiv] WebGL init failed:', e);
      // 降级到 Canvas 2D（理论上不会发生，因为 Electron 内置 Chromium 支持 WebGL 2.0）
      alert('WebGL 2.0 not supported');
      return;
    }

    // 初始化灵动岛
    this.island = new IslandController();

    // 初始化后端桥接
    this.bridge = new BackendBridge(
      (state) => this._onBackendState(state),
      (status) => this._onBackendStatus(status)
    );
    this.bridge.connect();

    // 监听 IPC 事件
    this._setupIPC();

    // 监听 resize
    window.addEventListener('resize', () => this._onResize());

    // 启动渲染循环
    this.running = true;
    this.lastTime = performance.now();
    this.rafId = requestAnimationFrame((t) => this._renderLoop(t));

    console.log('[Lumiv] App initialized');
  }

  // ── DPI 自适应 ──────────────────────────────────

  _setupDPI() {
    const dpr = window.devicePixelRatio || 1;
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.canvas.width = Math.round(w * dpr);
    this.canvas.height = Math.round(h * dpr);
    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
  }

  _onResize() {
    this._setupDPI();
    if (this.webgl) {
      this.webgl.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    }
  }

  // ── IPC 监听 ────────────────────────────────────

  _setupIPC() {
    // 显示器变化
    if (window.lumivAPI?.onDisplayChanged) {
      window.lumivAPI.onDisplayChanged((info) => {
        this.canvas.width = Math.round(info.width * info.scaleFactor);
        this.canvas.height = Math.round(info.height * info.scaleFactor);
      });
    }

    // 开发调试
    if (window.lumivAPI?.onDevTogglePhase) {
      window.lumivAPI.onDevTogglePhase(() => {
        this._devTogglePhase();
      });
    }

    // 后端状态推送（备用通道）
    if (window.lumivAPI?.onBackendState) {
      window.lumivAPI.onBackendState((state) => this._onBackendState(state));
    }

    // 后端连接状态
    if (window.lumivAPI?.onBackendStatus) {
      window.lumivAPI.onBackendStatus((status) => this._onBackendStatus(status));
    }
  }

  // ── 后端状态处理 ────────────────────────────────

  _onBackendState(state) {
    // 直接更新后端状态
    if (state.phase !== undefined) this.backendState.phase = state.phase;
    if (state.intent !== undefined) this.backendState.intent = state.intent;
    if (state.speaking !== undefined) this.backendState.speaking = state.speaking;
    if (state.activeTask !== undefined) this.backendState.activeTask = state.activeTask;
    if (state.taskProgress !== undefined) this.backendState.taskProgress = state.taskProgress;
  }

  _onBackendStatus(status) {
    if (status.connected) {
      this.bridge.simulateMode = false;
    } else {
      this.bridge.enableSimulation();
    }
  }

  // ── Spring 物理（与 Canvas 2D 版本 1:1） ───────

  _springUpdate(dt) {
    const intentBoost = 1.0 + this.backendState.intent * 1.5;
    const tension = this.currentDepth < this.targetDepth ? 50 * intentBoost : 70;
    const friction = 14;
    const force = -tension * (this.currentDepth - this.targetDepth);
    const damping = -friction * this.springV;
    this.springV += (force + damping) * dt;
    this.currentDepth += this.springV * dt;
    this.currentDepth = Math.max(0, Math.min(1, this.currentDepth));
  }

  // ── 模拟后端 AI（降级模式，与 Canvas 2D 版本 1:1） ──

  _simulateBackendAI(dt) {
    this.stateTimer += dt;

    switch (this.backendState.phase) {
      case 'silent':
        if (this.stateTimer > 3 + Math.sin(this.time * 0.3) * 2) {
          this.backendState.phase = 'liminal';
          this.backendState.intent = 0.1;
          this.stateTimer = 0;
        }
        break;

      case 'liminal':
        if (this.backendState.intent < 0.9) {
          this.backendState.intent += dt * 0.25;
        }
        this.backendState.speaking = Math.sin(this.time * 2.5) > 0.2;
        if (this.backendState.intent >= 0.85 && this.stateTimer > 4) {
          this.backendState.phase = 'manifest';
          this.backendState.activeTask = '整理桌面文件';
          this.backendState.taskProgress = 0;
          this.backendState.intent = 1.0;
          this.stateTimer = 0;
        }
        break;

      case 'manifest':
        this.backendState.speaking = false;
        this.backendState.taskProgress += dt * 0.15;
        if (this.backendState.taskProgress >= 1.0) {
          this.backendState.phase = 'silent';
          this.backendState.intent = 0;
          this.backendState.activeTask = null;
          this.backendState.taskProgress = 0;
          this.stateTimer = 0;
        }
        break;
    }

    // 根据 phase 设置目标深度
    if (this.backendState.phase === 'silent') this.targetDepth = 0.05;
    else if (this.backendState.phase === 'liminal') {
      this.targetDepth = 0.15 + this.backendState.intent * 0.30;
    } else if (this.backendState.phase === 'manifest') {
      this.targetDepth = 0.90;
    }
  }

  // ── 渲染循环 ────────────────────────────────────

  _renderLoop(now) {
    if (!this.running) return;

    const dt = Math.min((now - this.lastTime) / 1000, 0.05);
    this.lastTime = now;
    this.time += dt;

    // 如果没有真实后端，启用模拟
    if (this.bridge?.isSimulating?.() || !this.bridge?.connected) {
      this._simulateBackendAI(dt);
    }

    // Spring 物理
    this._springUpdate(dt);

    // 三态权重
    const silentW = Math.max(0, 1 - this.currentDepth / 0.30);
    const liminalW = Math.max(0, Math.min(1, (this.currentDepth - 0.15) / 0.40) * Math.min(1, (0.95 - this.currentDepth) / 0.35));

    // 更新 WebGL Uniforms
    const dpr = window.devicePixelRatio || 1;
    this.webgl.setUniform('u_time', this.time);
    this.webgl.setUniform('u_resolution', [this.canvas.width, this.canvas.height]);
    this.webgl.setUniform('u_depth', this.currentDepth);
    this.webgl.setUniform('u_intent', this.backendState.intent);
    this.webgl.setUniform('u_speaking', this.backendState.speaking ? 1.0 : 0.0);

    // 渲染
    this.webgl.render();

    // 更新灵动岛
    this.island.update(this.currentDepth, this.backendState);

    // 状态显示（开发模式）
    const pn = this.currentDepth < 0.25 ? '呼吸' : this.currentDepth < 0.75 ? '空间' : '执行';
    const intentStr = (this.backendState.intent * 100).toFixed(0);
    this.depthEl.textContent = `${this.currentDepth.toFixed(2)} · ${pn} · 意图${intentStr}%`;

    this.rafId = requestAnimationFrame((t) => this._renderLoop(t));
  }

  // ── 开发工具 ────────────────────────────────────

  _devTogglePhase() {
    const phases = ['silent', 'liminal', 'manifest'];
    const idx = phases.indexOf(this.backendState.phase);
    this.backendState.phase = phases[(idx + 1) % 3];
    this.stateTimer = 0;
    console.log('[Lumiv] Dev: phase →', this.backendState.phase);
  }

  // ── 销毁 ────────────────────────────────────────

  destroy() {
    this.running = false;
    if (this.rafId) cancelAnimationFrame(this.rafId);
    if (this.bridge) this.bridge.disconnect();
    if (this.webgl) this.webgl.destroy();
  }
}

// ── 启动 ──────────────────────────────────────────

window.addEventListener('DOMContentLoaded', () => {
  window.lumivApp = new LumivApp();
  window.lumivApp.init();
});

window.addEventListener('beforeunload', () => {
  if (window.lumivApp) window.lumivApp.destroy();
});

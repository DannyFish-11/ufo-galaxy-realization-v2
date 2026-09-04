const { contextBridge, ipcRenderer } = require('electron');

// PR-IPC: Electron IPC 桥接 — Python 后端 → main.js → preload → 前端
// 替代 WebSocket，内存级通信，无端口占用
contextBridge.exposeInMainWorld('galaxyAPI', {
  // ── 三态状态接收（主窗口）─
  onBackendState: (callback) => {
    const handler = (_, data) => callback(data);
    ipcRenderer.on('presence-state', handler);
    return () => ipcRenderer.removeListener('presence-state', handler);
  },

  // ── Panel 数据获取 ─
  // 统一网关端口（默认 9000），与 main.js / useWebSocket.ts 保持一致。
  // 此前硬编码 8000，与实际后端端口不符，导致回退连接打不通。
  getBackendUrl: () => ipcRenderer.invoke('galaxy:get-backend-url'),
  getBackendStatus: () => ipcRenderer.invoke('galaxy:get-backend-status'),
  startBackend: () => ipcRenderer.invoke('galaxy:start-backend'),
  getRuntimeStatus: () => ipcRenderer.invoke('galaxy:get-runtime-status'),
  testRuntime: (runtime) => ipcRenderer.invoke('galaxy:test-runtime', runtime),
  saveRuntime: (runtime) => ipcRenderer.invoke('galaxy:save-runtime', runtime),

  // ── 窗口控制 ─
  getWindowSize: () => ipcRenderer.invoke('get-window-size'),
  setIgnoreMouse: (ignore) => ipcRenderer.send('set-ignore-mouse', ignore),

  // ── 桌面连续感知（摄像头/麦克风/屏幕）─
  // 配置（默认关闭，隐私优先）由 main.js 经环境变量决定。
  getPerceptionConfig: () => ipcRenderer.invoke('galaxy:perception-config'),
  // 渲染层采到的帧/音频片段 → main.js → 转发到网关 /api/perception/desktop/*
  sendDesktopPerception: (payload) => ipcRenderer.send('galaxy:desktop-perception', payload),

  // ── 工具 ─
  platform: process.platform,

  // -- 配置管理 --
  // getConfig/setConfig：精简版(模型 tab)—— status/configured/values,不含密钥明文。
  getConfig: () => ipcRenderer.invoke('galaxy:get-config'),
  setConfig: (config) => ipcRenderer.invoke('galaxy:set-config', config),
  // 渲染层保存超时死线的真源在主进程(见 electron/main.js 的
  // CONFIG_FETCH_BUDGET_MS 等常量)，这里现查而不是渲染层自己另维护一份数字。
  getConfigSaveTimeoutMs: () => ipcRenderer.invoke('galaxy:get-config-save-timeout-ms'),
  // getSettings：完整明细(设置 tab)—— 105 项配置的 value/default/type/category/description。
  // 与 getConfig 分开路径,避免后端路由遮蔽导致设置 tab 拿不到任何一项内容。
  getSettings: () => ipcRenderer.invoke('galaxy:get-settings'),
  onConfigUpdate: (callback) => {
    const handler = (_, data) => callback(data);
    ipcRenderer.on('galaxy:config-update', handler);
    return () => ipcRenderer.removeListener('galaxy:config-update', handler);
  },
  // 后端从"未就绪"变为"就绪"是异步的:getConfig/getSettings 立即返回当前
  // 缓存(可能是空的),真正的网络请求在 main.js 后台进行,拿到结果后广播
  // 'galaxy:config-ready'(kind: 'config'|'settings')。渲染层收到后自行
  // invalidate() 重新取一次即可,不需要用户手动切走再切回来。
  onConfigReady: (callback) => {
    const handler = (_, kind) => callback(kind);
    ipcRenderer.on('galaxy:config-ready', handler);
    return () => ipcRenderer.removeListener('galaxy:config-ready', handler);
  },
  saveConfig: () => ipcRenderer.invoke('galaxy:save-config'),
});

// ── 外壳告诉面板:后端在哪 ──
//
// 面板(electron/renderer/panel)是**外壳无关的**:它不 import electron,
// 也不假设自己跑在 Electron 里。它按这个顺序找后端地址:
//   1. window.galaxyShell.base —— 外壳给的(就是这里)
//   2. <meta name="galaxy-base"> —— 浏览器里开发时用
//   3. 同源
//
// file:// 下"同源"没有意义,所以 Electron 这条路必须给出真实地址,否则
// WebSocket 会去连一个不存在的东西然后一直退避重试 —— 界面上就是
// 「连接指示一直是断的」,而没有任何报错说得清为什么。
const _baseArg = process.argv.find((a) => a.startsWith('--galaxy-base='));
contextBridge.exposeInMainWorld('galaxyShell', {
  base: _baseArg ? _baseArg.slice('--galaxy-base='.length) : '',
  name: 'electron',
});

console.log('[Preload] galaxyAPI IPC bridge ready');

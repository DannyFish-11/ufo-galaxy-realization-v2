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
  getBackendUrl: () => {
    const port = process.env.GALAXY_GATEWAY_PORT || process.env.PORT || '9000';
    return Promise.resolve(`http://localhost:${port}`);
  },

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
  getConfig: () => ipcRenderer.invoke('galaxy:get-config'),
  setConfig: (config) => ipcRenderer.invoke('galaxy:set-config', config),
  onConfigUpdate: (callback) => {
    const handler = (_, data) => callback(data);
    ipcRenderer.on('galaxy:config-update', handler);
    return () => ipcRenderer.removeListener('galaxy:config-update', handler);
  },
  saveConfig: () => ipcRenderer.invoke('galaxy:save-config'),
});

console.log('[Preload] galaxyAPI IPC bridge ready');

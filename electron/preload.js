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
  getBackendUrl: () => Promise.resolve('http://localhost:8000'),

  // ── 窗口控制 ─
  getWindowSize: () => ipcRenderer.invoke('get-window-size'),
  setIgnoreMouse: (ignore) => ipcRenderer.send('set-ignore-mouse', ignore),

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

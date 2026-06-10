const { contextBridge, ipcRenderer } = require('electron');

// PR-IPC: Electron IPC 桥接 — Python 后端 → main.js → preload → 前端
// 替代 WebSocket，内存级通信，无端口占用
contextBridge.exposeInMainWorld('galaxyAPI', {
  // ── 三态状态接收（主窗口）─
  onBackendState: (callback) => {
    ipcRenderer.on('presence-state', (event, payload) => callback(payload));
  },

  // ── Panel 数据获取 ─
  getBackendUrl: () => Promise.resolve('http://localhost:8000'),

  // ── 窗口控制 ─
  getWindowSize: () => ipcRenderer.invoke('get-window-size'),
  setIgnoreMouse: (ignore) => ipcRenderer.send('set-ignore-mouse', ignore),

  // ── 工具 ─
  platform: process.platform,
});

console.log('[Preload] galaxyAPI IPC bridge ready');

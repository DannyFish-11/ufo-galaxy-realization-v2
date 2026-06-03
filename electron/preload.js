const { contextBridge, ipcRenderer } = require('electron');

// P1+P14 修复：本地加载 Three.js，避免 CDN 依赖
// 添加 try-catch，如果 require 失败则 THREE 为 undefined（renderer 会 graceful degradation）
let THREE = null;
try {
    THREE = require('three');
    console.log('[Preload] Three.js 本地加载成功');
} catch (err) {
    console.warn('[Preload] Three.js 本地加载失败 — Silent 态将以 CSS 降级模式运行:', err.message);
}

contextBridge.exposeInMainWorld('electronAPI', {
    getWindowSize: () => ipcRenderer.invoke('get-window-size'),
    onWindowResize: (callback) => ipcRenderer.on('window-resize', (_, size) => callback(size)),
    setIgnoreMouse: (ignore) => ipcRenderer.send('set-ignore-mouse', ignore),
    removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel)
});

// 暴露 THREE 到全局（如果加载成功）
contextBridge.exposeInMainWorld('THREE', THREE);

const { contextBridge, ipcRenderer } = require('electron');

// 本地加载 Three.js，避免 CDN 依赖
const THREE = require('three');

contextBridge.exposeInMainWorld('electronAPI', {
    getWindowSize: () => ipcRenderer.invoke('get-window-size'),
    onWindowResize: (callback) => ipcRenderer.on('window-resize', (_, size) => callback(size)),
    setIgnoreMouse: (ignore) => ipcRenderer.send('set-ignore-mouse', ignore),
    removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel)
});

// 暴露 THREE 到全局，供 renderer 使用
contextBridge.exposeInMainWorld('THREE', THREE);

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('electronAPI', {
    getWindowSize: () => ipcRenderer.invoke('get-window-size'),
    onWindowResize: (callback) => ipcRenderer.on('window-resize', (_, size) => callback(size)),
    setIgnoreMouse: (ignore) => ipcRenderer.send('set-ignore-mouse', ignore),
    removeAllListeners: (channel) => ipcRenderer.removeAllListeners(channel)
});

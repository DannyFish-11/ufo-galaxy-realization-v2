const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
const path = require('path');

// PR-IPC: HTTP 接收端 — Python 后端推送到此端点，转发到前端 IPC
const IPC_HTTP_PORT = 9229;
let ipcHttpServer = null;

// ── Two-window architecture ──
// mainWindow  : Three-State Full-Screen AI (always on, never hidden)
// panelWindow : AI Control Panel — Colorless Lens (toggled by F12)
let mainWindow = null;
let panelWindow = null;
let isPanelVisible = false;

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1920,
        height: 1080,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        fullscreen: true,
        skipTaskbar: true,
        hasShadow: false,
        resizable: false,
        movable: false,
        closable: true,
        focusable: true,
        show: false,
        backgroundColor: '#00000000',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            webSecurity: true,
            allowRunningInsecureContent: false,
            experimentalFeatures: false
        }
    });

    mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));

    mainWindow.once('ready-to-show', () => {
        mainWindow.show();
        mainWindow.setIgnoreMouseEvents(true, { forward: true });
    });

    mainWindow.on('closed', () => {
        mainWindow = null;
    });

    mainWindow.on('resize', () => {
        if (mainWindow) {
            const [w, h] = mainWindow.getSize();
            mainWindow.webContents.send('window-resize', { width: w, height: h });
        }
    });

    return mainWindow;
}

app.whenReady().then(() => {
    createWindow();

    // ── IPC HTTP 接收端 ──
    // Python 后端 POST /ipc/presence-state → 转发到前端 via ipcMain
    try {
        const http = require('http');
        ipcHttpServer = http.createServer((req, res) => {
            if (req.method === 'POST' && req.url === '/ipc/presence-state') {
                let body = '';
                req.on('data', chunk => body += chunk);
                req.on('end', () => {
                    try {
                        const data = JSON.parse(body);
                        const payload = data.payload || data;
                        // 转发到主窗口
                        if (mainWindow && !mainWindow.isDestroyed()) {
                            mainWindow.webContents.send('presence-state', payload);
                        }
                        // 转发到 Panel 窗口
                        if (panelWindow && !panelWindow.isDestroyed()) {
                            panelWindow.webContents.send('presence-state', payload);
                        }
                        res.writeHead(200, { 'Content-Type': 'application/json' });
                        res.end(JSON.stringify({ success: true, via: 'ipc' }));
                    } catch (e) {
                        res.writeHead(400);
                        res.end('{"error": "invalid json"}');
                    }
                });
            } else {
                res.writeHead(404);
                res.end('{"error": "not found"}');
            }
        });
        ipcHttpServer.listen(IPC_HTTP_PORT, '127.0.0.1', () => {
            console.log(`[IPC] HTTP receiver on localhost:${IPC_HTTP_PORT}`);
        });
    } catch (err) {
        console.warn('[IPC] Failed to start HTTP receiver:', err);
    }

    // PR-D5: Start system tray alongside Electron GUI
    // P22 修复：根据平台选择 python/python3，避免硬编码
    try {
        const { spawn } = require('child_process');
        const pythonCmd = process.platform === 'win32' ? 'python' : 'python3';
        const trayProcess = spawn(pythonCmd, ['-m', 'windows_service.tray_icon'], {
            cwd: path.join(__dirname, '..'),
            detached: true,
            stdio: 'ignore'
        });
        trayProcess.unref();
        console.log('System tray started');
    } catch (err) {
        console.warn('Failed to start system tray:', err);
    }

    // F12: Toggle AI Control Panel (Colorless Lens)
    // P21 修复：检查快捷键注册是否成功
    const f12Registered = globalShortcut.register('F12', () => {
        togglePanel();
    });
    if (!f12Registered) {
        console.warn('[Main] F12 快捷键注册失败，可能已被系统或其他应用占用');
    }

    app.on('browser-window-created', (event, window) => {
        if (mainWindow) {
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
        }
    });
});

// ═══════════════════════════════════════════
// AI Control Panel — Colorless Lens
// ═══════════════════════════════════════════

function createPanelWindow() {
    const fs = require('fs');
    const panelPath = path.join(__dirname, 'renderer', 'panel', 'index.html');
    if (!fs.existsSync(panelPath)) {
        console.log('[Panel] renderer/panel/index.html not found');
        return null;
    }

    if (panelWindow) return panelWindow;

    panelWindow = new BrowserWindow({
        width: 1200,
        height: 700,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        fullscreen: false,
        skipTaskbar: false,
        hasShadow: true,
        resizable: true,
        movable: true,
        closable: true,
        focusable: true,
        show: false,
        backgroundColor: '#00000000',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            webSecurity: true,
        }
    });

    panelWindow.loadFile(panelPath);

    panelWindow.on('closed', () => {
        panelWindow = null;
        isPanelVisible = false;
    });

    return panelWindow;
}

function togglePanel() {
    if (!panelWindow) {
        createPanelWindow();
    }
    if (!panelWindow) return;

    if (isPanelVisible) {
        panelWindow.hide();
        isPanelVisible = false;
        console.log('[Panel] Hidden (F12)');
    } else {
        panelWindow.show();
        panelWindow.focus();
        isPanelVisible = true;
        console.log('[Panel] Shown (F12)');
    }
}

app.on('window-all-closed', () => {
    app.quit();
});

app.on('will-quit', () => {
    // 关闭 IPC HTTP 服务器
    if (ipcHttpServer) {
        ipcHttpServer.close();
        console.log('[IPC] HTTP receiver stopped');
    }
    globalShortcut.unregisterAll();
});

app.on('activate', () => {
    if (mainWindow === null) {
        createWindow();
    }
});

// IPC handlers
ipcMain.handle('get-window-size', () => {
    if (mainWindow) {
        const [w, h] = mainWindow.getSize();
        return { width: w, height: h };
    }
    return { width: 1920, height: 1080 };
});

ipcMain.on('set-ignore-mouse', (event, ignore) => {
    if (mainWindow) {
        mainWindow.setIgnoreMouseEvents(ignore, { forward: true });
    }
});

const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
const path = require('path');

// PR-IPC: HTTP 接收端 — Python 后端推送到此端点，转发到前端 IPC
// 注意：9229 是 Node/V8 inspector 的默认端口（--inspect），会与调试器或
// 第二个实例冲突，导致 listen EADDRINUSE 崩溃主进程。改用独立端口，
// 并通过环境变量与 Python 端 (core/lumiv_websocket_bridge.py) 保持一致。
const IPC_HTTP_PORT = parseInt(process.env.GALAXY_IPC_PORT || '9231', 10);
// 配置 API 由统一网关 (unified_launcher / core.routes) 提供，监听 PORT(默认 9000)，
// 而非本进程的 IPC 接收端。此前误指向 9229 导致配置读写永远 404。
const GATEWAY_PORT = parseInt(process.env.GALAXY_GATEWAY_PORT || process.env.PORT || '9000', 10);
const GATEWAY_BASE = `http://localhost:${GATEWAY_PORT}`;
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
        // listen 的错误是异步 'error' 事件，try/catch 捕获不到。
        // 缺少该处理器时，EADDRINUSE（端口被占用 / 已有实例 / inspector）
        // 会变成未捕获异常，直接弹出 "A JavaScript error occurred in the
        // main process" 并杀死主进程 —— 导致桌面覆盖层（唤醒）和 F12 面板
        // 全部失效。这里降级为告警，IPC 接收端不可用不影响窗口与快捷键。
        ipcHttpServer.on('error', (err) => {
            if (err && err.code === 'EADDRINUSE') {
                console.warn(`[IPC] Port ${IPC_HTTP_PORT} already in use — presence push disabled. ` +
                    `Set GALAXY_IPC_PORT to use a different port. App continues running.`);
            } else {
                console.warn('[IPC] HTTP receiver error:', err);
            }
            ipcHttpServer = null;
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
    if (panelWindow && !panelWindow.isDestroyed()) {
        if (panelWindow.isVisible()) {
            panelWindow.hide();
            isPanelVisible = false;
            console.log('[Panel] Hidden (F12)');
        } else {
            panelWindow.show();
            panelWindow.focus();
            isPanelVisible = true;
            console.log('[Panel] Shown (F12)');
        }
        return;
    }

    // 创建 Panel 窗口（复用 createPanelWindow）
    const win = createPanelWindow();
    if (win) {
        win.show();
        win.focus();
        isPanelVisible = true;
        console.log('[Panel] Created & Shown (F12)');
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

// ═══════════════════════════════════════════
// Configuration Management — Python Backend
// ═══════════════════════════════════════════

// 内存中的配置缓存
let configCache = {};

// 从 Python 后端获取配置
async function fetchConfigFromBackend() {
    try {
        const response = await fetch(`${GATEWAY_BASE}/api/config`);
        if (response.ok) {
            configCache = await response.json();
            return configCache;
        }
    } catch (e) {
        console.error('[Main] Failed to fetch config:', e.message);
    }
    return configCache;
}

// GET 配置
ipcMain.handle('galaxy:get-config', async () => {
    return await fetchConfigFromBackend();
});

// SET 配置（批量更新）
ipcMain.handle('galaxy:set-config', async (_, config) => {
    try {
        const response = await fetch(`${GATEWAY_BASE}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config),
        });
        if (response.ok) {
            configCache = { ...configCache, ...config };
            // 广播到所有窗口
            BrowserWindow.getAllWindows().forEach(w => {
                w.webContents.send('galaxy:config-update', configCache);
            });
            return { success: true };
        }
        return { success: false, error: 'Backend rejected config' };
    } catch (e) {
        console.error('[Main] Failed to set config:', e.message);
        return { success: false, error: e.message };
    }
});

// 保存配置到文件
ipcMain.handle('galaxy:save-config', async () => {
    try {
        const response = await fetch(`${GATEWAY_BASE}/api/config/save`, {
            method: 'POST',
        });
        return { success: response.ok };
    } catch (e) {
        return { success: false, error: e.message };
    }
});

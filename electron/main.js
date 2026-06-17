const { app, BrowserWindow, globalShortcut, ipcMain, dialog } = require('electron');
const path = require('path');

// 应用图标：Windows 用多尺寸 .ico（任务栏/窗口才正确显示），其余平台用 .png。
const ICON_PATH = path.join(
    __dirname, 'assets', process.platform === 'win32' ? 'icon.ico' : 'icon.png'
);
// Windows 任务栏图标身份：未设置 AppUserModelId 时，从源码运行的 Electron 会沿用
// electron.exe 的默认原子图标（用户看到「图标没显示/很怪」）。显式设置后任务栏才
// 关联到本应用并显示自定义图标。
if (process.platform === 'win32') {
    app.setAppUserModelId('ai.galaxy.desktop');
}

// ── 单实例锁 ──
// 端口 EADDRINUSE 崩溃最常见的根因就是"已有一个实例在跑"。单实例锁从源头
// 杜绝第二个进程争抢 IPC 端口；后来者直接退出，并唤起已存在的窗口。
const gotSingleInstanceLock = app.requestSingleInstanceLock();
if (!gotSingleInstanceLock) {
    console.warn('[Main] 已有 Galaxy 桌面实例在运行，本实例退出。');
    app.quit();
} else {
    app.on('second-instance', () => {
        // 第二个实例被拉起时，把已有主窗口带到前台
        if (mainWindow && !mainWindow.isDestroyed()) {
            if (mainWindow.isMinimized()) mainWindow.restore();
            mainWindow.show();
            mainWindow.focus();
        }
    });
}

// ── 主进程兜底 ──
// 任何未捕获异常都记录而不是直接弹出系统级崩溃框并杀进程。覆盖层与快捷键
// 应当尽可能保持存活，宁可某个子功能降级也不要整个外壳消失。
process.on('uncaughtException', (err) => {
    console.error('[Main] Uncaught exception (kept alive):', err);
});
process.on('unhandledRejection', (reason) => {
    console.error('[Main] Unhandled promise rejection (kept alive):', reason);
});

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

// 桌面连续感知（摄像头/麦克风/屏幕）配置 —— 默认关闭（隐私优先）。
// 仅当 GALAXY_DESKTOP_PERCEPTION=1 时才在渲染层启动采集。
const PERCEPTION_ENABLED = ['1', 'true', 'yes', 'on'].includes(
    String(process.env.GALAXY_DESKTOP_PERCEPTION || '').trim().toLowerCase()
);
const PERCEPTION_INTERVAL_MS = parseInt(process.env.GALAXY_DESKTOP_PERCEPTION_INTERVAL_MS || '2000', 10);

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
        icon: ICON_PATH,
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
    // 未取得单实例锁的后来者：什么都不做，等待 app.quit() 收尾，
    // 避免它创建窗口或去争抢已被占用的 IPC 端口。
    if (!gotSingleInstanceLock) return;

    // 媒体权限：Electron 默认拒绝 getUserMedia。仅当桌面感知启用时放行
    // 摄像头/麦克风/屏幕权限；否则一律拒绝（隐私优先）。
    try {
        const { session } = require('electron');
        session.defaultSession.setPermissionRequestHandler((wc, permission, callback) => {
            const mediaPerms = ['media', 'audioCapture', 'videoCapture', 'display-capture'];
            if (PERCEPTION_ENABLED && mediaPerms.includes(permission)) {
                return callback(true);
            }
            return callback(false);
        });
    } catch (e) {
        console.warn('[Main] 设置媒体权限处理器失败:', e && e.message);
    }

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

    // Toggle AI Control Panel (Colorless Lens)
    // F12 在很多环境会被开发者工具/输入法/其他应用占用，因此注册一组候选
    // 快捷键：任意一个成功即可开关面板，避免"按了没反应"。
    const PANEL_SHORTCUTS = ['F12', 'CommandOrControl+F12', 'CommandOrControl+Shift+P'];
    const registeredShortcuts = PANEL_SHORTCUTS.filter((accel) => {
        try {
            return globalShortcut.register(accel, () => togglePanel());
        } catch (e) {
            return false;
        }
    });
    if (registeredShortcuts.length === 0) {
        // 一个都没注册上：给出可见反馈，而不是只在控制台里 warn。
        console.warn('[Main] 面板快捷键全部注册失败，可能被系统或其他应用占用');
        try {
            dialog.showMessageBox(mainWindow, {
                type: 'warning',
                title: 'Galaxy 控制面板',
                message: '面板快捷键注册失败',
                detail: `尝试过：${PANEL_SHORTCUTS.join(' / ')}。\n` +
                    '可能被系统或其他应用占用。可关闭占用 F12 的程序后重启，或通过托盘菜单打开面板。',
            });
        } catch (e) { /* 无窗口时忽略 */ }
    } else {
        console.log(`[Main] 面板快捷键已注册: ${registeredShortcuts.join(', ')}`);
    }

    app.on('browser-window-created', (event, window) => {
        if (mainWindow) {
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
        }
    });

    // ── 面板真实数据轮询 ──
    // 控制面板的数据契约(usePanelData)走 IPC 'presence-state'。这里定期从网关拉取
    // 真实聚合数据 /api/v1/panel/feed(MCP/Skills/OpenClawd/LLM路由/统一记忆)并推给
    // 面板窗口 —— 无需重建前端 bundle，面板即显示真实状态而非写死的占位数据。
    setInterval(async () => {
        if (!panelWindow || panelWindow.isDestroyed() || !panelWindow.isVisible()) return;
        try {
            const resp = await fetch(`${GATEWAY_BASE}/api/v1/panel/feed`);
            if (!resp.ok) return;
            const data = await resp.json();
            const feed = data && data.feed;
            if (feed && Object.keys(feed).length) {
                panelWindow.webContents.send('presence-state', feed);
            }
        } catch (e) { /* 网关未就绪等，静默重试下一轮 */ }
    }, 5000);
});

// ═══════════════════════════════════════════
// AI Control Panel — Colorless Lens
// ═══════════════════════════════════════════

function createPanelWindow() {
    const fs = require('fs');
    // 优先加载 Vite 构建产物 (dist/)。renderer/panel/index.html 现在是构建
    // 入口（指向 src/main.tsx），不能直接被浏览器/Electron 当页面加载。
    const distPath = path.join(__dirname, 'renderer', 'panel', 'dist', 'index.html');
    const legacyPath = path.join(__dirname, 'renderer', 'panel', 'index.html');
    const panelPath = fs.existsSync(distPath) ? distPath : legacyPath;
    if (!fs.existsSync(panelPath)) {
        console.log('[Panel] panel build not found — run: cd electron/renderer/panel && npm install && npm run build');
        return null;
    }

    if (panelWindow) return panelWindow;

    panelWindow = new BrowserWindow({
        width: 1200,
        height: 700,
        icon: ICON_PATH,
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
// Desktop Perception — 摄像头/麦克风/屏幕连续感知
// ═══════════════════════════════════════════

// 渲染层询问是否启用 + 采集参数
ipcMain.handle('galaxy:perception-config', () => ({
    enabled: PERCEPTION_ENABLED,
    intervalMs: PERCEPTION_INTERVAL_MS,
    video: true,
    audio: true,
}));

// 渲染层采到的帧/音频 → 转发到网关的桌面感知接收端
ipcMain.on('galaxy:desktop-perception', async (_event, payload) => {
    if (!PERCEPTION_ENABLED || !payload) return;
    try {
        if (payload.type === 'frame' && payload.image_base64) {
            await fetch(`${GATEWAY_BASE}/api/perception/desktop/frame`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    image_base64: payload.image_base64,
                    mime: payload.mime || 'image/jpeg',
                    source: payload.source || 'desktop_camera',
                }),
            });
        } else if (payload.type === 'audio' && payload.audio_base64) {
            await fetch(`${GATEWAY_BASE}/api/perception/desktop/audio`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    audio_base64: payload.audio_base64,
                    mime: payload.mime || 'audio/webm',
                }),
            });
        }
    } catch (e) {
        // 后端未就绪/网络抖动等非致命；丢弃本帧即可
        console.debug('[Perception] forward failed:', e && e.message);
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

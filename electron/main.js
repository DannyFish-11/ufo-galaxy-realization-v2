const { app, BrowserWindow, globalShortcut, ipcMain, dialog, screen } = require('electron');
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

// ── 透明全屏覆盖层稳定性（GPU 自适应）──
// mainWindow 是 transparent + fullscreen + alwaysOnTop + WebGL(three.js) 覆盖层。
// 在部分 Windows GPU/驱动（尤其笔记本双显卡/混合输出）上，透明窗口 + GPU 合成会让
// GPU 进程崩溃 → 窗口关闭 → window-all-closed → app.quit() → 闪退循环。
// 策略：默认【开启】硬件加速（有独显的机器走 GPU、更流畅）；只有当启动器在检测到
// GPU 模式反复崩溃后注入 GALAXY_ELECTRON_GPU=0 时，才禁用硬件加速（软件渲染兜底）。
// 这样按机器实际情况自适应，无需用户手动判断有没有 GPU。
if (['0', 'false', 'no', 'off'].includes(
        String(process.env.GALAXY_ELECTRON_GPU || '').trim().toLowerCase())) {
    try {
        app.disableHardwareAcceleration();
        console.error('[Main] 硬件加速已禁用（软件渲染模式，GALAXY_ELECTRON_GPU=0）');
    } catch (_e) { /* older electron may not support; non-fatal */ }
}

// ── GPU / 渲染进程崩溃诊断 ──
// 把崩溃原因打到 stdout（→ logs/electron.log），便于定位「闪退循环」根因。
app.on('gpu-process-gone', (_e, details) => {
    console.error('[Main] gpu-process-gone:', JSON.stringify(details));
});
app.on('child-process-gone', (_e, details) => {
    console.error('[Main] child-process-gone:', JSON.stringify(details));
});
app.on('render-process-gone', (_e, _wc, details) => {
    console.error('[Main] render-process-gone:', JSON.stringify(details));
});

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

// 桌面连续感知（摄像头/麦克风/屏幕）。
// 隐私处理：首次启动弹一次「授权」对话框；授权后持久化记住，之后每次启动自动开启，
// 省得手动设环境变量。可用 GALAXY_DESKTOP_PERCEPTION=1/0 强制覆盖（跳过询问）。
const PERCEPTION_INTERVAL_MS = parseInt(process.env.GALAXY_DESKTOP_PERCEPTION_INTERVAL_MS || '2000', 10);
let perceptionEnabled = false;   // 运行期最终状态，由 env 覆盖或持久化授权决定

function _perceptionConsentFile() {
    try {
        return path.join(app.getPath('userData'), 'perception_consent.json');
    } catch (e) {
        return null;
    }
}
function _readPerceptionConsent() {
    try {
        const fs = require('fs');
        const f = _perceptionConsentFile();
        if (f && fs.existsSync(f)) return JSON.parse(fs.readFileSync(f, 'utf-8'));
    } catch (e) { /* ignore */ }
    return null;
}
function _writePerceptionConsent(granted) {
    try {
        const fs = require('fs');
        const f = _perceptionConsentFile();
        if (f) fs.writeFileSync(f, JSON.stringify({ granted: !!granted, ts: Date.now() }), 'utf-8');
    } catch (e) { /* ignore */ }
}
// 解析最终的感知开关：env 强制 > 已持久化授权 > 首次弹框询问。
async function resolvePerceptionConsent() {
    const env = String(process.env.GALAXY_DESKTOP_PERCEPTION || '').trim().toLowerCase();
    if (['1', 'true', 'yes', 'on'].includes(env)) { perceptionEnabled = true; return; }
    if (['0', 'false', 'no', 'off'].includes(env)) { perceptionEnabled = false; return; }
    const saved = _readPerceptionConsent();
    if (saved && typeof saved.granted === 'boolean') { perceptionEnabled = saved.granted; return; }
    // 首次：弹一次授权框
    try {
        const { response } = await dialog.showMessageBox({
            type: 'question',
            buttons: ['授权', '暂不'],
            defaultId: 0,
            cancelId: 1,
            title: 'Galaxy 多模态感知授权',
            message: '允许 Galaxy 使用摄像头、麦克风与屏幕画面？',
            detail: '授权后，Galaxy 在第一态(待机)会连续原生采集【摄像头+麦克风+屏幕】，由本地多模态模型(Gemma4 / MiniCPM-o)一体化理解，' +
                '提供更自然的在场助理体验。\n采集仅在本机处理；可随时在设置中关闭。\n（系统稍后还会再弹一次摄像头/麦克风权限，请一并允许。）',
        });
        perceptionEnabled = (response === 0);
        _writePerceptionConsent(perceptionEnabled);
    } catch (e) {
        perceptionEnabled = false;
    }
}

// ── Two-window architecture ──
// mainWindow  : Three-State Full-Screen AI (always on, never hidden)
// panelWindow : AI Control Panel — Colorless Lens (toggled by F12)
let mainWindow = null;
let panelWindow = null;
let isPanelVisible = false;

function createWindow() {
    // ── 覆盖层尺寸：用主显示器实际 bounds，而非 fullscreen:true ──
    // 关键修复（「唤不起来/打不开」根因之一）：在 Windows 上 transparent:true 与
    // fullscreen:true 同时开启极易出问题——尤其笔记本双显卡/混合输出，OS 独占全屏与
    // 透明合成冲突，窗口经常【全黑】或【根本不显示】。改成「无边框 + 覆盖整块屏幕 bounds」
    // 的覆盖层（视觉上等同全屏，但不触发 OS 独占全屏），是透明置顶覆盖层的稳健做法。
    let bounds = { x: 0, y: 0, width: 1920, height: 1080 };
    try {
        bounds = screen.getPrimaryDisplay().bounds;
    } catch (e) { /* app 未就绪时兜底；createWindow 实际在 whenReady 后调用 */ }

    mainWindow = new BrowserWindow({
        x: bounds.x,
        y: bounds.y,
        width: bounds.width,
        height: bounds.height,
        icon: ICON_PATH,
        frame: false,
        transparent: true,
        alwaysOnTop: true,
        fullscreen: false,          // 见上：不用 OS 独占全屏，改用 bounds 覆盖
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

    // ── 加固「窗口一定看得见」──
    // 历史问题：窗口只在 ready-to-show 里 show()。若渲染层加载异常导致该事件未如期
    // 触发，窗口就永远不显示 → 用户「唤不起来/打不开」。现在多重保险：
    //  1) ready-to-show / did-finish-load 任一触发即显示并定位；
    //  2) 兜底定时器：1.5s 后无论如何强制显示（绝不把外壳卡在不可见状态）；
    //  3) did-fail-load 打日志到 logs/electron.log，便于定位根因。
    let _shown = false;
    const _showOverlay = () => {
        if (_shown || !mainWindow || mainWindow.isDestroyed()) return;
        _shown = true;
        try {
            // 覆盖整块主屏（DIP 坐标），并置于最顶层、全工作区可见。
            mainWindow.setBounds(bounds);
            mainWindow.show();
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
            try { mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true }); } catch (e) {}
            // 始终鼠标穿透：覆盖层绝不接管鼠标，随时能操作桌面。
            mainWindow.setIgnoreMouseEvents(true, { forward: true });
            _overlayAwake = true;   // 启动即显示第一态 → 视为已唤醒（与可见状态一致）
        } catch (e) { console.error('[Main] 显示覆盖层失败:', e && e.message); }
        // 渲染层默认 silent(0.05) → 启动即显示第一态暖香槟辉光，无需任何「splash」。
        // 完整三态由后端 presence 事件 / 唤醒快捷键驱动，连贯过渡、不切割。
    };
    mainWindow.once('ready-to-show', _showOverlay);
    mainWindow.webContents.once('did-finish-load', _showOverlay);
    setTimeout(_showOverlay, 1500);   // 兜底：无论如何 1.5s 内显示
    mainWindow.webContents.on('did-fail-load', (_e, code, desc, url) => {
        console.error(`[Main] 覆盖层 did-fail-load code=${code} desc=${desc} url=${url}`);
        _showOverlay();   // 即便加载失败也显示窗口（DOM 兜底视觉仍可见），不让外壳消失
    });
    mainWindow.webContents.on('console-message', (_e, _lvl, message, line, sourceId) =>
        console.log(`[Overlay:renderer] ${message} (${sourceId}:${line})`));

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

app.whenReady().then(async () => {
    // 未取得单实例锁的后来者：什么都不做，等待 app.quit() 收尾，
    // 避免它创建窗口或去争抢已被占用的 IPC 端口。
    if (!gotSingleInstanceLock) return;

    // 解析感知授权（首次弹框 → 持久化；env 可强制覆盖）。在创建窗口/放行权限前确定。
    await resolvePerceptionConsent();

    // 媒体权限：Electron 默认拒绝 getUserMedia。授权后放行摄像头/麦克风/屏幕权限。
    try {
        const { session } = require('electron');
        session.defaultSession.setPermissionRequestHandler((wc, permission, callback) => {
            const mediaPerms = ['media', 'audioCapture', 'videoCapture', 'display-capture'];
            if (perceptionEnabled && mediaPerms.includes(permission)) {
                return callback(true);
            }
            return callback(false);
        });
    } catch (e) {
        console.warn('[Main] 设置媒体权限处理器失败:', e && e.message);
    }

    // 屏幕采集：让渲染层 perception-capture.js 的 getDisplayMedia 自动拿到【主屏】，
    // 不弹来源选择器（第一态连续屏幕采集要无人值守、免交互）。仅在授权时放行。
    try {
        const { session, desktopCapturer } = require('electron');
        session.defaultSession.setDisplayMediaRequestHandler((request, callback) => {
            if (!perceptionEnabled) { return callback(); }   // 未授权：取消
            desktopCapturer.getSources({ types: ['screen'] }).then((sources) => {
                if (sources && sources.length) {
                    callback({ video: sources[0] });          // 自动选第一个屏幕，无 UI
                } else {
                    callback();
                }
            }).catch(() => callback());
        }, { useSystemPicker: false });
    } catch (e) {
        console.warn('[Main] 设置屏幕采集处理器失败（旧版 Electron 可忽略）:', e && e.message);
    }

    createWindow();

    // ── IPC HTTP 接收端 ──
    // Python 后端 POST /ipc/presence-state → 转发到前端 via ipcMain
    try {
        const http = require('http');
        ipcHttpServer = http.createServer((req, res) => {
            // 托盘/外部触发：打开面板 或 唤醒覆盖层 —— 不依赖全局快捷键（F12 常被占用）。
            // 让系统托盘菜单可以可靠地打开面板，即使所有快捷键都注册失败。
            if (req.method === 'POST' && req.url === '/ipc/toggle-panel') {
                try { togglePanel(); } catch (e) { /* ignore */ }
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end('{"success": true, "action": "toggle-panel"}');
                return;
            }
            // /ipc/wake = 始终【显示】覆盖层（幂等，永不隐藏）——托盘「Wake Overlay」走这条，
            // 保证「按了就一定看得见」，不会因 toggle 把已显示的外壳反而藏起来。
            if (req.method === 'POST' && req.url === '/ipc/wake') {
                try { setOverlayPhase(true); } catch (e) { /* ignore */ }
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end('{"success": true, "action": "wake"}');
                return;
            }
            // /ipc/toggle-overlay = 显示/隐藏切换（供快捷键用）。
            if (req.method === 'POST' && req.url === '/ipc/toggle-overlay') {
                try { toggleOverlayWake(); } catch (e) { /* ignore */ }
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end('{"success": true, "action": "toggle-overlay"}');
                return;
            }
            // /ipc/hide-overlay = 始终【隐藏】覆盖层（幂等,永不显示）。
            // 补齐"放下"的托盘兜底——此前托盘只有 Wake(显示),没有对应的隐藏入口；
            // 若 Ctrl+Alt+H 等隐藏快捷键在用户机器上被占用而注册失败,此前完全没有
            // 办法把已唤醒的覆盖层收起去,只能靠可能失灵的快捷键(用户反馈"放下也
            // 没有完全注册"的直接根因)。
            if (req.method === 'POST' && req.url === '/ipc/hide-overlay') {
                try { setOverlayPhase(false); } catch (e) { /* ignore */ }
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end('{"success": true, "action": "hide-overlay"}');
                return;
            }
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

    // 系统托盘已改由 Python 启动器 (unified_launcher.start_system_tray) 在其自身进程
    // 内常驻启动，与 Electron 解耦 —— 避免 Electron 崩溃/重启把右下角托盘图标带没，
    // 也避免与 Python 侧重复启动出现两个托盘图标。此处不再 spawn。

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

    // ── 三态覆盖层「唤醒/隐藏」全局快捷键 ──
    // 之前没有任何唤醒快捷键被真正注册（启动横幅写的 Ctrl+Space 是假的），而且
    // Ctrl+Space 在中文 Windows 会被输入法抢去切换中英文 → 用户「按不开」。
    // 这里注册一组【不与输入法/系统冲突】的候选键，任一成功即可唤出覆盖层。
    const WAKE_SHORTCUTS = [
        'CommandOrControl+Alt+Space', 'CommandOrControl+Shift+Space',
        'CommandOrControl+Alt+G', 'CommandOrControl+Shift+G',
    ];
    const wakeRegistered = WAKE_SHORTCUTS.filter((accel) => {
        try { return globalShortcut.register(accel, () => toggleOverlayWake()); }
        catch (e) { return false; }
    });
    const HIDE_SHORTCUTS = ['CommandOrControl+Alt+H', 'CommandOrControl+Shift+H'];
    HIDE_SHORTCUTS.forEach((accel) => {
        try { globalShortcut.register(accel, () => setOverlayPhase(false)); } catch (e) { /* ignore */ }
    });
    console.log('[Main] 覆盖层唤醒快捷键: ' + (wakeRegistered.join(', ') || '(全部注册失败)'));

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

    // ── 面板加载诊断 + 可见兜底 ──
    // 历史问题：面板窗口 transparent，一旦渲染失败(如 Vite 产物带 crossorigin 在
    // file:// 被 CORS 拦截 → React 不挂载)，窗口全透明=不可见，用户以为「F12 打不开」。
    // 现在：把渲染层日志/加载失败打到 logs/electron.log，并在彻底加载失败时回退到一张
    // 不透明的提示页，保证窗口「看得见」而不是一片空白。
    const wc = panelWindow.webContents;
    wc.on('did-finish-load', () => console.log('[Panel] did-finish-load:', panelPath));
    wc.on('did-fail-load', (_e, code, desc, url) => {
        console.error(`[Panel] did-fail-load code=${code} desc=${desc} url=${url}`);
        try {
            panelWindow.setBackgroundColor('#11131c');
            panelWindow.loadURL('data:text/html;charset=utf-8,' + encodeURIComponent(
                '<body style="margin:0;background:#11131c;color:#eaf6ff;font-family:Segoe UI,system-ui;' +
                'display:flex;align-items:center;justify-content:center;height:100vh;text-align:center">' +
                '<div><h2>Galaxy 控制面板加载失败</h2>' +
                '<p style="opacity:.7">请重建面板：cd electron/renderer/panel &amp;&amp; npm install &amp;&amp; npm run build<br>' +
                '详情见 logs/electron.log</p></div></body>'));
        } catch (e) { /* ignore */ }
    });
    wc.on('render-process-gone', (_e, details) =>
        console.error('[Panel] render-process-gone:', JSON.stringify(details)));
    wc.on('console-message', (_e, level, message, line, sourceId) =>
        console.log(`[Panel:renderer] ${message} (${sourceId}:${line})`));

    panelWindow.on('closed', () => {
        panelWindow = null;
        isPanelVisible = false;
    });

    return panelWindow;
}

// ── 三态覆盖层手动唤醒/隐藏 ──
// 「唤醒」= 把 AI 这一整套三态外壳显示出来，停在【第一态(silent 暖金边缘氛围光)】。
// 三态(silent→liminal→manifest)之间的切换由后端 DesktopPresenceRuntime 按 AI 的【实际
// 活动】自行驱动(待机=silent / 思考=liminal / 执行=manifest)，唤醒不强制跳到某个具体态。
// 早期错误：曾把唤醒强制设成 0.92(manifest 透明执行) → 一按唤醒几乎全透明，像「换不醒」；
// 又曾强制设成 0.60(liminal) → 等于硬切第二态。二者都不对：唤醒只该显示外壳、停第一态。
// 「隐藏」= 收起整套外壳(隐藏窗口)。
let _overlayAwake = false;
function setOverlayPhase(awake) {
    if (!mainWindow || mainWindow.isDestroyed()) return;
    _overlayAwake = awake;
    try {
        // 始终保持鼠标穿透(forward)：覆盖层是全屏透明窗口，绝不接管鼠标，保证随时能操作桌面。
        mainWindow.setIgnoreMouseEvents(true, { forward: true });
        if (awake) {
            // 停在第一态(暖金辉光)；不强制后续态，交给后端按 AI 实际活动驱动 1→2→3。
            try {
                mainWindow.webContents.send('presence-state', {
                    phase: 'silent', depth_factor: 0.05, intent: 'manual_wake',
                    speaking: false, source: 'hotkey',
                });
            } catch (e) { /* ignore */ }
            // 幂等地「显示并置顶」：重定位到主屏 bounds（防止被移到屏外）、显示、全工作区可见、
            // 顶到 screen-saver 层。即使本来就可见，再调用一次也只是确保它在最前、看得见。
            try {
                mainWindow.setBounds(screen.getPrimaryDisplay().bounds);
            } catch (e) { /* ignore */ }
            mainWindow.show();
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
            try { mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true }); } catch (e) {}
            mainWindow.moveTop();
        } else {
            mainWindow.hide();   // 隐藏整套外壳
        }
    } catch (e) { /* ignore */ }
    console.log('[Overlay] ' + (awake
        ? '已唤醒(第一态 暖金辉光；三态随 AI 实际活动自行切换)'
        : '已隐藏(收起外壳)'));
}
function toggleOverlayWake() {
    setOverlayPhase(!_overlayAwake);
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
    enabled: perceptionEnabled,
    intervalMs: PERCEPTION_INTERVAL_MS,
    video: true,
    audio: true,
}));

// 渲染层采到的帧/音频 → 转发到网关的桌面感知接收端
ipcMain.on('galaxy:desktop-perception', async (_event, payload) => {
    if (!perceptionEnabled || !payload) return;
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
        // 后端未就绪/网络抖动等非致命；丢弃本帧即可。
        // 限流日志：每帧都打会把 electron.log 刷爆（摄像头每 2s 一帧）。只在【首次】和【每 30s】
        // 各打一次，并带累计次数，既能看见问题又不淹没真正的报错。
        _perceptionFailCount++;
        const _now = Date.now();
        if (_now - _perceptionFailLogAt > 30000) {
            console.warn(`[Perception] forward 失败（已累计 ${_perceptionFailCount} 帧）：` +
                `${e && e.message} — 目标 ${GATEWAY_BASE}/api/perception/desktop/*；` +
                `请确认后端网关在 ${GATEWAY_BASE} 正常监听。`);
            _perceptionFailLogAt = _now;
        }
    }
});
let _perceptionFailCount = 0;
let _perceptionFailLogAt = 0;

// ═══════════════════════════════════════════
// Configuration Management — Python Backend
// ═══════════════════════════════════════════

// 内存中的配置缓存
let configCache = {};      // 精简版(模型 tab):{api_base_url, ws_url, status, configured, values}
let settingsCache = {};    // 完整明细(设置 tab):{KEY: {value, default, type, category, description}}

// 从 Python 后端获取配置(精简版 —— 模型 tab 消费)
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

// 从 Python 后端获取完整配置明细(设置 tab 消费,与精简版不同路径,避免路由遮蔽)
async function fetchSettingsFromBackend() {
    try {
        const response = await fetch(`${GATEWAY_BASE}/api/config/all`);
        if (response.ok) {
            settingsCache = await response.json();
            return settingsCache;
        }
    } catch (e) {
        console.error('[Main] Failed to fetch settings:', e.message);
    }
    return settingsCache;
}

// GET 配置(精简版 —— 模型 tab)
ipcMain.handle('galaxy:get-config', async () => {
    return await fetchConfigFromBackend();
});

// GET 配置(完整明细 —— 设置 tab)
ipcMain.handle('galaxy:get-settings', async () => {
    return await fetchSettingsFromBackend();
});

// SET 配置（批量更新）
ipcMain.handle('galaxy:set-config', async (_, config) => {
    try {
        const response = await fetch(`${GATEWAY_BASE}/api/config`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            // 后端 ConfigUpdateRequest 要求 {config: {...}} 形状，不能直接发裸对象
            body: JSON.stringify({ config }),
        });
        if (response.ok) {
            configCache = { ...configCache, ...config };
            // 同步更新完整明细缓存里对应项的 value(保持 ConfigItem 形状,
            // 不用裸字符串覆盖整项 —— 否则设置 tab 下次渲染会读到 undefined)。
            Object.entries(config).forEach(([k, v]) => {
                if (settingsCache[k]) settingsCache[k] = { ...settingsCache[k], value: v };
            });
            // 广播到所有窗口(裸的 {KEY: 新值} —— 由各 tab 自行按需合并到自己的形状)。
            BrowserWindow.getAllWindows().forEach(w => {
                w.webContents.send('galaxy:config-update', config);
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

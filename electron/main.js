const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
const path = require('path');

// ── Two-window architecture ──
// mainWindow    : Three-State Full-Screen AI (always on, never hidden)
// panelWindow   : Unified Control Panel (toggled by F12)
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

function createPanelWindow() {
    // Create the unified control panel window (toggled by F12).
    // WAVE-3-TODO: panel.html will be created during Wave 3 (control panel design).
    // Until then, F12 toggling is a no-op — the three-state GUI is unaffected.
    const fs = require('fs');
    const panelPath = path.join(__dirname, 'renderer', 'panel.html');
    if (!fs.existsSync(panelPath)) {
        console.log('[Panel] panel.html not found — F12 panel disabled until Wave 3');
        return null;
    }

    if (panelWindow) {
        return panelWindow;
    }
    panelWindow = new BrowserWindow({
        width: 1400,
        height: 900,
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
        backgroundColor: '#0a0a0a88',
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js'),
            webSecurity: true,
        }
    });

    panelWindow.loadFile(panelPath);

    panelWindow.once('ready-to-show', () => {
        // Don't show yet — wait for F12
    });

    panelWindow.on('closed', () => {
        panelWindow = null;
        isPanelVisible = false;
    });

    return panelWindow;
}

function togglePanel() {
    // F12 toggles the control panel — three-state GUI is unaffected.
    if (!panelWindow) {
        createPanelWindow();
    }
    if (!panelWindow) return;

    if (isPanelVisible) {
        panelWindow.hide();
        isPanelVisible = false;
        console.log('Panel hidden (F12)');
    } else {
        panelWindow.show();
        panelWindow.focus();
        isPanelVisible = true;
        console.log('Panel shown (F12)');
    }
}

app.whenReady().then(() => {
    createWindow();
    // Panel is created lazily on first F12

    // PR-D5: Start system tray alongside Electron GUI
    try {
        const { spawn } = require('child_process');
        const trayProcess = spawn('python', ['-m', 'windows_service.tray_icon'], {
            cwd: path.join(__dirname, '..'),
            detached: true,
            stdio: 'ignore'
        });
        trayProcess.unref();
        console.log('System tray started');
    } catch (err) {
        console.warn('Failed to start system tray:', err);
    }

    // PR-F12-PANEL: F12 toggles control panel (NOT the three-state GUI)
    globalShortcut.register('F12', () => {
        togglePanel();
    });
    // Legacy shortcut also toggles panel
    globalShortcut.register('CommandOrControl+Shift+G', () => {
        togglePanel();
    });

    app.on('browser-window-created', (event, window) => {
        if (mainWindow) {
            mainWindow.setAlwaysOnTop(true, 'screen-saver');
        }
    });
});

app.on('window-all-closed', () => {
    app.quit();
});

app.on('will-quit', () => {
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

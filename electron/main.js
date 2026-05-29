const { app, BrowserWindow, globalShortcut, ipcMain } = require('electron');
const path = require('path');

// ── Single-window architecture ──
// mainWindow : Three-State Full-Screen AI (always on, never hidden)
// Panel removed — will be rebuilt with full design brief + reference images
let mainWindow = null;

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

    // F12 panel shortcut removed — panel will be rebuilt with full design brief
    // globalShortcut.register('F12', () => { togglePanel(); });

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

# Galaxy Desktop Presence (Electron)

Three-state fullscreen AI assistant desktop overlay powered by Electron.

## Architecture

- **main.js** — Main process: window management, global shortcuts, IPC HTTP server, perception config
- **preload.js** — Secure IPC bridge between main and renderer
- **renderer/** — Renderer process: WebGL visuals, perception capture, UI components

## Three States

1. **Silent** (0.05) — Warm champagne edge glow, ambient presence
2. **Liminal** (0.50) — Island expands, spatial depth emerges
3. **Manifest** (0.92) — Full execution surface with coherent visual

## Security

- CSP policy restricts script/style sources to `'self'`
- `contextIsolation: true`, `nodeIntegration: false`
- `webSecurity: true`, `allowRunningInsecureContent: false`
- All configuration changes validated server-side

## Quick Start

```bash
cd electron
npm install
npm start        # production mode
npm run dev      # development mode
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `GALAXY_GATEWAY_PORT` | Backend gateway port | 9000 |
| `GALAXY_IPC_PORT` | IPC HTTP receiver port | 9231 |
| `GALAXY_DESKTOP_PERCEPTION` | Enable camera/mic/screen capture | 0 |
| `GALAXY_ELECTRON_GPU` | GPU acceleration (0=software render) | 1 |

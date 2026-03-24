# Node 124 - Linux Desktop Automation

Linux desktop UI automation and scripting service. Provides programmatic control of mouse, keyboard, windows, clipboard, and screen capture using `xdotool`/xlib.

## Port
Default port: **8124**

## Prerequisites

Requires the following system packages on the host:
```bash
sudo apt install xdotool scrot xclip
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NODE_PORT` | `8124` | Listening port |
| `NODE_ID` | `124` | Node identifier |
| `LOG_LEVEL` | `INFO` | Logging level |
| `DISPLAY` | `:0` | X11 display target |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check |
| `POST` | `/click` | Mouse click at coordinates or on element |
| `POST` | `/type` | Type text at current focus |
| `POST` | `/key` | Send a key or key combination |
| `POST` | `/move` | Move mouse to coordinates |
| `POST` | `/drag` | Click-drag between two points |
| `POST` | `/scroll` | Scroll at coordinates |
| `POST` | `/screenshot` | Capture a screenshot (base64 PNG) |
| `POST` | `/window` | Window management (focus, resize, move) |
| `POST` | `/clipboard` | Read/write clipboard |
| `GET` | `/mouse_position` | Get current mouse position |
| `GET` | `/screen_size` | Get screen dimensions |
| `GET` | `/active_window` | Get active window info |
| `POST` | `/mcp/call` | MCP tool dispatch |
| `GET` | `/tools` | List available MCP tools |

## Dependencies

See `requirements.txt` for full dependency list.

## Running

```bash
pip install -r requirements.txt
python main.py
```

Or with Docker (requires X11 socket passthrough):

```bash
docker build -t galaxy-node-124-linuxdesktopauto .
docker run -p 8124:8124 -e DISPLAY=$DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix galaxy-node-124-linuxdesktopauto
```

## Governance

`startup_policy: optional` — started if available; startup failure does not abort the system.
Promote to `active` after passing integration tests and health-check review (see `docs/NODE_ACTIVE_MANIFEST.md`).

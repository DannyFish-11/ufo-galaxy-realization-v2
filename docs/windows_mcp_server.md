# Windows Execution Pipeline

> **This document describes the current (unified) Windows execution architecture.**
> The legacy Windows MCP Server path documented previously has been retired.
> See the [Deprecated Paths](#deprecated-paths) section at the bottom.

---

## Active Windows Execution Pipeline

All Windows local execution flows through a single, unified pipeline:

```
AIP ingress
(windows_aip_client.py)
        │
        │  WebSocket /ws/device/{device_id}
        │  AIP v3.0 handshake + capability_report
        │
        ▼
WindowsExecutionArbiter         ← core/windows_execution_arbiter.py
(route_command / execute)       ← unified execution entry point
        │
        │  strict fallback chain:
        │
        ├─ Level 1: System API   (Win32 / OS calls)
        ├─ Level 2: UIA          (WindowsAutonomyManager — COM accessibility)
        ├─ Level 3: GUI          (coordinate-based input simulation)
        └─ Level 4: VLM          (screenshot + vision-language model, last resort)
```

This is the **only** active Windows execution path.

---

## Quick Start

### 1. Start the Galaxy server

```bash
python main.py   # or: uvicorn main:app --host 0.0.0.0 --port 8000
```

### 2. Register the Windows device

```bash
pip install websockets
python windows_client/windows_aip_client.py --host 127.0.0.1 --port 8000
```

Optional parameters:

| Parameter | Default | Description |
|---|---|---|
| `--host` | `127.0.0.1` | Server address |
| `--port` | `8000` | Server port |
| `--device-id` | auto-generated | Custom device ID |

The client will:
1. Connect to `ws://{host}:{port}/ws/device/{device_id}`
2. Send `device_register` (AIP v3.0 handshake)
3. Send `capability_report` (supported actions list)
4. Maintain heartbeat (every 30 s)
5. Receive and execute incoming commands through `WindowsExecutionArbiter`

### 3. Send a task

```bash
curl -X POST http://127.0.0.1:8000/api/v1/agent/autonomous \
  -H "Content-Type: application/json" \
  -d '{"instruction": "截取当前屏幕截图"}'
```

---

## Supported Actions

| Action | Description |
|---|---|
| `get_screen_state` | Get foreground window UI tree (accessible elements) |
| `click` | Mouse click (coordinates) |
| `type` | Type text |
| `press_key` | Press a single key (enter / escape / f5 …) |
| `press_keys` | Press a key combination (['ctrl','c'] …) |
| `scroll` | Mouse wheel scroll |
| `find_and_click` | Find UI element by name/AutomationId and click |
| `find_and_type` | Find UI element and type text |
| `screenshot` | Capture screen, return base64 PNG |

---

## Desktop Status Board

The Windows desktop UI (`windows_client/ui/galaxy_client_ui.py`) is a
**tri-state status mapping panel** — it displays the current `TriStatePhase`
(`silent` / `liminal` / `manifest`) and device state.

It is **not** a chat input surface.  Input to OpenClawd is handled exclusively
through the AIP ingress pipeline.

See [WINDOWS_STATUS_BOARD.md](WINDOWS_STATUS_BOARD.md) for more details.

---

## Deprecated Paths

The following modules are **deprecated** and must not be used as active primary
paths in new deployments:

| Module | Status | Reason |
|---|---|---|
| `windows_client/windows_mcp_server.py` | Deprecated | MCP stdio path replaced by AIP → Arbiter |
| `windows_client/ui_sidebar.py` | Deprecated | Old Tk chat sidebar; replaced by status board |
| `windows_client/client.py` | Deprecated | Old bespoke Gateway/AIP handler |
| `windows_client/desktop_automation.py` | Deprecated | pyautogui path; now a GUI fallback level inside Arbiter |

All deprecated modules emit a `DeprecationWarning` when imported.

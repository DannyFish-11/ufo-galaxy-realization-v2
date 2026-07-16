# Windows Client

Galaxy Windows device integration: AIP v3.0 client, status board, and execution arbiter.

## Modules

| Module | Status | Description |
|--------|--------|-------------|
| `windows_aip_client.py` | Active | AIP v3.0 WebSocket client — device registration, heartbeat, command execution |
| `status_board_v2/` | Active | Projection-driven CLI status board (read-only surface) |
| `client.py` | Disabled | Legacy gateway client (hard-disabled stub) |
| `windows_client_integrated.py` | Disabled | Legacy PyQt6 client (hard-disabled stub) |
| `ui_sidebar.py` | Disabled | Legacy Tk sidebar (hard-disabled stub) |
| `key_listener.py` | Disabled | Legacy F12 hotkey listener (hard-disabled stub) |
| `desktop_automation.py` | Disabled | Legacy pyautogui automation (hard-disabled stub) |
| `windows_mcp_server.py` | Disabled | Legacy MCP server (hard-disabled stub) |

## Quick Start

### AIP Client

```bash
python windows_client/windows_aip_client.py --host 127.0.0.1 --port 8000
```

### Status Board V2

```bash
# Poll the default local server
python -m windows_client.status_board_v2

# With management console
python -m windows_client.status_board_v2 --management
```

## Architecture

All inbound commands route through `WindowsExecutionArbiter.route_command()` with the fallback chain:

```
system_api -> UIA (via WindowsAutonomyManager) -> GUI -> VLM
```

## Logging

Log files are stored in `~/.galaxy/logs/windows_aip_client.log` with automatic rotation (5 MB max, 3 backups).

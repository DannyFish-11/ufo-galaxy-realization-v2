# UFO Galaxy - Deployment Guide

## Environment Variables

The following environment variables can be used to configure UFO Galaxy at deployment time.

### Plugin Directory

| Variable | Default | Description |
|---|---|---|
| `UFO_PLUGIN_DIR` | `~/ufo-plugins` | Path to the directory where node plugins are loaded from. Used by Node_28, Node_29, Node_31, and Node_32. |

**Example:**

```bash
# Use a custom plugin directory
export UFO_PLUGIN_DIR=/opt/ufo-galaxy/plugins
python smart_launcher.py start

# Or inline for a single run
UFO_PLUGIN_DIR=/custom/path python nodes/Node_28_Reserved/main.py
```

When `UFO_PLUGIN_DIR` is not set, the nodes default to `~/ufo-plugins` (i.e. `$HOME/ufo-plugins` of the current user), which makes the system portable across different users and operating systems.

---

## Monitoring

`smart_launcher.py monitor` checks node health every 10 seconds and automatically restarts failed nodes (up to 3 retries per node). The monitor responds immediately to `Ctrl+C` thanks to `threading.Event`-based waiting.

---

## Hardware Watchdog

`hardware/hardware_monitor.py` runs a hardware watchdog that checks for system unresponsiveness. The watchdog loop uses `threading.Event.wait(timeout=1)` so it can be stopped immediately when `stop_monitoring()` is called.

---

## Node Call Timeouts

`core/node_registry.py` enforces a **30-second timeout** on every `call_node()` invocation. If a node does not respond within 30 seconds, the call fails fast with:

```json
{"success": false, "error": "Node call timeout after 30s"}
```

Automatic failover to an alternative node (if available) is attempted before returning the error.

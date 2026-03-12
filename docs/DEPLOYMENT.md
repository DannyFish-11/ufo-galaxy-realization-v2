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

## Gateway Auth & Key Rotation

The Galaxy Gateway supports Bearer token authentication with zero-downtime
key rotation.  Set `GALAXY_AUTH_ENABLED=true` to enforce auth on all
gateway endpoints.

| Variable | Default | Description |
|---|---|---|
| `GALAXY_AUTH_ENABLED` | `false` | Set to `true` to enforce Bearer token auth on the gateway. Defaults to `false` for backward compatibility. |
| `GALAXY_API_TOKEN` | — | Primary API token (legacy single-token variable). |
| `GALAXY_API_TOKEN_EXPIRY` | — | ISO-8601 UTC expiry time for `GALAXY_API_TOKEN`, e.g. `2026-09-01T00:00:00Z`. The primary token is rejected after this time. |
| `GALAXY_API_TOKENS` | — | Comma-separated list of additional active tokens for zero-downtime key rotation overlap. |
| `GALAXY_REVOKED_TOKENS` | — | Comma-separated list of tokens to reject immediately (instant revocation), even if they appear in the active token lists. |

### Quick-start (single token)

```bash
GALAXY_AUTH_ENABLED=true
GALAXY_API_TOKEN=my-secret-token
```

### Zero-downtime rotation (overlap window)

```bash
GALAXY_AUTH_ENABLED=true
GALAXY_API_TOKEN=old-secret        # still accepted during migration
GALAXY_API_TOKENS=new-secret       # new token clients should migrate to
```

See [`docs/KEY_ROTATION.md`](KEY_ROTATION.md) for the full step-by-step
rotation procedure, instant-revocation instructions, and a post-rotation
verification checklist.

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

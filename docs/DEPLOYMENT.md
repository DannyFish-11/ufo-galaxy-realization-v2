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
key rotation.  Auth is **enforced by default**.  A zero-config install still
starts: on first run the gateway signs a local token into
`$GALAXY_DATA_DIR/api_token.json` (mode `0600`) and uses it.

The default used to be off.  That rested on "the gateway only ever listens on
the LAN, and the home network is itself the trust boundary".  Any publicly
reachable path — Tailscale Funnel, a port forward, a tunnel — removes that
premise, and reachability changes without the config changing.  A default must
not rest on "currently happens to be unreachable".

| Variable | Default | Description |
|---|---|---|
| `GALAXY_AUTH_ENABLED` | `true` | Set to `false` only when there is provably no publicly reachable path to the gateway. Unrecognised values fail closed (auth stays on). |
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

## Reaching the gateway from mobile data (Tailscale Funnel)

LAN, hotspot and Wi-Fi all reach the gateway directly.  A device that only has
mobile data does not — and a Wear OS watch cannot join the tailnet either,
because there is no Tailscale client for it.  Funnel is the one path that
covers both: it exposes the gateway on the public internet over
`https://<machine>.<tailnet>.ts.net`, and **the far side needs no client**.

The gateway tries to bring Funnel up on startup (`GALAXY_TS_FUNNEL=1`, the
default) and degrades quietly if it can't — startup is never blocked.

**It will refuse to run when auth is off.**  `funnel_preflight()` is a hard
gate, not a warning: with auth disabled, or with no usable token, not a single
`tailscale` command is executed.  Exposing an unauthenticated gateway to the
public internet would let anyone open `/ws/device/<any id>` and drive the
machine.

### One-time manual step

Funnel needs consent in the Tailscale admin console the first time — the CLI
refuses until it is granted, and the refusal text carries the link:

1. Enable **HTTPS certificates** for the tailnet (DNS → HTTPS Certificates).
2. Grant the machine the **`funnel`** node attribute (Access Controls →
   `nodeAttrs`).

| Variable | Default | Description |
|---|---|---|
| `GALAXY_TS_FUNNEL` | `true` | Try to expose the gateway publicly via Funnel on startup. Set `false` to keep the gateway tailnet-only (watches on mobile data then cannot connect). |

The public port is fixed to 443 (Tailscale allows only 443/8443/10000); the
local gateway port is mapped behind it, so the URL handed to devices carries
**no** `:9000`.

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

# Galaxy — Compatibility Toggles Reference

This document lists all legacy/optional features and their environment variable toggles.
All legacy features are **disabled by default** and require explicit opt-in.

---

## Core Toggles

| Environment Variable                  | Default  | Description                                                                          |
|---------------------------------------|----------|--------------------------------------------------------------------------------------|
| `GALAXY_NATS_URL`                     | `nats://localhost:4222` | NATS server URL. **Required.** Startup fails if NATS is unreachable. |
| `GALAXY_NATS_PORT`                    | `4222`   | NATS port (used by startup scripts when GALAXY_NATS_URL is not set)                  |
| `GALAXY_ENABLE_LEGACY_MULTIDEVICE`    | `false`  | Enable legacy AIP v2 multidevice coordination layer (enhancements/multidevice)       |
| `GALAXY_MASTER_BRAIN_ENABLED`         | `false`  | Enable MasterBrain cloud-side orchestrator                                            |

---

## Legacy Multidevice Compatibility Layer

**Variable:** `GALAXY_ENABLE_LEGACY_MULTIDEVICE`

**Default:** `false` (disabled)

**Purpose:** Enables the legacy `enhancements/multidevice` package which implements AIP v2
protocol adaptation for old binary clients that have not yet migrated to AIP v3 + Node_71.

**Behavior when disabled (default):**
- Importing `enhancements.multidevice` emits a `UserWarning` and returns stub classes
- Any attempt to instantiate a legacy multidevice class raises `RuntimeError`
- The canonical multi-device engine (Node_71) is always used

**Behavior when enabled:**
- Full legacy AIP v2 multidevice layer is active
- Handles protocol adaptation and message routing for old clients
- Does **not** maintain independent device state (Node_71 is the source of truth)
- Old clients using AIP v2 binary protocol can connect

**How to enable:**
```bash
# Linux / macOS
export GALAXY_ENABLE_LEGACY_MULTIDEVICE=true
bash start.sh

# Windows
set GALAXY_ENABLE_LEGACY_MULTIDEVICE=true
start.bat

# Docker Compose — add to environment section:
environment:
  - GALAXY_ENABLE_LEGACY_MULTIDEVICE=true
```

**Migration path:**
Clients should migrate from AIP v2 to AIP v3 (Gateway WebSocket) to eventually
remove the dependency on this legacy layer.

---

## MasterBrain Orchestrator

**Variable:** `GALAXY_MASTER_BRAIN_ENABLED`

**Default:** `false` (disabled)

**Purpose:** Enables the cloud-side MasterBrain task orchestrator which uses NATS
to distribute tasks across worker nodes.

**How to enable:**
```bash
export GALAXY_MASTER_BRAIN_ENABLED=true
bash start.sh
```

---

## Gateway Legacy Entry Points

**Default:** Disabled (HTTP 404 / connection refused)

The following legacy WebSocket paths are disabled by default:
- `/ws/ufo3` — Legacy UFO v3 WebSocket
- `/ws/legacy` — Legacy protocol bridge

These are managed in `galaxy_gateway/app.py`. There is currently no env var toggle;
re-enabling them requires code changes and is not recommended.

---

## NATS (Required, not optional)

NATS is **not** a toggleable feature — it is the internal scheduling mainline and
is **required for startup**. There is no fallback or "noop" mode.

If NATS is unavailable:
- `start.sh` / `start.bat` will exit with an error and print instructions
- `unified_launcher.py` will raise `SystemExit` with a clear message
- `galaxy_gateway/app.py` will raise `RuntimeError` on startup

---

## Summary

| Feature                     | Toggle Variable                        | Default  | Safe to Enable? |
|-----------------------------|----------------------------------------|----------|-----------------|
| NATS (scheduling mainline)  | N/A (required)                         | required | N/A             |
| Legacy AIP v2 multidevice   | `GALAXY_ENABLE_LEGACY_MULTIDEVICE`     | OFF      | ✅ Yes (read-only adaptation) |
| MasterBrain orchestrator    | `GALAXY_MASTER_BRAIN_ENABLED`          | OFF      | ✅ Yes           |
| Gateway legacy WS paths     | Code change required                   | OFF      | ⚠️ Not recommended |

---

See also:
- [DEPLOYMENT_COMPLETE.md](DEPLOYMENT_COMPLETE.md) — Full deployment instructions
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Common errors and fixes
- [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) — Verification checklist

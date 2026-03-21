# Local Runtime Host Contract

**PR-30** — Galaxy / OpenClawd system

---

## Overview

The **Local Runtime Host Contract** (`contracts/local_runtime_host.py`) is the
**host-side counterpart to PR-29 (Registered Runtime Device Contract)**.

| Contract | Question answered |
|----------|------------------|
| **PR-29** `RegisteredRuntimeDevice` | *What is a runtime-capable device?* |
| **PR-30** `LocalRuntimeHost` | *What must a device hosting a local runtime expose?* |

This contract formalises the posture of a physical device that:
- **accepts runtime participation** (a local agent runtime can be dispatched to it);
- **exposes local autonomy posture** (can it run local inference, planning, execution autonomously?);
- **supports receiving cross-device handoff** (another device can dispatch an agent runtime to it);
- **manages local execution/session lifecycle** in a standard, serialisable way.

It is additive only and does not modify any existing module.

---

## Background

Before PR-30, the repository implied local-runtime-host behaviour in several
fragmented locations:

- `galaxy_gateway/agent_bridge.py` — bridge handoff logic and `HandoffContract`.
- `docs/RUNTIME_BRIDGE.md` — handoff endpoint model and bridge config.
- `contracts/execution_trace.py` — runtime/session/trace execution context.
- `core/device_registry.py`, `galaxy_gateway/device_router.py` — device capability data.
- `core/mesh/body_mesh_registry.py` — device-formation and projection surfaces.

No single canonical contract stated what a "local runtime host" must expose.
**PR-30 defines that contract explicitly.**

---

## How it differs from RegisteredRuntimeDevice (PR-29)

| Aspect | RegisteredRuntimeDevice | LocalRuntimeHost |
|--------|------------------------|-----------------|
| **Focus** | Device identity and capability profile | Runtime-host posture and participation |
| **Key question** | What is this device? What can it do? | What does it expose as a runtime host? |
| **Main fields** | `device_id`, `platform`, `form_factor`, `capabilities`, `autonomy`, `session_presence` | `host_id`, `device_id`, `runtime_id`, `host_enabled`, `host_status`, `supports_*` flags, session/handoff/execution sub-contracts |
| **Adapters** | From UDM, router device, Android registration, device registry | From `RegisteredRuntimeDevice`, from bridge config, generic builder |
| **Scope** | Device registration and capability normalisation | Runtime participation, handoff receive, local execution posture |

---

## Contract structure

```
LocalRuntimeHost
│
├── host_id                           str   (auto-generated UUID hex)
├── device_id                         str
├── runtime_id                        Optional[str]
├── runtime_version                   Optional[str]
├── host_enabled                      bool
├── host_status                       LocalRuntimeHostStatus
│
├── # Top-level posture flags (convenience mirrors of sub-contracts)
├── supports_local_autonomy           bool
├── supports_local_execution          bool
├── supports_local_planning           bool
├── supports_local_fallback           bool
├── supports_remote_handoff_receive   bool
├── supports_remote_handoff_callback  bool
├── supports_runtime_sessions         bool
│
├── # Flat convenience lists
├── active_session_ids                List[str]
├── execution_modes                   List[str]   ("local", "remote", "hybrid", …)
├── callback_channels                 List[str]   ("ws", "nats", "webrtc", …)
├── capability_summary                List[str]   (device capability names)
│
├── # Optional load / concurrency
├── max_concurrent_tasks              Optional[int]
├── current_load                      Optional[float]  [0.0, 1.0]
│
├── # Sub-contracts (structured)
├── capabilities  LocalRuntimeHostCapabilities
│   ├── supports_local_autonomy           bool
│   ├── supports_local_execution          bool
│   ├── supports_local_planning           bool
│   ├── supports_local_fallback           bool
│   ├── supports_remote_handoff_receive   bool
│   ├── supports_remote_handoff_callback  bool
│   └── supports_runtime_sessions         bool
│
├── sessions      LocalRuntimeSessionSupport
│   ├── supports_runtime_sessions  bool
│   ├── max_concurrent_tasks       Optional[int]
│   ├── current_load               Optional[float]
│   └── active_session_ids         List[str]
│
├── handoff       LocalRuntimeHandoffSupport
│   ├── supports_remote_handoff_receive   bool
│   ├── supports_remote_handoff_callback  bool
│   └── callback_channels                 List[str]
│
├── execution     LocalRuntimeExecutionSupport
│   ├── supports_local_execution  bool
│   ├── supports_local_planning   bool
│   ├── supports_local_autonomy   bool
│   ├── supports_local_fallback   bool
│   └── execution_modes           List[str]
│
├── metadata                          Dict[str, Any]
└── recorded_at                       float  (Unix timestamp)
```

---

## LocalRuntimeHostStatus values

| Value | Meaning |
|-------|---------|
| `inactive` | Runtime is registered but not currently active |
| `starting` | Runtime is initialising |
| `active` | Runtime is live and accepting participation |
| `degraded` | Runtime is running but in reduced capacity |
| `stopping` | Runtime is shutting down |
| `error` | Runtime encountered a fatal error |

---

## LocalRuntimeExecutionMode values

| Value | Meaning |
|-------|---------|
| `local` | Tasks are executed locally on this host |
| `remote` | Tasks can be delegated to a remote host |
| `hybrid` | Both local and remote execution are supported |
| `fallback` | This host acts as a fallback executor |

---

## Local autonomy / local execution / remote handoff receive

### `supports_local_autonomy`
The host can operate a **fully autonomous local loop**: voice-in → local
inference → action → local output, without any remote assistance.  This is the
core "each device can run its own closed loop" principle.

### `supports_local_execution`
The host can **execute tasks locally**.  This may not imply a full autonomous
loop (e.g. a device may execute commands dispatched from another device without
running its own inference).

### `supports_local_planning`
The host can run a **local planning/reasoning step** (e.g. a local LLM or
planner).

### `supports_remote_handoff_receive`
Another device can **dispatch a runtime agent to this host** via the
`AgentBridge` handoff mechanism.  The host will receive the handoff and manage
local execution on behalf of the originating device.  This is the core
cross-device "dispatch agent to local runtime" capability.

---

## Which current system pieces normalise into this contract

| Source | Adapter |
|--------|---------|
| `RegisteredRuntimeDevice` (PR-29) | `from_registered_runtime_device(rrd)` |
| `AgentBridgeConfig` / bridge config dict | `from_runtime_bridge_config(config)` |
| Any mix of the above fields | `build_local_runtime_host(device_id=..., ...)` |

Internally, `from_registered_runtime_device` reads:
- `autonomy.runtime_enabled` → `host_enabled`, `supports_local_execution`, etc.
- `autonomy.supports_local_autonomy` → `supports_local_autonomy`, `supports_local_planning`
- `autonomy.supports_remote_handoff` → `supports_remote_handoff_receive`
- `autonomy.runtime_id` / `autonomy.runtime_version` → `runtime_id` / `runtime_version`
- `session_presence.active_session_ids` → `active_session_ids`
- `capabilities.capabilities` → `capability_summary`
- `participation_hints.preferred_callback_channel` → `callback_channels`

`from_runtime_bridge_config` reads:
- `runtime_enabled` → `host_enabled`, all `supports_local_*` flags
- `cross_device_enabled` → `supports_remote_handoff_receive`
- `runtime_url` → presence of `callback_channels`

---

## API endpoints (read-only, additive)

### `GET /api/v1/devices/runtime-hosts`

Returns a list of `summarize_local_runtime_host()` dicts for all known devices.

```json
{
  "runtime_hosts": [
    {
      "host_id": "lrh_a1b2c3d4e5f6",
      "device_id": "phone_001",
      "runtime_id": null,
      "runtime_version": null,
      "host_enabled": true,
      "host_status": "active",
      "supports_local_autonomy": true,
      "supports_local_execution": true,
      "supports_local_planning": true,
      "supports_local_fallback": true,
      "supports_remote_handoff_receive": false,
      "supports_remote_handoff_callback": false,
      "supports_runtime_sessions": true,
      "active_session_count": 0,
      "execution_modes": ["local", "hybrid"],
      "callback_channels": [],
      "capability_summary": ["screen", "camera", "microphone"],
      "max_concurrent_tasks": null,
      "current_load": null,
      "recorded_at": 1710000000.0
    }
  ],
  "count": 1
}
```

### `GET /api/v1/devices/{device_id}/runtime-host`

Returns the full `LocalRuntimeHost.to_dict()` for a single device.

---

## Usage examples

```python
from contracts.local_runtime_host import (
    LocalRuntimeHost,
    LocalRuntimeHostStatus,
    LocalRuntimeHostCapabilities,
    LocalRuntimeSessionSupport,
    LocalRuntimeHandoffSupport,
    LocalRuntimeExecutionSupport,
    from_registered_runtime_device,
    from_runtime_bridge_config,
    build_local_runtime_host,
    summarize_local_runtime_host,
)

# Build from a RegisteredRuntimeDevice (PR-29)
from contracts.registered_runtime_device import build_registered_runtime_device
rrd = build_registered_runtime_device(
    device_id="phone_001",
    runtime_enabled=True,
    supports_local_autonomy=True,
)
host = from_registered_runtime_device(rrd)
summary = summarize_local_runtime_host(host)
payload = host.to_dict()

# Build from an AgentBridgeConfig
from galaxy_gateway.agent_bridge import AgentBridgeConfig
config = AgentBridgeConfig.from_env()
host = from_runtime_bridge_config(config)

# Build from scratch
host = build_local_runtime_host(
    device_id="pc_001",
    host_enabled=True,
    supports_local_execution=True,
    supports_local_autonomy=True,
    supports_remote_handoff_receive=True,
    execution_modes=["local", "remote", "hybrid"],
    callback_channels=["ws"],
)

# Serialisation
raw = host.to_dict()     # JSON-serialisable dict
json_str = host.to_json()  # JSON string
reconstructed = LocalRuntimeHost.from_dict(raw)  # round-trip
```

---

## What this PR explicitly does NOT do

- No Handoff Envelope v2 redesign (PR-31).
- No Mesh Membership contract (PR-32).
- No Mesh Session contract (PR-33).
- No local takeover / adopt-session execution path (PR-34).
- No full registration flow rewrite.
- No UI/dashboard redesign.
- No persistence / streaming redesign.

---

## Relationship to other PRs

```
PR-25  Execution Trace Contract
PR-26  Projection Assembly Governance
PR-27  Runtime Governance Snapshot
PR-28  Execution Policy Alignment Surface
PR-29  Unified Registered Runtime Device Contract  ←── device identity
PR-30  Local Runtime Host Contract (this PR)        ←── host posture
PR-31  Unified Handoff Envelope v2                  (future)
PR-32  Mesh Membership Contract                     (future)
PR-33  Mesh Session Contract                        (future)
PR-34  Target Runtime Local Takeover Path           (future)
```

PR-30 is the stable contract that PR-31, PR-32, and PR-33 will target.
Future handoff and mesh work should consume `LocalRuntimeHost` rather than
inferring local-runtime-host posture ad hoc from device or bridge structures.

# Galaxy Gateway — Transport & Routing Substrate Boundary

> **Authoritative reference for PR-10.**
> This document defines the architectural contract for the `galaxy_gateway` package.

---

## 1. Role of the Gateway Layer

The `galaxy_gateway` package is the **transport and routing substrate** of the
Galaxy system.  Its job is to:

- Accept device connections (WebSocket, HTTP, WebRTC, P2P relay).
- Parse and normalise protocol frames (AIP v3+).
- Route dispatched task envelopes to the correct connected device.
- Relay transport-level events back into the core layer.
- Write-through gateway-originated device state to the canonical
  `UnifiedDeviceManager` (UDM) via `ssot.py`.

The gateway is **not** a decision-maker for system-level concerns.  It is a
pipe, not a brain.

---

## 2. Gateway Responsibilities

| Responsibility | Owning module(s) |
|---|---|
| Device ingress / egress | `websocket_handler.py` |
| WebSocket session lifecycle | `websocket_handler.py`, `device_router.py` |
| AIP v3+ protocol framing & parsing | `protocol/`, `aip_protocol_v2.py` |
| Local routing & task dispatch | `routing/`, `device_router.py` |
| Send-to-device / transport fallback | `routing/dispatch.py`, `smart_transport_router.py` |
| Relay / P2P / WebRTC transport | `p2p_connector.py`, `webrtc_proxy.py` |
| Gateway-side UDM write-through | `ssot.py` |
| Cross-device convenience coordination | `cross_device_coordinator.py` |

---

## 3. Gateway Non-Responsibilities

The gateway is **not** the canonical authority for any of the following.
New logic for these concerns **must not** be added to `galaxy_gateway/`.
Instead, implement them in the canonical `core/` layer and have the gateway
call or delegate to that layer.

| Concern | Canonical Authority |
|---|---|
| **Entry-mode decisioning** | `core/` orchestration layer |
| **Orchestration eligibility** | `core/orchestration/` + `core/device_selection/canonical_device_selector.py` |
| **Formation / session truth** | `core/unified/device_manager.py` (UDM) |
| **Global readiness truth** | `core/system_orchestrator.py` |
| **Final canonical capability truth** | `core/capability_bus.py` via UDM |

---

## 4. Module-level Boundary Sentinels

Each key gateway module exposes a module-level string sentinel to make the
boundary machine-queryable and import-graph inspectable.

| Module | Sentinel constant |
|---|---|
| `websocket_handler.py` | `WEBSOCKET_HANDLER_TRANSPORT_AUTHORITY` |
| `device_router.py` | `DEVICE_ROUTER_TRANSPORT_AUTHORITY` |
| `cross_device_coordinator.py` | `CROSS_DEVICE_COORDINATOR_TRANSPORT_AUTHORITY` |
| `ssot.py` | `GATEWAY_SSOT_WRITE_AUTHORITY` |

Importing one of these sentinels at a call site signals that the import is
consuming transport/routing primitives only — not canonical readiness,
orchestration eligibility, or formation truth.

---

## 5. Data-flow Reference

```
External Devices
      │  (WebSocket / HTTP / WebRTC / P2P)
      ▼
┌──────────────────────────────────────────────────────────┐
│                galaxy_gateway  (transport substrate)      │
│                                                          │
│  websocket_handler  ──►  device_router  ──►  routing/   │
│                                                          │
│  ssot.py  (write-through to UDM — gateway events only)  │
│  cross_device_coordinator  (convenience coordination)    │
└──────────────────────────┬───────────────────────────────┘
                           │  delegates all higher-level
                           │  decisions to ▼
┌──────────────────────────────────────────────────────────┐
│                  core/  (canonical authority)             │
│                                                          │
│  command_router  ·  orchestration/  ·  UDM               │
│  system_orchestrator  ·  capability_bus                  │
└──────────────────────────────────────────────────────────┘
```

The gateway **receives** transport events and **delegates** all higher-level
decisions (readiness, eligibility, formation, entry-mode) upstream to
`core/`.  It must never become a secondary source of truth for those concerns.

---

## 6. Evolution Guidelines

When adding new logic to `galaxy_gateway/`:

1. **Ask**: does this logic need to know whether a device is
   _orchestration-eligible_ or whether the system is _ready_?
   - If yes → the logic belongs in `core/`, not here.
   - If no  → it is safe to add here as transport/routing logic.

2. **Never** introduce a new API that returns readiness, eligibility, or
   formation state from within `galaxy_gateway/`.  Surface those facts from
   `core/` endpoints instead.

3. **Always** write device-state mutations through `ssot.py` so that UDM
   remains the single canonical write target.

4. **Keep `cross_device_coordinator.py`** scoped to low-level cross-device
   transport tasks (clipboard, file, media, notification).  Any new
   cross-device _orchestration_ logic belongs in `core/orchestration/`.

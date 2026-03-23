# Unified Device Registration, Runtime Presence, and Multi-Device Participation — V1 Architecture Spec

**Status:** Canonical — PR-1 Final Architecture Baseline  
**Version:** 1.0  
**Owner:** core/unified/device_manager.py  
**Scope:** Device registration, runtime presence, single-device projection, participation/coordination, top-level multi-device projection

---

## Executive Summary

This document is the **normative V1 architecture baseline** for all device registration, runtime presence, and multi-device participation semantics in the Galaxy / OpenClawd system.

It establishes a single, unambiguous authority chain:

1. **`UnifiedDeviceManager` (UDM)** is the **only canonical write SSOT** for device registration and mutable device state.
2. **`RegisteredRuntimeDevice`** is the **only canonical single-device read contract**.
3. **`MultiDeviceRuntimeProjection`** is the **only canonical top-level multi-device runtime projection**.

All existing registration paths — REST API, Android bridge, DeviceAgentManager, DeviceRouter, DeviceRegistry — remain in operation but are reclassified under a compatibility-first unification model. None of them retain independent status as a parallel SSOT. All of them must ultimately converge on UDM as the write authority and project through `RegisteredRuntimeDevice` as the read contract.

This specification is UI-agnostic. No UI or dashboard component is required for this architecture to be valid or useful. Any future UI or observability surface should consume the canonical read model rather than driving its design.

---

## Current Repository Reality

The repository contains partial convergence toward the unified model but retains multiple modules that could be mistaken for independent device-state authorities. This spec resolves that ambiguity by explicitly classifying each module.

### Modules that represent convergence progress

| Module | Role |
|--------|------|
| `core/unified/device_manager.py` | Canonical write SSOT (UDM) |
| `contracts/registered_runtime_device.py` | Canonical single-device read contract |
| `contracts/multi_device_runtime_projection.py` | Canonical top-level multi-device read projection |
| `core/routes/devices.py` | Standard public registration API |
| `core/legacy_adapters/device_agent_manager_adapter.py` | Adapter: DeviceAgentManager → UDM |

### Modules that must be explicitly classified

| Module | Classification | Notes |
|--------|---------------|-------|
| `core/device_registry.py` | Legacy-compatible | See §Role Classifications |
| `core/device_agent_manager.py` | Adapted | See §Role Classifications |
| `galaxy_gateway/android_bridge.py` | Adapted (transport adapter) | See §Role Classifications |
| `galaxy_gateway/device_router.py` | Runtime-only | See §Role Classifications |
| `galaxy_gateway/cross_device_coordinator.py` | Orchestration-only | See §Role Classifications |
| `core/swarm_coordinator.py` | Orchestration-only | See §Role Classifications |
| `nodes/Node_71_MultiDeviceCoordination/` | Future normalization target | See §Role Classifications |

---

## Canonical Authority Chain

```
All registration inputs (REST / WebSocket / agent lifecycle / legacy)
                          │
                          ▼
          ┌───────────────────────────────┐
          │   UnifiedDeviceManager (UDM)  │   core/unified/device_manager.py
          │   Canonical write SSOT        │   Single mutable device state store
          └───────────────┬───────────────┘
                          │  read projection
                          ▼
          ┌───────────────────────────────┐
          │   RegisteredRuntimeDevice     │   contracts/registered_runtime_device.py
          │   Canonical single-device     │   Stable, serialisable read contract
          │   read contract               │   per device
          └───────────────┬───────────────┘
                          │  aggregated into
                          ▼
          ┌───────────────────────────────┐
          │ MultiDeviceRuntimeProjection  │   contracts/multi_device_runtime_projection.py
          │ Canonical top-level           │   Aggregates all device and multi-device
          │ multi-device read projection  │   runtime state into a single snapshot
          └───────────────────────────────┘
```

**Rule:** No module other than UDM may be treated as a canonical write authority for device registration or mutable device state. Any module that writes device state must do so by calling UDM methods (`register_device`, `upsert_device_state`, `update_device_status`, `heartbeat`).

---

## Five-Layer Model

### Layer 1 — Canonical Registration

**Authority:** `UnifiedDeviceManager` (`core/unified/device_manager.py`)

Canonical registration is the act of writing a device's persistent identity and initial mutable state into the system's single write SSOT. It produces a device record that can be read, updated, and projected.

All registration paths — regardless of transport or origin — must write through UDM. The following operations are the canonical write API:

| Operation | UDM method |
|-----------|-----------|
| Initial registration | `register_device(device: UnifiedDevice)` |
| Upsert / patch state | `upsert_device_state(device_id, patch, source)` |
| Status update | `update_device_status(device_id, status)` |
| Heartbeat | `heartbeat(device_id)` |
| Unregister | `unregister_device(device_id)` |

**Registration paths (classified):**

| Path | Transport / Origin | Classification |
|------|--------------------|---------------|
| `POST /api/v1/devices/register` via `core/routes/devices.py` | HTTP REST | Canonical external registration entrypoint |
| `galaxy_gateway/android_bridge.py` WebSocket register | AIP v3 WebSocket | Transport registration adapter |
| `core/device_agent_manager.py` agent lifecycle register | Internal agent lifecycle | Agent lifecycle registration adapter |
| `galaxy_gateway/device_router.py` runtime attach | WebSocket runtime connection | Runtime connection registration adapter |
| `core/device_registry.py` legacy register/update | Legacy internal | Legacy-compatible registration and indexing adapter |

### Layer 2 — Runtime Presence

**Authority:** `galaxy_gateway/device_router.py` (runtime connection tracking only)

Runtime presence is the live connection and session state of a device: whether it currently has an active WebSocket connection, what session it is participating in, and whether it is reachable for task dispatch.

Runtime presence is **separate from canonical registration**. A device may be canonically registered but not runtime-present (offline). A runtime-present device must already be canonically registered.

Runtime presence state flows into the canonical read contract via the `connection` and `session_presence` fields of `RegisteredRuntimeDevice`.

**Key principle:** `DeviceRouter` tracks runtime connections for routing purposes. It does not define canonical device identity. It must not be used as a substitute for UDM.

### Layer 3 — Canonical Single-Device Read Model

**Authority:** `contracts/registered_runtime_device.py` (`RegisteredRuntimeDevice`)

`RegisteredRuntimeDevice` is the single canonical read contract for a device. It answers: *"What is this device, what can it do, and what is its current runtime state?"*

It normalises the fragmented device representations across UDM, DeviceRegistry, DeviceRouter, and AndroidBridge into a stable, serialisable schema. It does not replace any of those representations; it projects above them.

**Adapter functions:**

| Function | Source model | Origin module |
|----------|-------------|---------------|
| `from_udm_device(device)` | `UnifiedDevice` | `core/unified/device_manager.py` |
| `from_router_device(device)` | `Device` (gateway wrapper) | `galaxy_gateway/device_router.py` |
| `from_android_registration(data)` | Android registration dict | `galaxy_gateway/android_bridge.py` |
| `from_device_registry_record(device)` | `DeviceModel` | `core/device_registry.py` |

**Rule:** All cross-module consumers that need a device's current state should read `RegisteredRuntimeDevice`, not the internal models of UDM, DeviceRouter, or DeviceRegistry directly.

### Layer 4 — Participation and Coordination Semantics

**Authorities:** `galaxy_gateway/cross_device_coordinator.py`, `core/swarm_coordinator.py`, `nodes/Node_71_MultiDeviceCoordination/`

Participation semantics describe the conditions under which a device is eligible to take part in cross-device tasks, mesh sessions, or orchestrated multi-device workloads.

**Eligibility definitions:**

| Eligibility state | Definition |
|-------------------|-----------|
| **Registered** | Device has a canonical record in UDM. Minimum condition for any participation. |
| **Runtime-present** | Device currently has an active runtime connection (tracked by DeviceRouter). |
| **Routable** | Device is registered, runtime-present, and has a resolvable dispatch endpoint. |
| **Cross-device eligible** | Device is routable and supports remote handoff (`autonomy.supports_remote_handoff = true`). |
| **Orchestration-eligible** | Device is cross-device eligible and has been accepted into an active mesh or coordination session. |
| **Mesh / session participant** | Device is currently an active member of a `MeshSession` or coordination session. |

These eligibility states form a strict hierarchy. A device cannot be orchestration-eligible without first being routable.

**Module roles in participation:**

| Module | Participation role |
|--------|-------------------|
| `galaxy_gateway/cross_device_coordinator.py` | Routes cross-device eligibility decisions; does not own canonical state |
| `core/swarm_coordinator.py` | Coordinates multi-agent orchestration; reads from canonical contracts |
| `nodes/Node_71_MultiDeviceCoordination/` | Implements multi-device coordination logic; must read from canonical contracts, not from internal registries |

### Layer 5 — Canonical Top-Level Multi-Device Runtime Projection

**Authority:** `contracts/multi_device_runtime_projection.py` (`MultiDeviceRuntimeProjection`)

`MultiDeviceRuntimeProjection` is the single canonical read projection of the full multi-device runtime state. It aggregates devices (Layer 3), sessions, handoffs, dispatch decisions, coordination state, and merged results into a single serialisable snapshot.

It sits **above** `RegisteredRuntimeDevice`, not beside it. The relationship is:

```
MultiDeviceRuntimeProjection     ← top-level aggregated projection
  └── runtime_devices[]
        └── RegisteredRuntimeDevice   ← per-device canonical contract
```

**Rule:** All cross-module consumers that need the full multi-device runtime view should read `MultiDeviceRuntimeProjection` via `GET /api/v1/projection/runtime/multi-device` or via `build_multi_device_runtime_projection(...)`. They should not assemble this view themselves from individual route payloads.

---

## Role Classification of All In-Scope Modules

### `core/unified/device_manager.py` — `UnifiedDeviceManager`
**Classification:** Canonical

The only canonical write SSOT for device registration and mutable device state. All registration paths must write through this module. No other module may act as a parallel mutable device state authority.

### `core/routes/devices.py`
**Classification:** Canonical (external registration entrypoint)

The standard public HTTP REST interface for device registration. Calls `UnifiedDeviceManager` directly. This is the preferred external API for new integrations.

### `core/device_agent_manager.py` — `DeviceAgentManager`
**Classification:** Adapted

An agent-backed device lifecycle compatibility layer. It receives agent lifecycle events (connect, disconnect, heartbeat) and maps them to canonical UDM patches via the adapter at `core/legacy_adapters/device_agent_manager_adapter.py`. It does not define an independent canonical device schema. It is in scope, supported, and formally classified.

**V1 role:** Agent lifecycle registration adapter. Writes to UDM via adapter. Does not act as SSOT.

### `core/device_registry.py`
**Classification:** Legacy-compatible

A legacy compatibility registration and indexing layer. It may still be called by older code paths for indexing, persistence, or tag/group lookups. It must not be treated as a parallel canonical write authority. All canonical state reads should be directed to UDM or `RegisteredRuntimeDevice`.

**V1 role:** Legacy compatibility registry. In scope. May be retained as an indexing/persistence layer as long as it does not shadow UDM canonical state. Future normalization target for cleanup.

### `galaxy_gateway/android_bridge.py` — `AndroidBridge`
**Classification:** Adapted (transport adapter)

Handles AIP v3 WebSocket connections from Android devices. Translates Android registration messages into canonical UDM registrations. It is a transport registration adapter, not a canonical write authority.

**V1 role:** Transport registration adapter. Bridges Android WebSocket protocol to canonical UDM registration. Does not retain independent device state.

### `galaxy_gateway/device_router.py` — `DeviceRouter`
**Classification:** Runtime-only

Manages live WebSocket connections and runtime routing for connected devices. Tracks which devices are currently connected and routes commands to them. It does not define canonical device identity and must not be used as a substitute for UDM.

**V1 role:** Runtime connection and routing layer. Tracks live connections for dispatch. Feeds runtime presence data into `RegisteredRuntimeDevice` via `from_router_device()`.

### `galaxy_gateway/cross_device_coordinator.py` — `CrossDeviceCoordinator`
**Classification:** Orchestration-only

Routes cross-device task dispatch and eligibility decisions. Reads from canonical contracts to determine which devices are cross-device eligible. Does not hold canonical device state.

**V1 role:** Cross-device dispatch and coordination consumer. Reads canonical contracts. Does not act as SSOT.

### `core/swarm_coordinator.py` — `SwarmCoordinator`
**Classification:** Orchestration-only

Coordinates multi-agent and multi-device workloads. Reads from canonical contracts (device eligibility, session state) to plan and execute distributed tasks. Does not hold canonical device state.

**V1 role:** Multi-agent orchestration layer. Reads canonical contracts. Does not act as SSOT.

### `nodes/Node_71_MultiDeviceCoordination/`
**Classification:** Future normalization target

Implements multi-device coordination node logic. Currently may maintain internal device representations or routing state that partially overlaps with canonical contracts. Must be progressively aligned to read exclusively from `RegisteredRuntimeDevice` and `MultiDeviceRuntimeProjection` rather than from internal registries.

**V1 role:** Multi-device coordination implementation. In scope. Targeted for progressive normalization in follow-up PRs (see §Migration Intent).

### `contracts/registered_runtime_device.py` — `RegisteredRuntimeDevice`
**Classification:** Canonical (single-device read contract)

The only canonical single-device read contract. Provides a stable, serialisable view of a device's identity, capabilities, connection state, autonomy, session presence, and participation hints. All cross-module consumers that need a device's current state should read this contract.

### `contracts/multi_device_runtime_projection.py` — `MultiDeviceRuntimeProjection`
**Classification:** Canonical (top-level multi-device read projection)

The only canonical top-level multi-device runtime projection. Aggregates all device, session, handoff, dispatch, coordination, and result state into a single coherent snapshot. Sits above `RegisteredRuntimeDevice` in the contract hierarchy.

---

## Canonical Information Domains

| Domain | Canonical owner | Notes |
|--------|----------------|-------|
| **Identity** | `UnifiedDeviceManager` → `RegisteredRuntimeDevice` | device_id, device_name, owner_id, platform, form_factor, device_type |
| **Registration** | `UnifiedDeviceManager` | canonical write; all registration paths converge here |
| **Runtime presence** | `DeviceRouter` → `RegisteredRuntimeDevice.connection` | live connection state; feeds into canonical read contract |
| **Capability** | `UnifiedDeviceManager` → `RegisteredRuntimeDevice.capabilities` | canonical capability profile; sourced from registration, updated via UDM |
| **Participation** | `RegisteredRuntimeDevice.participation_hints` + eligibility rules | mesh roles, groups, tags, cross-device eligibility |
| **Coordination / topology** | `MultiDeviceRuntimeProjection` | session topology, mesh memberships, coordinator state |

---

## Normative Rules

**R1. UDM is the only canonical write SSOT.**  
All code paths that create, update, or delete device state must call `UnifiedDeviceManager` methods. Direct mutation of internal device dicts (e.g., `_devices[id] = ...`) is prohibited and blocked by `scripts/audit_udm_write_paths.py`.

**R2. `RegisteredRuntimeDevice` is the only canonical single-device read contract.**  
All cross-module consumers that need a device's current state must read `RegisteredRuntimeDevice`, not the internal models of UDM, DeviceRouter, DeviceRegistry, or any other module.

**R3. `MultiDeviceRuntimeProjection` is the only canonical top-level multi-device read projection.**  
All consumers that need the full multi-device runtime view must use `MultiDeviceRuntimeProjection`. They must not assemble this view themselves from individual contract modules.

**R4. All registration paths must converge on UDM.**  
REST, WebSocket, agent lifecycle, and legacy registration paths are all valid entry points. All of them must write to UDM. None of them may act as a parallel SSOT.

**R5. `MultiDeviceRuntimeProjection` sits above `RegisteredRuntimeDevice`, not beside it.**  
The projection aggregates per-device contracts. The per-device contract is the unit. The projection is the aggregation.

**R6. The architecture is UI-agnostic.**  
No UI or dashboard component is required for this architecture to be valid. Any future UI is a downstream consumer of the canonical read model. It does not drive the architecture's design.

**R7. Participation eligibility is ordered.**  
A device must satisfy lower eligibility conditions before it can satisfy higher ones: registered → runtime-present → routable → cross-device eligible → orchestration-eligible → mesh/session participant.

---

## Migration Classification Summary

| Module | Migration classification |
|--------|-------------------------|
| `core/unified/device_manager.py` | Canonical |
| `contracts/registered_runtime_device.py` | Canonical |
| `contracts/multi_device_runtime_projection.py` | Canonical |
| `core/routes/devices.py` | Canonical |
| `core/device_agent_manager.py` | Adapted |
| `galaxy_gateway/android_bridge.py` | Adapted |
| `galaxy_gateway/device_router.py` | Runtime-only |
| `galaxy_gateway/cross_device_coordinator.py` | Orchestration-only |
| `core/swarm_coordinator.py` | Orchestration-only |
| `core/device_registry.py` | Legacy-compatible |
| `nodes/Node_71_MultiDeviceCoordination/` | Future normalization target |

---

## Migration Intent and Follow-Up Implementation Program

This spec is documentation-first. The following implementation program is defined for follow-up PRs. This spec does not implement any of these steps.

| Step | Target | Classification outcome |
|------|--------|----------------------|
| PR-2 | Ensure all `DeviceAgentManager` writes go through UDM adapter; confirm no direct state writes bypass UDM | Adapted → Fully adapted |
| PR-3 | Align `DeviceRegistry` reads to serve as index/cache only; block new canonical writes directly to DeviceRegistry | Legacy-compatible → Index-only adapter |
| PR-4 | Confirm `AndroidBridge` writes flow to UDM; remove any internal device dict if present | Adapted → Fully adapted |
| PR-5 | Confirm `DeviceRouter` does not hold canonical state; ensure `from_router_device()` is the only read bridge | Runtime-only → Confirmed runtime-only |
| PR-6 | Align `CrossDeviceCoordinator` and `SwarmCoordinator` to read exclusively from canonical contracts | Orchestration-only → Confirmed orchestration-only |
| PR-7 | Progressively normalize `Node_71_MultiDeviceCoordination` to read from `RegisteredRuntimeDevice` and `MultiDeviceRuntimeProjection` | Future normalization target → Adapted |

---

## Acceptance Criteria

- [ ] The repo has one final V1 architecture spec naming UDM as canonical write SSOT.
- [ ] The spec names `RegisteredRuntimeDevice` as the canonical single-device read contract.
- [ ] The spec names `MultiDeviceRuntimeProjection` as the canonical top-level multi-device read projection.
- [ ] `DeviceRegistry`, `DeviceAgentManager`, `AndroidBridge`, `DeviceRouter`, `CrossDeviceCoordinator`, `SwarmCoordinator`, and `Node_71` are all explicitly role-classified.
- [ ] The architecture docs do not frame dashboard/UI as the design target.
- [ ] Migration docs reflect canonical-vs-adapter framing.
- [ ] `MultiDeviceRuntimeProjection` is defined as sitting above `RegisteredRuntimeDevice`, not beside it.

---

## References

- `core/unified/device_manager.py` — UDM canonical write SSOT
- `contracts/registered_runtime_device.py` — canonical single-device read contract
- `contracts/multi_device_runtime_projection.py` — canonical top-level multi-device projection
- `core/routes/devices.py` — standard public registration API
- `core/legacy_adapters/device_agent_manager_adapter.py` — DeviceAgentManager → UDM adapter
- `docs/architecture/unified_system_contract.md` — broader system ingress/state/event rules
- `docs/architecture/module_ownership_map.md` — full module ownership map
- `docs/migration/unified_migration_matrix.md` — migration path classifications
- `docs/REGISTERED_RUNTIME_DEVICE_CONTRACT.md` — RegisteredRuntimeDevice contract documentation
- `docs/UNIFIED_MULTI_DEVICE_RUNTIME_PROJECTION.md` — MultiDeviceRuntimeProjection documentation
- `scripts/audit_udm_write_paths.py` — UDM write path auditor

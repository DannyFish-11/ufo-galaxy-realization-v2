# Truth / Projection / Outward Truth Convergence Map

> **Full re-audit pass** — fresh standalone review produced as part of the complete
> dual-repo architecture re-audit.
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android`.
>
> Companion documents: `DUAL_REPO_FULL_REAUDIT.md`, `DUAL_REPO_GAP_MATRIX.md`.

---

## Purpose

This document answers the question:

> *How far has multi-device truth convergence progressed? Are mesh/session/formation/
> participation/readiness/topology surfaces converging into outward truth, or do
> parallel projection paths still exist? What is the relationship between center-side
> truth and Android authoritative host-facing projections? Is `MultiDeviceRuntimeProjection`
> canonical/stable or still transitional?*

---

## 1. Truth surface inventory

### 1.1 Primary truth surfaces (V2 side)

| Surface | Module | Purpose | Status |
|---------|--------|---------|--------|
| `TruthIntegrationLayer` | `core/truth_integration_layer.py` | Canonical convergence point: fuses device identity, connection, capability, participation, and readiness into a unified truth record | **Wired from canonical paths; consumer coverage incomplete** |
| `UnifiedDeviceManager` (UDM) | `core/unified/device_manager.py` | Canonical SSOT for device identity and mutable state | **Stable** |
| `UnifiedConnectionManager` (UCM) | `core/unified/connection_manager.py` | Canonical SSOT for transport presence and connection lifecycle | **Stable** |
| `CapabilityAssimilationLayer` | `core/capability_assimilation.py` | Canonical capability registration for all participant types (nodes + devices) | **Stable** |
| `NetworkTopologyRuntime` | `core/network_topology_runtime.py` | Runtime network topology and path state | **Partially populated** |
| `MultiDeviceRuntimeProjection` | `contracts/multi_device_runtime_projection.py` | Top-level canonical multi-device read model | **Contract-stable; merged_results partially populated** |
| `RegisteredRuntimeDevice` | `contracts/registered_runtime_device.py` | Canonical single-device read contract | **Stable** |
| `ProjectionSurfaceBridge` | `core/projection_surface_bridge.py` | Convergence adapter: enriches projection with canonical runtime state | **Wired from main endpoints; not all paths call it** |
| `compile_outward_truth()` | `core/outward_truth.py` | Compiles the outward-facing truth snapshot consumed by projection endpoints | **Called from main projection endpoints; fallback paths return null** |

### 1.2 Secondary / display projection surfaces

| Surface | Module | Independence from canonical chain | Gap |
|---------|--------|----------------------------------|-----|
| Desktop status board (`status_board_v2`) | `desktop_projection/` | **Partially independent** — assembles some runtime views without consuming `NetworkTopologyRuntime` | TRUTH-002 |
| Desktop projection engine | `desktop_projection/projection_engine.py` | **Gated** — must delegate to `ProjectionSurfaceBridge` | Delegation enforcement unconfirmed |
| Status board V2 topology map | `dashboard/` | Independent topology representation | Does not always consume `NetworkTopologyRuntime` |

### 1.3 Android-side truth surfaces

| Surface | Repo | Purpose | Convergence with V2 |
|---------|------|---------|---------------------|
| Session snapshot | `ufo-galaxy-android` | Local session state persisted on device | **No reconciliation protocol** |
| Target readiness state | `ufo-galaxy-android` | Android-side assessment of device readiness | **No reconciliation protocol** |
| Current task phase | `ufo-galaxy-android` | Android-side task lifecycle state | **Silent divergence risk** |
| `AgentLocalRuntime` state | `ufo-galaxy-android` | Local runtime loop state | **No reconciliation protocol** |

---

## 2. Convergence chain trace

### 2.1 Canonical convergence chain (center side)

```
UDM (identity + state)              UCM (connection)
    │                                   │
    └───────────────┬───────────────────┘
                    │
                    ▼
        TruthIntegrationLayer           CapabilityAssimilationLayer
              (canonical fusion)              (capability graph)
                    │                              │
                    └──────────────┬───────────────┘
                                   │
                                   ▼
                        RegisteredRuntimeDevice
                        (single-device read contract)
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼               ▼
              BodyMeshRegistry  formation_resolver  NetworkTopologyRuntime
              (mesh sessions)   (formation groups)  (network topology)
                    │              │               │
                    └──────────────┴───────────────┘
                                   │
                                   ▼
                    MultiDeviceRuntimeProjection
                    (top-level read model)
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                              ▼
         ProjectionSurfaceBridge         compile_outward_truth()
         enrich_runtime_projection()              │
                    │                             │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                        Projection API endpoints
                        /api/v1/projection/runtime
                        /api/v1/projection/outward-truth
```

### 2.2 Where the chain breaks

| Break point | Gap | Severity |
|-------------|-----|---------|
| Not all projection endpoint code paths call `enrich_runtime_projection()` | TRUTH-001 | MEDIUM |
| `MultiDeviceRuntimeProjection.merged_results` not fully sourced from canonical state | ADMIT-002, TRUTH-004 | MEDIUM |
| Desktop status board assembles independent topology views | TRUTH-002 | MEDIUM |
| `compile_outward_truth()` fallback paths return `outward_truth: null` | TRUTH-001 | MEDIUM |
| Android local state has no reconciliation protocol with V2 outward truth | TRUTH-005 | MEDIUM |
| Multi-model topology (ContinuumState / TopologyRoutePlan) not reflected in unified truth | TRUTH-003 | MEDIUM |
| `BodyMeshRegistry` data in `MultiDeviceRuntimeProjection` — adapter coverage unconfirmed | ADMIT-004 | LOW |

---

## 3. Component-by-component convergence status

### 3.1 TruthIntegrationLayer

| Field | Value |
|-------|-------|
| **Module** | `core/truth_integration_layer.py` |
| **Role** | Canonical convergence point for all device truth reads |
| **Status** | **Wired** from device registration, heartbeat, and capability report paths |
| **Gap** | Not all truth consumers use it. Some status/projection surfaces still query UDM/UCM directly. |
| **Test coverage** | 28 tests confirm the contract |

### 3.2 MultiDeviceRuntimeProjection

| Field | Value |
|-------|-------|
| **Module** | `contracts/multi_device_runtime_projection.py` |
| **Role** | Top-level multi-device read model; intended canonical output of multi-device truth |
| **Status** | **Contract-stable** — the model is well-defined and not changing |
| **Canonical or transitional?** | **Canonical** — it is the designated output contract. Transitional only in the sense that `merged_results` body is not yet fully populated from all canonical chain inputs. |
| **Gap** | `merged_results` body: enriched by PR-522 but not confirmed as fully sourced from canonical state. Formation data, mesh session data, and per-device readiness may still be assembled from side channels. |

### 3.3 ProjectionSurfaceBridge

| Field | Value |
|-------|-------|
| **Module** | `core/projection_surface_bridge.py` |
| **Role** | Convergence adapter — enriches runtime projection with canonical state |
| **Status** | **Wired** from main projection endpoints (PR-511) |
| **Gap** | Not all projection endpoint code paths call `enrich_runtime_projection()`. Fallback paths may return unenriched projections. |

### 3.4 compile_outward_truth()

| Field | Value |
|-------|-------|
| **Module** | `core/outward_truth.py` |
| **Role** | Compiles the outward-facing truth snapshot |
| **Status** | **Called** from main projection endpoint code paths |
| **Gap** | Exception fallback paths return `outward_truth: null`. Under error conditions, the API may silently return no truth. |

### 3.5 Desktop projection surfaces

| Field | Value |
|-------|-------|
| **Modules** | `desktop_projection/`, `status_board_v2` |
| **Role** | Display representation for operator/user interfaces |
| **Status** | **Partially independent** |
| **Gap** | Some views assemble topology/route representations independently rather than consuming the canonical chain through `NetworkTopologyRuntime`. This means displayed topology may diverge from canonical truth under runtime state changes. |

---

## 4. Android-side truth: the reconciliation gap

### 4.1 Current state

Android maintains local runtime state that is authoritative on-device but has no
reconciliation protocol with V2 outward truth:

| Android state | V2 equivalent | Reconciliation |
|---------------|--------------|----------------|
| Session snapshot (local SQLite) | `BodyMeshRegistry` session record | **None** |
| Target readiness assessment | `RegisteredRuntimeDevice.readiness_state` | **None** |
| Current task phase | `TaskGraphRuntime` node state | **None** |
| `AgentLocalRuntime` execution state | `CommandRouter` tracked task | **None** |

### 4.2 Divergence risk

V2 may project a device as "active in task" while Android has already:
- Completed the task locally
- Failed the task locally
- Cancelled the task locally (after `task_cancel` — see ANDROID_PROTOCOL_MATURITY_MATRIX)
- Lost its WebSocket connection temporarily

The Android side re-connects and re-registers, but there is no mechanism to reconcile
local execution state with V2's in-flight task state after reconnection.

### 4.3 Design decision required

Before any implementation: **Does V2 outward truth supersede Android local state, or
are they independent with explicit sync events?**

Options:
- **V2 authoritative**: Android local state is advisory; V2 drives the canonical view.
  Android sync events update V2 but V2 truth gates all external queries.
- **Android authoritative for device scope**: Android is authoritative for its own
  device-local state; V2 is authoritative for multi-device coordination. Sync is
  explicit via result uplink and signal emission.
- **Explicit reconciliation protocol**: A heartbeat-like sync message carries task
  phase, session state, and readiness deltas; both sides apply conflict resolution.

This decision is **TRUTH-005** and **Q4** in `DUAL_REPO_FULL_REAUDIT.md`.

---

## 5. Mesh / session / formation truth convergence

### 5.1 Mesh session truth

`MeshSession` state (`FORMING → ACTIVE → COMPLETING → DONE`) is declared in
`contracts/mesh_session.py` and stored in `BodyMeshRegistry`. It is included in
`MultiDeviceRuntimeProjection`. However:

- No live runtime engine drives `MeshSessionStatus` transitions
- The `MeshSessionCoordinator` is populated at construction time; not updated dynamically
- Mesh session truth is therefore **construction-time static**, not live

### 5.2 Formation truth

Formation resolution produces a `DeviceFormationGroup` at dispatch time. This is
included in `MultiDeviceRuntimeProjection`. Formation is static — once resolved,
no runtime process reshapes it. Formation truth is **dispatch-time static**.

### 5.3 Participation / readiness truth

Device participation eligibility and readiness are assessed at dispatch time via
the admissibility chain. They are reflected in `RegisteredRuntimeDevice.readiness_state`.
`TruthIntegrationLayer` fuses readiness. However, readiness state is not continuously
updated between dispatch events — it reflects the last admissibility assessment.

---

## 6. Multi-model topology truth gap

`ContinuumState` and `TopologyRoutePlan` express multi-model intelligent routing
preferences and topology. There is no canonical runtime authority for the model
domain equivalent to `NetworkTopologyRuntime` for devices. Model routing decisions
are not reflected in `MultiDeviceRuntimeProjection` or `compile_outward_truth()`.
This is TRUTH-003 (MEDIUM).

---

## 7. Convergence progress summary

| Domain | Convergence level | Key gap |
|--------|------------------|---------|
| Device identity (UDM → TIL → RegisteredRuntimeDevice) | **High** | Consumer coverage incomplete |
| Device connection (UCM → TIL) | **High** | Same |
| Device capability (CapabilityAssimilation → capability graph) | **High** | Advisory-only at dispatch |
| Device readiness (admissibility chain → RegisteredRuntimeDevice) | **Medium** | Not continuously updated |
| Multi-device top-level (MultiDeviceRuntimeProjection) | **Medium** | merged_results partially populated |
| Mesh session truth | **Low** | No live session engine |
| Formation truth | **Medium** | Static; no dynamic rebalance |
| Desktop display truth | **Medium** | Partially independent |
| Android local truth | **Low** | No reconciliation protocol |
| Multi-model topology truth | **Low** | No canonical authority |

---

## 8. Answer to acceptance criterion 6

**AC6 — How far has truth/projection convergence progressed?**

> **Moderate progress on the center-side canonical chain; significant gaps remain
> for Android local state, mesh session live truth, and multi-model topology.**
>
> The device identity + connection + capability path (UDM → UCM → TruthIntegrationLayer →
> RegisteredRuntimeDevice) is the most mature and correctly structured. The top-level
> read model (`MultiDeviceRuntimeProjection`) is contract-stable and is the designated
> output contract.
>
> Key remaining gaps:
> 1. Not all projection endpoints call `enrich_runtime_projection()` — some fallback paths return null truth.
> 2. `MultiDeviceRuntimeProjection.merged_results` is partially populated.
> 3. Desktop status board surfaces are partially independent from the canonical chain.
> 4. Android local state (session, readiness, task phase) has no reconciliation protocol with V2 outward truth.
> 5. Mesh session truth is construction-time static, not live.
> 6. Multi-model topology is not reflected in the unified truth surface.

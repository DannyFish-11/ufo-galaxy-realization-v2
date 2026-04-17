# Re-Audit: Scheduling and Authority Map V2

> **Fresh re-audit pass** — `DannyFish-11/ufo-galaxy-realization-v2` and
> `DannyFish-11/ufo-galaxy-android`.
>
> Supersedes `docs/UNIFIED_SCHEDULING_AUTHORITY_MAP.md`.
> Companion: `docs/REAUDIT_FRESH_PASS_2.md`

---

## Purpose

This document provides a complete, current authority chain map covering:
- Where scheduling and routing decisions are made
- Which authority is canonical at each layer
- Where convergence between node capabilities and device capabilities exists
- Where gaps remain (as of this re-audit)

---

## Top-level authority chain

```
User request / agent invocation
    │
    ▼
OpenClawd._dispatch_device()
  OR e2e_orchestrator.process_user_input()
    │  (entry normalisation; picks up intent + required_capabilities)
    ▼
CommandRouter.route_envelope()      ← SOLE canonical cross-device dispatcher
    │
    │  ┌─────────────────────────────────────────────────────┐
    │  │  REGISTRATION TIER (unified, canonical)             │
    │  │  CapabilityAssimilationLayer.assimilate_device()    │
    │  │  CapabilityAssimilationLayer.register_node()        │
    │  │  → both produce AssimilationRecord                  │
    │  │  → unified capability graph                         │
    │  └─────────────────────────────────────────────────────┘
    │
    │  [GAP SCHED-001]: query_routable_executors() NOT called here
    │
    ├─ local path ─────────────────────────────────────────────────►
    │       CapabilityBus / CapabilityOrchestrator
    │       (local capability dispatch; reads from capability graph)
    │       TaskGraphRuntime
    │       Local executor / skill / MCP node
    │
    └─ cross-device path ──────────────────────────────────────────►
            [GAP SCHED-001]: CapabilityAssimilationLayer.query_routable_executors()
            NOT consulted here — device selection bypasses capability graph
            │
            ▼
            cross_device_candidates.resolve_candidates()  ← ADMISSIBILITY CHAIN
            │
            │  Gate 1: device_readiness
            │          → UDM / UCM transport presence + heartbeat state
            │          → Output: device is online and reachable
            │
            │  Gate 2: device_participation
            │          → orchestration eligibility check
            │          [GAP ADMIT-003]: does NOT check CapabilityAssimilationLayer
            │
            │  Gate 3: target_device_validator
            │          → per-device validation (policy, HITL, ACL)
            │
            │  [GAP ADMIT-005]: NO capability verification gate
            │          → device_capabilities from Android may not be in graph
            │
            ▼
            formation_resolver.resolve_formation()
            │  → DeviceFormationGroup + FormationPolicy + FormationMember + FormationRole
            │  → static resolution at dispatch time only
            │  [GAP ADMIT-003]: does NOT call CapabilityAssimilationLayer
            │  [GAP MESH-006]: no dynamic rebalance on device health change
            │
            ▼
            DeviceRouter.route_task()    ← SUBSTRATE-ONLY dispatcher
            │  (sentinel: DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY)
            │  [GAP SCHED-002]: _select_devices() is an independent selection path
            │  [GAP SCHED-003]: _analyze_command() is policy logic (should be in CommandRouter)
            │
            ├─ single device ──────────────────────────────────────►
            │       DeviceRouter.dispatch_task()
            │       AgentBridge handoff (preferred)
            │
            └─ multi device ───────────────────────────────────────►
                    DeviceRouter._dispatch_cross_device_task()
                    CrossDeviceCoordinator.execute_cross_device_task()
                    (sentinel: CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY)
                    [GAP COMPAT-003]: external callers still possible
                    │
                    ▼
                    Remote device executor (Android / other)
```

---

## Additionally: ConstellationRuntime device selection

```
ConstellationRuntime._run_dag_loop()
    │
    ▼
pool.select_device(required_capabilities=caps)
    │  → DevicePool.select_device()
    │  [GAP SCHED-004]: NOT CONFIRMED whether DevicePool reads from
    │                   CapabilityAssimilationLayer or from its own internal state.
    │                   If internal: this is a THIRD independent selection path.
    │
    ▼
subtask.device_id assigned
    │
    ▼
dispatch proceeds through CommandRouter (?)
    │  [UNCONFIRMED]: whether ConstellationRuntime dispatches through
    │                 CommandRouter.route_envelope() or directly to DeviceRouter
```

**Action required**: Confirm whether `ConstellationRuntime` dispatches through
`CommandRouter`. If not, ConstellationRuntime is a fourth independent dispatch
path bypassing the canonical chain.

---

## Layer-by-layer authority classification

### CapabilityBus / CapabilityOrchestrator

| Field | Value |
|-------|-------|
| **Modules** | `core/capability_bus.py`, `core/capability_orchestrator.py` |
| **Role** | Local capability dispatch authority |
| **Classification** | ✅ Canonical — stable for local paths |
| **Scope** | Routes to locally registered capabilities (tools, skills, MCP providers, nodes) |
| **Reads from** | Capability graph (via CapabilityAssimilationLayer) for local lookups |
| **Limitation** | Does not directly participate in cross-device routing |

---

### CapabilityAssimilationLayer

| Field | Value |
|-------|-------|
| **Module** | `core/capability_assimilation.py` |
| **Role** | Unified capability registration and query authority for ALL participant types |
| **Classification** | ✅ Canonical — single source of truth for capabilities |
| **Scope** | Nodes, devices (Android, desktop, sensor), MCP providers |
| **Key methods** | `assimilate_device()`, `register_node()`, `query_routable_executors()`, `query_network_path()` |
| **Gap** | SCHED-001: `query_routable_executors()` not called by CommandRouter. Graph is built but not consulted at routing time. |
| **Gap** | ADMIT-005: Android `device_capabilities` ingress not confirmed auto-wired at connection time. |

---

### CommandRouter

| Field | Value |
|-------|-------|
| **Module** | `core/command_router.py` |
| **Role** | Sole canonical cross-device dispatch authority |
| **Classification** | ✅ Canonical — sole entry for cross-device execution |
| **Scope** | All task execution that crosses device boundaries |
| **Key method** | `route_envelope(TaskEnvelope)` |
| **Sentinel** | All alternative paths are sentinel-gated as substrate-only |
| **Gap** | SCHED-001: does not consult `query_routable_executors()` — capability-graph-unaware dispatch |
| **Gap** | SCHED-004: uncertain whether ConstellationRuntime dispatches through CommandRouter |

---

### Admissibility chain

| Field | Value |
|-------|-------|
| **Module** | `core/cross_device_candidates.py` |
| **Role** | Device eligibility verification before dispatch |
| **Classification** | ✅ Canonical — 3 gates, called from CommandRouter |
| **Gates** | (1) transport/presence, (2) orchestration eligibility, (3) per-device validation |
| **Gap** | No capability verification gate (ADMIT-005) |
| **Gap** | Gate 2 does not consult CapabilityAssimilationLayer (ADMIT-003) |

---

### formation_resolver

| Field | Value |
|-------|-------|
| **Module** | `core/device_formation/formation_resolver.py` |
| **Role** | Static device group formation at dispatch time |
| **Classification** | ✅ Canonical for dispatch-time formation |
| **Gap** | ADMIT-003: does not call CapabilityAssimilationLayer |
| **Gap** | MESH-006: static only; no dynamic rebalancing |

---

### DeviceRouter

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/device_router.py` |
| **Role** | Device-bound dispatch substrate |
| **Classification** | 🔄 Transitional → substrate-only |
| **Sentinel** | `DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY` enforced |
| **Gap** | SCHED-002: `_select_devices()` is an independent device selection path |
| **Gap** | SCHED-003: `_analyze_command()` is policy logic that belongs in CommandRouter |

---

### CrossDeviceCoordinator

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/cross_device_coordinator.py` |
| **Role** | Multi-device task execution substrate |
| **Classification** | 🔄 Substrate-only (gated) |
| **Sentinel** | `CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY` enforced |
| **Gap** | COMPAT-003: external callers possible; `LEGACY_DISPATCH` warnings not monitored |

---

### TruthIntegrationLayer

| Field | Value |
|-------|-------|
| **Module** | `core/truth_integration_layer.py` |
| **Role** | Canonical device truth convergence point |
| **Classification** | 🟡 Partial — wired but not universally consumed |
| **Gap** | ADMIT-001: some status/projection surfaces may still query UDM/UCM directly |

---

### CapabilityRegistry (legacy)

| Field | Value |
|-------|-------|
| **Module** | `core/capability_registry.py` |
| **Role** | Device-local capability bookkeeping (permitted use only) |
| **Classification** | 🔄 Gated — routing decisions must use CapabilityAssimilationLayer |
| **Gap** | COMPAT-002: developers may still use for routing; no static guard enforces boundary |

---

## Node capabilities vs device capabilities — convergence status

| Layer | Node capabilities | Device capabilities | Unified? |
|-------|------------------|--------------------|---------:|
| Registration | `register_node()` | `assimilate_device()` | ✅ Yes — both in CapabilityAssimilationLayer |
| Graph representation | `AssimilationRecord` | `AssimilationRecord` | ✅ Yes — same record type |
| Query interface | `query_routable_executors()` | `query_routable_executors()` | ✅ Yes — same method |
| CommandRouter dispatch | LocalPath: reads capability graph | Cross-device: uses admissibility chain only | ❌ No — cross-device path bypasses capability graph |
| Formation resolver | — | Admissibility chain output | ❌ No — no capability check at formation |
| DeviceRoleAllocator | — | Position/order only | ❌ No — no capability-aware role allocation |

**Summary**: Convergence is **real at registration** and **absent at dispatch**.
The unified capability graph exists and is populated, but the hot-path dispatch
decisions for cross-device execution do not read from it.

---

## Scheduling authority gaps — action map

| Gap | Action | Owner layer | Priority |
|-----|--------|------------|----------|
| SCHED-001 | Wire `query_routable_executors()` into CommandRouter cross-device path | CommandRouter | P1 |
| SCHED-002 | Retire `DeviceRouter._select_devices()` or delegate to admissibility chain | DeviceRouter | P2 |
| SCHED-003 | Move `_analyze_command()` classification to CommandRouter | DeviceRouter | P3 |
| SCHED-004 | Confirm DevicePool source; wire to CapabilityAssimilationLayer if independent | ConstellationRuntime | P2 |
| ADMIT-003 | Add capability verification call in formation_resolver | formation_resolver | P2 |
| ADMIT-005 | Wire Android `device_capabilities` ingress to `assimilate_device()` | android_bridge | P0 |

# Unified Scheduling Authority Map

> **Full re-audit pass** — fresh standalone review. Supersedes all prior scheduling
> authority map versions including `REAUDIT_SCHEDULING_AUTHORITY_V2.md`.
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android`.

---

## Purpose

This document answers the question:

> *Are node capabilities and device capabilities truly unified into one canonical scheduling and routing path, or does convergence remain only partial?*

It traces the real authority chain from capability registration through
`CapabilityBus`, `CapabilityAssimilation`, orchestrator layers, device
selection, formation resolution, and `CommandRouter`, and classifies the
responsibility of every significant layer.

---

## Authority chain — top-level view

```
User request / agent invocation
    │
    ▼
OpenClawd._dispatch_device() / e2e_orchestrator.process_user_input()
    │  (entry normalisation; picks up intent + required_capabilities)
    ▼
CommandRouter.route_envelope()      ← SOLE canonical cross-device dispatcher
    │  (ACL, HITL gating, lifecycle, retry, TaskEnvelope propagation)
    │
    ├─ local path ──────────────────────────────────────────────────────►
    │       CapabilityBus / CapabilityOrchestrator (local capability dispatch)
    │       TaskGraphRuntime
    │       Local executor / skill / MCP node
    │
    └─ cross-device path ────────────────────────────────────────────────►
            CapabilityAssimilationLayer.query_routable_executors()   [GAP-512-004 — not yet wired into CommandRouter]
            │
            ▼
            cross_device_candidates.resolve_candidates()   ← admissibility chain
            │   Gate 1: device_readiness (Layer 1 — transport/presence)
            │   Gate 2: device_participation (Layer 2 — orchestration eligibility)
            │   Gate 3: target_device_validator (Layer 3 — per-device validation)
            │
            ▼
            formation_resolver.resolve_formation()  ← DeviceFormationGroup + FormationPolicy
            │
            ▼
            DeviceRouter.route_task()    ← canonical device-bound dispatch substrate
            │   (transport session handles; source/target semantic separation PR-521)
            │
            ├─ AgentBridge handoff (preferred)
            └─ CrossDeviceCoordinator.execute_cross_device_task() (fallback)
                    │  (substrate-only; CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY enforced)
                    ▼
                    Remote device executor (Android / other)
```

---

## Layer-by-layer authority classification

### 1. CapabilityBus / CapabilityOrchestrator

| Field | Value |
|-------|-------|
| **Module** | `core/capability_bus.py`, `core/capability_orchestrator.py` |
| **Role** | Local capability dispatch authority |
| **Classification** | **Canonical — stable for local paths** |
| **Scope** | Routes to locally registered capabilities (tools, skills, MCP providers, nodes) |
| **Limitation** | Does not directly participate in device-bound cross-device routing; devices must be assimilated first |

`CapabilityOrchestrator.dispatch()` is the canonical local capability dispatch entry. It routes to registered capability providers based on capability name/ID.

---

### 2. CapabilityAssimilationLayer

| Field | Value |
|-------|-------|
| **Module** | `core/capability_assimilation.py` |
| **Role** | Bridge — translates all participant types (nodes, devices, skills, MCP providers) into canonical `AssimilationRecord` entries projected into capability graph + task graph + network graph |
| **Classification** | **Canonical — stable; partially wired into routing** |
| **Device assimilation** | `assimilate_device()` registers devices as `NodeParticipantKind.DEVICE` so the capability selection plane can treat them as first-class providers |
| **Key gap** | `CommandRouter` does not yet call `query_routable_executors()` / `query_network_path()` before selecting dispatch targets (GAP-512-004, MEDIUM severity, PR-514 target) |

The assimilation layer is architecturally correct and well-implemented. The convergence gap is that routing decisions in `CommandRouter` can still proceed without consulting the canonical `CapabilityAssimilationLayer` for executor readiness.

---

### 3. CommandRouter

| Field | Value |
|-------|-------|
| **Module** | `core/command_router.py` |
| **Role** | **SOLE canonical cross-device dispatcher** |
| **Classification** | **Canonical — stable** |
| **Sentinels** | `NO_PARALLEL_CROSS_DEVICE_DISPATCH_POLICY`, `COMMAND_ROUTER_PARALLEL_FANOUT_CANONICAL_PATH` |
| **Convergence status** | Both node-domain and device-domain tasks must route through `CommandRouter.route_envelope()` |

`CommandRouter` is the canonical orchestration authority for all cross-device dispatch. It enforces ACL, HITL gating, lifecycle state transitions, retry/circuit-breaker, and TaskEnvelope propagation. All PR-517 through PR-532 gaps are resolved — `CommandRouter` is the sole authorised dispatcher.

**Current convergence status**: `CommandRouter` is authoritative for *orchestration*, but it does **not yet consult `CapabilityAssimilationLayer`** for executor-readiness validation before target selection (GAP-512-004). This means capability and network routing truth is available but not yet consumed by the routing decision path.

---

### 4. DeviceRouter

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/device_router.py` |
| **Role** | Canonical device dispatch **substrate** — transport session management, WebSocket delivery |
| **Classification** | **Canonical substrate — stable; substrate-only boundary enforced** |
| **Sentinels** | `DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY`, `DEVICE_ROUTER_FORMATION_DESCRIPTOR_ATTACHED`, `DEVICE_ROUTER_CONTROL_SEMANTIC_SEPARATION` |
| **Policy leakage** | Historically held scheduling/policy logic; PR-517/518/520/521 progressively reduced this |

**Is `DeviceRouter.route_task()` a pure transport substrate or does policy/compat logic still leak in?**

The answer is: **partially reduced but not fully substrate-pure**.

- `route_task()` still performs command analysis (`_analyze_command`) to decide `exec_mode`, `task_type`, `device_id`, and route branching.
- It calls `resolve_formation()` (formation policy) before dispatch — this is architecture-correct but is policy/formation logic, not pure transport.
- The `AgentBridge` handoff path introduces an additional policy branch.
- The `CrossDeviceCoordinator` fallback remains.

For architecture purposes, `DeviceRouter` is best classified as a **canonical dispatch substrate with formation-aware routing** — more than pure transport, but less than policy-authority. The boundary is stable and well-governed (sentinel-enforced), but some formation/routing logic legitimately lives here as "late-stage orchestration before transport."

---

### 5. CrossDeviceCoordinator

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/cross_device_coordinator.py` |
| **Role** | DeviceRouter-internal fallback coordinator |
| **Classification** | **Compatibility / substrate-only — not a public dispatch entry** |
| **Sentinels** | `CROSS_DEVICE_COORDINATOR_SUBSTRATE_ONLY` |
| **Access constraint** | External callers must route through `DeviceRouter.route_task()`, not this directly |

`CrossDeviceCoordinator` is governed as a substrate-only component. It is used as a fallback when `AgentBridge` import fails. The `_substrate_caller` guard (PR-518/GAP-517-003) enforces this boundary. Direct external calls emit `LEGACY_DISPATCH` warnings and record `DispatchAuthorityRecord(dispatch_path=COORDINATOR_LEGACY)`.

---

### 6. Node capability vs. Device capability convergence

| Question | Answer |
|----------|--------|
| Do node capabilities and device capabilities converge in one canonical path? | **Architecturally yes, operationally partially** |
| How? | Both nodes and devices are assimilated via `CapabilityAssimilationLayer.assimilate()` / `assimilate_device()`. Both appear as `AssimilationRecord` entries with `NodeParticipantKind.WORKER` or `NodeParticipantKind.DEVICE`. Both are projected into the capability graph. |
| Gap | `CommandRouter` routing decisions do not yet query `CapabilityAssimilationLayer.query_routable_executors()` before target selection (GAP-512-004). This means the canonical unified capability/network view exists but is not yet consumed in the hot dispatch path. |
| Implication | For a task requiring a specific capability, the dispatcher may select a device/node without consulting the canonical assimilation layer's executor-readiness truth. The routing decision is still valid (devices are reachable), but it bypasses the unified capability graph. |

---

### 7. Scheduling basis — key modules and their roles

| Module | Role | Classification |
|--------|------|----------------|
| `core/capability_assimilation.py` | Absorbs all participant types; canonical capability authority | **Canonical — stable** |
| `core/capability_orchestrator.py` | Local capability dispatch | **Canonical — stable** |
| `core/capability_network_runtime_policy.py` | `query_routable_executors()` / `query_network_path()` — capability+network co-query | **Canonical — not yet wired into CommandRouter (GAP-512-004)** |
| `core/command_router.py` | Sole canonical cross-device orchestration dispatcher | **Canonical — stable** |
| `core/cross_device_candidates.py` | Admissibility chain: resolves which devices are eligible | **Canonical — stable** |
| `core/device_formation/formation_resolver.py` | Derives formation group + policy from signals | **Canonical — stable** |
| `galaxy_gateway/device_router.py` | Device dispatch substrate with formation-aware routing | **Canonical substrate — stable** |
| `galaxy_gateway/cross_device_coordinator.py` | DeviceRouter-internal fallback | **Compatibility / substrate-only** |
| `galaxy_gateway/agent_bridge.py` | Agent handoff surface | **Transitional** — preferred over coordinator but not fully canonical |

---

## Open scheduling convergence gaps

| Gap ID | Severity | Module | Description | Status |
|--------|----------|--------|-------------|--------|
| GAP-512-004 | ~~MEDIUM~~ | `core/command_router.py` | **CLOSED (PR-3).** `CommandRouter.route_envelope()` now passes `required_capabilities` to `query_routable_executors()` and enforces target validation against the canonical capability graph. Targets confirmed in the graph proceed unchanged; unconfirmed targets emit structured warnings and are filtered when confirmed alternatives exist. Falls back gracefully when the layer is unavailable. New sentinel: `CAPABILITY_GRAPH_SELECTION_ENFORCED`. | ✅ Closed |
| SCHED-003 | MEDIUM | `galaxy_gateway/device_router.py` | **Partially closed (PR-3).** `DeviceRouter.route_task()` now supports a CommandRouter pre-analysis passthrough: when `context["_command_router_pre_analyzed"]==True` and `context["_pre_analysis"]` is set, `route_task()` skips its own `_analyze_command()` call. New governance sentinel: `DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL`. Full extraction of `_analyze_command()` authority to `CommandRouter` and retirement of the DeviceRouter copy remains as a future hardening step. | ⚠️ Partially closed |
| SCHED-004 | LOW | `core/constellation_runtime.py` | `ConstellationRuntime._run_dag_loop()` calls `pool.select_device(required_capabilities=caps)` via `DevicePool`. Whether `DevicePool` reads from `CapabilityAssimilationLayer` is unconfirmed. Possible third parallel selection path. | Open |

---

## Answer to acceptance criteria 1 & 2 (PR-3 update)

**AC1 — Is node and device capability scheduling truly unified in practice?**

> **PR-3 improvement**: Both nodes and devices are first-class entries in `CapabilityAssimilationLayer`.  The canonical capability graph covers both kinds.  `CommandRouter.route_envelope()` now passes `required_capabilities` to `query_routable_executors()` and enforces target selection against the canonical graph (GAP-512-004 closed).  `query_capable_device_executors()` provides an explicit device-only selection helper so the node/device unified scheduling basis is directly testable.  The remaining gap is that `_execute_command` does not yet re-derive the target from the capability graph on retry paths, and `ConstellationRuntime` (SCHED-004) is not yet audited.

**AC2 — Is `DeviceRouter` cleanly reduced to substrate responsibility?**

> **PR-3 improvement**: `DeviceRouter.route_task()` now has a pre-analysis passthrough (`_command_router_pre_analyzed` context flag) so callers that have already resolved command analysis at the `CommandRouter` (decision) layer can bypass the DeviceRouter re-analysis entirely.  The governance intent is documented in `DEVICE_ROUTER_COMMAND_ANALYSIS_GOVERNANCE_SENTINEL`.  Full retirement of the DeviceRouter copy of `_analyze_command()` logic requires migrating all direct `route_task()` callers through `CommandRouter`, which is the remaining work in this gap.

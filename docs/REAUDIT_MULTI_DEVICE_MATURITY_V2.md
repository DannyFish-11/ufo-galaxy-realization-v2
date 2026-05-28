> ## ⚠️ SUPERSEDED — NOT AUTHORITATIVE
>
> **This document has been superseded by [`MULTI_DEVICE_RUNTIME_MATURITY.md`](MULTI_DEVICE_RUNTIME_MATURITY.md).**
> The content below is preserved for historical reference only.
> For the current multi-device runtime maturity matrix, see [`MULTI_DEVICE_RUNTIME_MATURITY.md`](MULTI_DEVICE_RUNTIME_MATURITY.md).

---

# Re-Audit: Multi-Device Runtime Maturity Matrix V2

> **Fresh re-audit pass** — `DannyFish-11/ufo-galaxy-realization-v2` and
> `DannyFish-11/ufo-galaxy-android`.
>
> Supersedes `docs/MULTI_DEVICE_RUNTIME_MATURITY.md`.
> Companion: `docs/REAUDIT_FRESH_PASS_2.md`

---

## Maturity classification legend

| Class | Symbol | Meaning |
|-------|--------|---------|
| Runtime-complete | ✅ | Full implementation; tested; wired into canonical chains; operates in production |
| Partial | 🟡 | Meaningful implementation; key gaps remain; functional but not fully reliable |
| Contract-first | 🔶 | Well-defined contract / data model; runtime wiring is incomplete or absent |
| Transitional | 🔄 | Exists and is used but on a migration path toward canonical replacement |
| Placeholder | ❌ | Structural presence with no real runtime behavior |
| Not implemented | ⛔ | No implementation exists; contract may or may not be defined |

---

## Summary matrix

| Component | Module | Maturity | Gaps |
|-----------|--------|----------|------|
| `CommandRouter` cross-device dispatch | `core/command_router.py` | ✅ Runtime-complete | SCHED-001: capability graph not consulted |
| `DeviceRouter` substrate dispatch | `galaxy_gateway/device_router.py` | ✅ Runtime-complete | SCHED-002: dual selection path |
| Parallel fanout API | `/api/v1/devices/parallel` | ✅ Runtime-complete | — |
| `formation_resolver` (static) | `core/device_formation/formation_resolver.py` | ✅ Runtime-complete | ADMIT-003: no capability verification at formation time |
| Admissibility chain (3 gates) | `core/cross_device_candidates.py` | ✅ Runtime-complete | ADMIT-005: no CapabilityAssimilationLayer call |
| `CapabilityAssimilationLayer` | `core/capability_assimilation.py` | ✅ Runtime-complete | SCHED-001/ADMIT-005: not consulted at routing/admission |
| `TruthIntegrationLayer` | `core/truth_integration_layer.py` | 🟡 Partial | ADMIT-001: not all consumers use it |
| `BodyMeshRegistry` | `core/mesh/body_mesh_registry.py` | 🟡 Partial | MESH-003: in-process only; no persistence; not wired to connect/disconnect events |
| `session_roaming` (basic migrate) | `galaxy_gateway/session_roaming.py` | 🟡 Partial | MESH-005: duplicate migration path |
| `MeshSession` | `contracts/mesh_session.py` | 🔶 Contract-first | MESH-002: no live lifecycle engine |
| `MeshSessionCoordinator` | `contracts/mesh_session_coordinator.py` | 🔶 Contract-first | MESH-001: no live coordinator engine |
| `DeviceRoleAllocator` | `core/mesh/device_role_allocator.py` | 🔶 Contract-first | MESH-004: no capability-aware allocation |
| `CrossRuntimeResultMerge` | `contracts/cross_runtime_result_merge.py` | 🔶 Contract-first | MESH-007: no merge engine |
| `MultiDeviceRuntimeProjection` | `contracts/multi_device_runtime_projection.py` | 🔶 Contract-first | TRUTH-004: merged_results partially populated |
| Formation dynamic rebalance | `core/device_formation/formation_resolver.py` | ⛔ Not implemented | MESH-006 |
| Persistent mesh session store | — | ⛔ Not implemented | MESH-003 dependency |
| Recovery / resume from checkpoint | — | ⛔ Not implemented | — |
| Staged mesh execution | — | ⛔ Not implemented | MESH-008 |

---

## Detailed component assessments

### 1. CommandRouter cross-device dispatch

**Module**: `core/command_router.py`
**Maturity**: ✅ Runtime-complete

**What works**:
- Sole canonical cross-device dispatcher; enforced by sentinel on all alternatives.
- Admissibility chain (3 gates) called before dispatch.
- Formation resolved at every cross-device invocation.
- Source/target device semantic separation (PR-521).
- TaskEnvelope propagated throughout.
- ACL, HITL gating, lifecycle, and retry are all live.

**Active gap**:
- SCHED-001: `query_routable_executors()` not called; capability graph is built but
  not consulted for dispatch target selection. Routing is valid but not
  capability-graph-aware.

---

### 2. DeviceRouter substrate dispatch

**Module**: `galaxy_gateway/device_router.py`
**Maturity**: ✅ Runtime-complete (as substrate)

**What works**:
- Single-device dispatch (`dispatch_task`) and multi-device dispatch
  (`_dispatch_cross_device_task`) both implemented.
- Substrate-only sentinel `DEVICE_ROUTER_CROSS_DEVICE_SUBSTRATE_ONLY` enforced.
- Formation resolver called.
- Source device ID and runtime posture injected into task dict (PR-521).

**Active gap**:
- SCHED-002: `_select_devices()` is a parallel device selection path that does not
  consult the admissibility chain or capability graph.
- SCHED-003: `_analyze_command()` performs policy classification that ideally lives
  in CommandRouter.

---

### 3. Parallel fanout API

**Module**: `core/routes/` → `/api/v1/devices/parallel`
**Maturity**: ✅ Runtime-complete

**What works**:
- Dispatches a single task to multiple target devices in parallel.
- Returns aggregated results.

**Active gap**:
- Parallel fanout is not the same as staged mesh execution (MESH-008). Fanout
  dispatches all devices simultaneously with no dependency ordering.

---

### 4. formation_resolver (static)

**Module**: `core/device_formation/formation_resolver.py`
**Maturity**: ✅ Runtime-complete (static resolution only)

**What works**:
- Formation resolved at every cross-device dispatch invocation.
- `DeviceFormationGroup`, `FormationPolicy`, `FormationMember`, `FormationRole`
  contracts fully populated.
- Formation resolution uses execution policy + routing summary as inputs.

**Active gaps**:
- ADMIT-003: Does not call `CapabilityAssimilationLayer` for capability verification
  during formation resolution. Device may join a formation without capability check.
- MESH-006: No dynamic rebalancing when a device disconnects or health degrades
  mid-session. Formation membership is fixed at dispatch time.

---

### 5. Admissibility chain (3 gates)

**Module**: `core/cross_device_candidates.py`
**Maturity**: ✅ Runtime-complete (gate logic)

**What works**:
- Gate 1 (`device_readiness`): transport/presence check via UDM/UCM.
- Gate 2 (`device_participation`): orchestration eligibility check.
- Gate 3 (`target_device_validator`): per-device final validation.
- Called from CommandRouter on every cross-device routing decision.

**Active gap**:
- ADMIT-005: No capability verification gate. A device can pass all 3 gates and
  be admitted to a formation without its declared capabilities being verified
  against the task's required capabilities.

---

### 6. BodyMeshRegistry

**Module**: `core/mesh/body_mesh_registry.py`
**Maturity**: 🟡 Partial

**What works**:
- In-process singleton registry for mesh memberships and sessions.
- `get_mesh_session()` returns `MeshSession` snapshots from registry entries.
- `get_mesh_session_coordinator()` returns coordinator state snapshots.
- PR-37 integration bridges in place.

**Active gaps**:
- MESH-003: In-process only — all state lost on process restart.
- Not subscribed to UDM/UCM device connect/disconnect events — mesh membership
  does not automatically update when a device goes offline.

---

### 7. session_roaming (basic migrate)

**Module**: `galaxy_gateway/session_roaming.py`
**Maturity**: 🟡 Partial

**What works**:
- Basic session migration: moves session state from one device to another.
- Some unit test coverage.

**Active gap**:
- MESH-005 (HIGH): A second session migration implementation exists in
  `core/routes/sessions.py` with different semantics and different persistence
  paths. No canonical migration entry is defined. Calling through either path can
  result in divergent session state (split-brain risk).

---

### 8. MeshSession

**Module**: `contracts/mesh_session.py`
**Maturity**: 🔶 Contract-first

**What works**:
- Full contract type hierarchy: `MeshSession`, `MeshSessionParticipant`,
  `MeshSubtaskAssignment`, `MeshMergePolicy`, `MeshBarrierPosture`, `MeshSessionStatus`.
- Multiple builder adapters from formation summaries and constellation decompositions.
- Can be instantiated and introspected from projection surfaces.

**What is missing**:
- `MeshSessionStatus` transitions (`FORMING → ACTIVE → COMPLETING → DONE`) have
  no live driver. Status is set at construction and never updated.
- `MeshSubtaskAssignment.status` fields are not updated as subtasks execute.
  No consumer reads TaskGraphRuntime events and updates assignments.
- `merge_policy` and `barrier_posture` are declared but no runtime process
  enforces them.
- No durable session store — `MeshSession` objects are rebuilt from BodyMeshRegistry
  on every read and cannot survive process restarts.

**Blocking**: A true multi-device session (even two devices) cannot be coordinated
because there is no engine to drive the session lifecycle.

---

### 9. MeshSessionCoordinator

**Module**: `contracts/mesh_session_coordinator.py`
**Maturity**: 🔶 Contract-first

**What works**:
- Contract type definitions: `MeshSessionCoordinatorState`, `MeshParticipantCoordinationState`,
  `MeshAssignmentState`, `MeshBarrierState`.
- Builder functions: `from_mesh_session()`, `build_mesh_session_coordinator()`.
- Integration bridge in `BodyMeshRegistry.get_mesh_session_coordinator()`.
- Contract populated by adapters from `MeshSession` and formation summaries at
  construction time.

**What is missing**:
- No live runtime class continuously evolving `MeshSessionCoordinatorState` across
  session phases.
- `pending_device_ids`, `completed_device_ids`, `failed_device_ids` are populated
  once at construction and never updated dynamically.
- Barrier coordination (all devices complete before merge) has no runtime engine.
- Merge ownership handoff is declared but not enforced.

**Assessment**: The coordinator contract is well-designed. What is needed is a live
`MeshSessionCoordinatorRuntime` class that subscribes to `TaskGraphRuntime` events
and drives state transitions.

---

### 10. DeviceRoleAllocator

**Module**: `core/mesh/device_role_allocator.py`
**Maturity**: 🔶 Contract-first

**What works**:
- `allocate()` method exists and can assign roles to devices.
- Role types are defined (`PRIMARY`, `SECONDARY`, `OBSERVER`, etc.).

**What is missing**:
- MESH-004: Does not consult `CapabilityAssimilationLayer`. Role allocation is
  based on position/order, not on device capability profile. A device may be
  assigned the `PRIMARY` role even if its capabilities are weaker than a
  `SECONDARY` device.

---

### 11. CrossRuntimeResultMerge

**Module**: `contracts/cross_runtime_result_merge.py`
**Maturity**: 🔶 Contract-first

**What works**:
- Contract type defined.
- `MeshSession.merge_policy` field declared.

**What is missing**:
- MESH-007: No runtime process reads `merge_policy` and executes a merge across
  device results. The merge contract is unreachable from any execution path.

---

### 12. MultiDeviceRuntimeProjection

**Module**: `contracts/multi_device_runtime_projection.py`
**Maturity**: 🔶 Contract-first (with partial population)

**What works**:
- Full contract hierarchy stable.
- `runtime_devices`, `runtime_hosts`, `mesh_memberships`, `mesh_sessions` fields
  populated from live registry state.
- REST endpoint `GET /api/v1/projection/runtime/multi-device` functional.

**What is missing**:
- TRUTH-004: `merged_results` body partially enriched (PR-522) but not fully sourced
  from canonical chain state.
- Projection reflects contract-first components (MeshSession, MeshSessionCoordinator)
  with frozen state — not live execution state.

---

### 13. Formation dynamic rebalance

**Module**: Not yet implemented
**Maturity**: ⛔ Not implemented

**Gap**: MESH-006. No mechanism to update formation membership when a device
disconnects or degrades mid-session. The formation snapshot taken at dispatch time
is final for the session lifetime.

**Impact**: If a device in a multi-device formation goes offline mid-task, the
formation is invalid but the session continues with stale routing targets.

---

### 14. Staged mesh execution

**Module**: Not yet implemented
**Maturity**: ⛔ Not implemented

**Gap**: MESH-008. The current parallel fanout API dispatches all devices
simultaneously. There is no execution model for:
- Device A must complete subtask X before device B begins subtask Y.
- Device B's input depends on device A's output.

**Impact**: Complex multi-device workflows that require sequential coordination
cannot be expressed or executed.

---

## Multi-device execution capability summary

| Capability | Status | Notes |
|------------|--------|-------|
| Route a task to a single remote device | ✅ Works | Via CommandRouter + admissibility chain |
| Route a task to multiple devices in parallel (fanout) | ✅ Works | Via parallel fanout API |
| Form a device group at dispatch time | ✅ Works | Via formation_resolver |
| Allocate roles to devices in a formation | 🔶 Contract only | No capability-aware allocation |
| Track mesh session status across execution | 🔶 Contract only | No live status driver |
| Coordinate barriers across devices | 🔶 Contract only | No barrier runtime engine |
| Merge results from multiple devices per policy | 🔶 Contract only | No merge engine |
| Migrate session from one device to another | 🟡 Partial | Dual implementation; split-brain risk |
| Recover session after process restart | ⛔ Not implemented | No persistent session store |
| Execute dependency-ordered multi-device subtasks | ⛔ Not implemented | Parallel only |
| Dynamically rebalance formation when device leaves | ⛔ Not implemented | Static formation only |

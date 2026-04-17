# Multi-Device Runtime Maturity Assessment

> **Dual-repo audit document** — produced as part of the complete unresolved audit PR.
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Cross-repo reference: `DannyFish-11/ufo-galaxy-android`.

---

## Purpose

This document performs a complete maturity audit of the multi-device runtime
stack. For each component, it classifies whether it is:

- **runtime-complete** — full implementation, tested, wired into canonical chains
- **partial** — meaningful implementation but gaps remain
- **contract-first** — well-defined contract (data model/interface) but runtime wiring is incomplete
- **transitional** — exists, used, but on a migration path toward a canonical replacement
- **compatibility/side-path** — still on some path but not the canonical main path
- **placeholder** — structural presence with no real runtime behavior

---

## Component-by-Component Maturity

### 1. MeshSessionCoordinator

| Field | Value |
|-------|-------|
| **Module** | `contracts/mesh_session_coordinator.py` |
| **Contract** | `MeshSessionCoordinatorState`, `MeshParticipantCoordinationState`, `MeshAssignmentState`, `MeshBarrierState` |
| **Introduced** | PR-37 |
| **Classification** | **Contract-first** |

**What exists:**
- Full contract type definitions (`MeshSessionCoordinatorState`, all sub-types)
- Builder functions (`from_mesh_session()`, `build_mesh_session_coordinator()`)
- Integration bridges in `BodyMeshRegistry.get_mesh_session_coordinator()` (PR-37 hook)
- Contract is populated by adapters from `MeshSession` and formation summaries

**What is missing / unverified:**
- No live runtime class that continuously evolves `MeshSessionCoordinatorState` across session phases (barrier wait, assignment progress, merge trigger)
- `pending_device_ids`, `completed_device_ids`, `failed_device_ids` are populated at construction time from a static `MeshSession` — not dynamically updated as the session executes
- Barrier coordination (wait for all devices → proceed) has no runtime orchestration engine
- Merge ownership hand-off is declared but not enforced at runtime

**Assessment:** The coordinator contract is well-designed and stable. The gap is a live coordinator engine that reads from TaskGraphRuntime and updates the state as execution progresses.

---

### 2. MeshSession

| Field | Value |
|-------|-------|
| **Module** | `contracts/mesh_session.py` |
| **Contract** | `MeshSession`, `MeshSessionParticipant`, `MeshSubtaskAssignment`, `MeshMergePolicy`, `MeshBarrierPosture`, `MeshSessionStatus` |
| **Introduced** | PR-33 |
| **Classification** | **Contract-first / partial** |

**What exists:**
- Full contract type hierarchy
- Multiple builder adapters: `from_device_formation_summary()`, `from_cross_device_routing_summary()`, `from_constellation_decomposition()`
- `BodyMeshRegistry.get_mesh_session()` wraps live registry entries into `MeshSession` snapshots
- `subtask_assignments` can be populated from task decomposition

**What is missing / unverified:**
- `MeshSessionStatus` transitions (`FORMING → ACTIVE → COMPLETING → DONE`) are not driven by any live engine
- `MeshSubtaskAssignment.status` fields are not updated as subtasks execute; no consumer updates them from `TaskGraphRuntime` events
- `merge_policy` / `barrier_posture` are declared but no runtime process enforces them
- Session persistence: `MeshSession` objects are rebuilt from `BodyMeshRegistry` each time — no durable store ensures continuity across process restarts or device disconnects

**Assessment:** `MeshSession` is a contract-first component that can be instantiated and introspected. It does not yet have a runtime lifecycle engine behind it.

---

### 3. formation_resolver

| Field | Value |
|-------|-------|
| **Module** | `core/device_formation/formation_resolver.py` |
| **Contract** | `DeviceFormationGroup`, `FormationPolicy`, `FormationMember`, `FormationRole` |
| **Introduced** | PR-17 |
| **Classification** | **Runtime-complete (read-derive)** |

**What exists:**
- Full `resolve_formation()` implementation with graceful degradation
- Reads from cross-device routing summary, execution policy, merge summary
- Assigns roles: PRIMARY_EXECUTION, SOURCE, SUPPORT, RELAY, OBSERVER, FALLBACK
- Derives `BarrierPosture` and `FormationPolicy`
- Called by `DeviceRouter._dispatch_cross_device_task()` and `CrossDeviceCoordinator.execute_cross_device_task()` at every cross-device dispatch (PR-520 resolution)
- `FormationTruthRecord` emitted to integrity runtime (PR-520)
- Formation descriptor attached to result payload under `"formation"` key

**What is missing:**
- Dynamic rebalancing: formation is resolved once per dispatch, not continuously rebalanced as devices join/leave mid-session
- No live reshaping when a device health score degrades or a device disconnects during execution
- Live membership updates are deferred (noted as non-goal in `formation_resolver.py`)

**Assessment:** The resolver is runtime-complete for static formation derivation at dispatch time. Dynamic rebalancing during live session is a known planned gap.

---

### 4. body_mesh_registry

| Field | Value |
|-------|-------|
| **Module** | `core/mesh/body_mesh_registry.py` |
| **Contract** | `BodyMeshRegistry`, `BodyEntry`, `DeviceRole`, `BodyAssignment` |
| **Classification** | **Partial** |

**What exists:**
- Thread-safe registry with register/unregister/get/list APIs
- `compute_assignment()` — derives primary/secondary body assignment
- `score_entry()` — updates body_score from health scores
- `snapshot()` — returns JSON-serialisable mesh snapshot
- Integration bridges: `get_mesh_memberships()`, `get_mesh_session()`, `get_mesh_session_coordinator()` (PR-32/33/37 hooks)

**What is missing / gaps:**
- `register()` and `unregister()` are not wired to UDM device lifecycle events — the registry must be manually populated; no automatic sync with device connect/disconnect
- `compute_assignment()` uses simple scoring heuristics (body_score), not capability-aware assignment
- No role conflict resolution when multiple devices compete for PRIMARY role
- The registry is in-process only — no persistence across restarts; devices must re-register

**Assessment:** The body mesh registry is a functional runtime component for tracking device roles and computing basic assignments. It is partial because it lacks automatic lifecycle wiring to device admission events and has no persistence.

---

### 5. device_role_allocator

| Field | Value |
|-------|-------|
| **Module** | `core/mesh/device_role_allocator.py` |
| **Contract** | `DeviceRoleAllocator`, `AllocationResult` |
| **Classification** | **Contract-first** |

**What exists:**
- `DeviceRoleAllocator` class with `allocate()` method
- `AllocationResult` contract

**What is missing / unverified:**
- Based on available evidence, the allocator computes role allocations but does not integrate with live `CapabilityAssimilationLayer` capability readiness data for intelligent allocation
- No evidence of multi-constraint allocation (e.g., "allocate role X to device with capability Y and lowest latency")
- Not wired to `TaskGraphRuntime` events to re-allocate roles when device capacity changes

**Assessment:** Contract-first. The allocator API exists; the allocation intelligence depth is limited and not connected to the canonical capability graph.

---

### 6. session_roaming

| Field | Value |
|-------|-------|
| **Module** | `galaxy_gateway/session_roaming.py` |
| **Contract** | `SessionRoamingManager`, `Session`, `SessionState`, `SessionContext` |
| **Classification** | **Partial** |

**What exists:**
- `SessionRoamingManager` with create/get/migrate/close APIs
- `migrate_session()` — serialises context, persists snapshot via `cross_device_coordinator`, pushes to target device via WebSocket
- `auto_migrate_on_attention_shift()` — attention-triggered migration
- REST endpoint: `POST /api/v1/sessions/{session_id}/migrate`
- Test coverage: `test_session_roaming_create_and_migrate` confirms basic flow

**What is missing / gaps:**
- Persistence is delegated to `cross_device_coordinator` shared data store — not a canonical durable store (no `TaskGraphRuntime` or `ReplayFoundation` recording of migration events)
- No rollback or compensating transaction if push to target device fails partially
- `MIGRATING` state is set and then either transitions to `ACTIVE` on success or rolled back to `ACTIVE` on failure — no `FAILED` terminal state for partial migrations
- `auto_migrate_on_attention_shift()` uses simple boolean attention map — no connection to real device attention/activity signals
- Parallel `core/routes/sessions.py` also has `POST /api/v1/sessions/migrate` — two separate session migration implementations exist (one in gateway, one in core) with different semantics

**Assessment:** Partial implementation. The migration flow works for the happy path. Error handling, persistence canonicalization, and dual-path session migration are gaps.

---

### 7. Session migrate / restore flows

| Field | Value |
|-------|-------|
| **Modules** | `galaxy_gateway/session_roaming.py`, `core/routes/sessions.py`, Android `SESSION_MIGRATE` / `session_restore` message handlers |
| **Classification** | **Partial — two parallel implementations, no canonical single path** |

**Center-side (V2 repo):**
- `galaxy_gateway/session_roaming.py` — sends `session_restore` via WebSocket to target device
- `core/routes/sessions.py` — sends `session_migrated` to source and `session_sync` to target
- Both paths exist; no single canonical migration entry point

**Android-side:**
- `SESSION_MIGRATE` is a `LegacyMessageType` from AIP v2 binary protocol
- `session_restore` message is expected by `SessionRoamingManager._push_context_to_device` but Android handling is not confirmed as fully wired into canonical task lifecycle

**Assessment:** Partial / dual-path. Session migration exists and works for basic cases but lacks a single canonical implementation and verified end-to-end closure from V2 to Android.

---

### 8. Staged mesh / parallel subtask participation

| Field | Value |
|-------|-------|
| **Modules** | `core/routes/devices.py` (parallel fanout), `contracts/mesh_session.py` (subtask assignments), `CommandRouter._route_parallel_fanout_envelope()` |
| **Classification** | **Partial** |

**What exists:**
- `CommandRouter._route_parallel_fanout_envelope()` — creates canonical per-device sub-envelopes and dispatches in parallel (PR-532)
- `MeshSubtaskAssignment` contract — declares subtask-to-device mapping
- `/api/v1/devices/parallel` endpoint — canonical fanout entry (PR-532 resolved GAP-517-002)

**What is missing / gaps:**
- Subtask assignments in `MeshSession.subtask_assignments` are not dynamically populated from the parallel fanout execution
- No staged mesh participation — tasks either go to all devices in parallel or to one primary device; no staged dependency graph execution (device A completes, then device B starts based on A's output)
- Result merge from parallel subtasks: `CrossRuntimeResultMerge` contract exists but `MeshSession.merge_policy` does not drive actual merge behavior

**Assessment:** Parallel dispatch (fanout) is runtime-complete for the basic case. Staged mesh execution (dependency-ordered multi-device subtask graphs) is not implemented.

---

### 9. Mesh session persistence gaps

| Area | Status | Gap |
|------|--------|-----|
| In-process session state | Exists (in-memory) | Not durable across process restarts |
| Cross-device snapshot | Via `cross_device_coordinator` shared store | Not integrated with `ReplayFoundation` or canonical audit |
| MeshSession object persistence | Rebuilt on each request from `BodyMeshRegistry` | No persistent canonical store |
| SessionRoamingManager persistence | Delegated to coordinator | Not a canonical durable store |

---

### 10. Formation dynamic rebalance gaps

| Area | Status | Gap |
|------|--------|-----|
| Static formation at dispatch time | Runtime-complete (PR-520) | — |
| Dynamic rebalance during session | Not implemented | No reshaping engine when device health degrades or disconnects mid-session |
| Role promotion (fallback → primary) | Not implemented | No automatic promotion when primary device fails |
| Health-driven reshaping | Not implemented | `score_entry()` updates scores but no rebalancer consumes score changes |

---

### 11. Recovery / resume behavior

| Area | Status | Gap |
|------|--------|-----|
| Session migrate on disconnect | Partial | `auto_migrate_on_attention_shift()` exists but not wired to device disconnect events |
| Task replay / resume | Partial | `ReplayFoundation` records exist but no resume-from-checkpoint execution engine |
| Distributed task merge recovery | Partial | `docs/DISTRIBUTED_TASK_MERGE_RECOVERY.md` exists; runtime completeness unverified |
| Durable runtime session snapshot | Contract-first | `docs/DURABLE_RUNTIME_SESSION_SNAPSHOT.md` exists; durable storage implementation unverified |

---

## Maturity Summary Table

| Component | Classification | Gaps |
|-----------|---------------|------|
| MeshSessionCoordinator | Contract-first | No live coordinator engine |
| MeshSession | Contract-first / partial | No lifecycle engine, no status transitions |
| formation_resolver | Runtime-complete (static) | No dynamic rebalance |
| body_mesh_registry | Partial | No automatic lifecycle wiring, no persistence |
| device_role_allocator | Contract-first | No capability-aware allocation |
| session_roaming | Partial | Dual implementations, no canonical durable store |
| Session migrate/restore | Partial | Two parallel implementations |
| Staged mesh participation | Partial | No dependency-ordered subtask graph execution |
| Mesh session persistence | Partial | In-memory only, no durable canonical store |
| Formation dynamic rebalance | Not implemented | No reshaping engine |
| Recovery / resume | Partial | No resume-from-checkpoint engine |

---

## Answer to acceptance criterion 3

**AC3 — Which multi-device runtime pieces are runtime-complete vs partial vs contract-only?**

| Piece | Status |
|-------|--------|
| formation_resolver (static dispatch-time) | ✅ Runtime-complete |
| CommandRouter cross-device dispatch | ✅ Runtime-complete |
| DeviceRouter substrate dispatch | ✅ Runtime-complete |
| Parallel fanout (`/api/v1/devices/parallel`) | ✅ Runtime-complete |
| body_mesh_registry (in-process) | ⚠️ Partial |
| session_roaming (basic migrate) | ⚠️ Partial |
| MeshSession | ⚠️ Contract-first / partial |
| MeshSessionCoordinator | ⚠️ Contract-first |
| device_role_allocator | ⚠️ Contract-first |
| Formation dynamic rebalance | ❌ Not implemented |
| Staged mesh participation | ❌ Not implemented |
| Persistent mesh session store | ❌ Not implemented |
| Recovery / resume from checkpoint | ❌ Not implemented |

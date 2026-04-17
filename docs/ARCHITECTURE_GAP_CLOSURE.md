# Architecture Gap Closure: Multi-Device Runtime, Compatibility, and Convergence Hardening

> **PR Status**: Implementation — closes identified architecture gaps in the Galaxy dual-repo system.
> **Primary repo**: `DannyFish-11/ufo-galaxy-realization-v2`
> **Related repo**: `DannyFish-11/ufo-galaxy-android` (linked design constraints)

---

## Summary

This document describes the concrete code changes introduced to begin closing the
known Galaxy architecture gaps in five areas:

1. **Mesh Session Durable Persistence** — `core/mesh/mesh_session_persistence.py`
2. **Formation Rebalance / Recovery Hooks** — `core/device_formation/formation_rebalance_engine.py`
3. **Formation Runtime Controller (PR-2)** — `core/device_formation/formation_runtime_controller.py`
4. **Scheduling / Truth Convergence Hardening** — `core/scheduling_truth_harness.py`
5. **Multi-Device Runtime Systemization** — `core/multi_device_runtime_harness.py`

---

## Gap 1: Mesh Session Durable Persistence

### Problem (from `MULTI_DEVICE_RUNTIME_MATURITY.md`)

> "Session persistence: MeshSession objects are rebuilt from BodyMeshRegistry
> each time — no durable store ensures continuity across process restarts or
> device disconnects."

### Implementation

**Module**: `core/mesh/mesh_session_persistence.py`

Provides:
- `MeshSessionPersistenceStore` — thread-safe, file-backed store for coordinator snapshots.
  - `save(coordinator_state)` — persist a `MeshSessionCoordinatorState` snapshot.
  - `load(session_id)` — load the latest snapshot for a session.
  - `list_recoverable()` — scan for non-terminal sessions eligible for recovery.
  - `delete(session_id)` — remove a session snapshot.
  - `mark_terminal(session_id)` — mark a session as completed/failed/cancelled.
- `SnapshotRecord` — serialisable snapshot record with versioning.
- Module-level functions: `save_mesh_session_snapshot`, `load_mesh_session_snapshot`,
  `recover_mesh_sessions`, `list_recoverable_sessions`.
- Singleton management: `get_persistence_store`, `reset_persistence_store`.

**Design**:
- Additive only — does not modify `MeshSessionCoordinator` or `BodyMeshRegistry`.
- File-backed by default (`data/mesh_sessions/<session_id>.json`).
- Pluggable: override `_write_record` / `_read_record` for Redis, S3, SQLite backends.
- Graceful degradation: all functions return valid results even when backing store unavailable.

**Exported from**: `core/mesh/__init__.py`

**Tests**: `tests/test_mesh_session_persistence.py` (25 tests)

**Sentinels**:
- `MESH_SESSION_PERSISTENCE_IS_AUTHORITY`
- `MESH_SESSION_PERSISTENCE_GAP_CLOSURE_SENTINEL`
- `RECOVERY_RESTORES_NON_TERMINAL_SESSIONS_POLICY`
- `PERSISTENCE_DOES_NOT_OWN_RUNTIME_TRUTH_POLICY`

---

## Gap 2: Formation Rebalance / Recovery Hooks

### Problem (from `MULTI_DEVICE_RUNTIME_MATURITY.md`)

> "formation_resolver does not implement live membership rebalancing or
> health-driven reshaping."

The existing `formation_resolver.py` docstring explicitly deferred:
> "Does not implement live membership rebalancing or health-driven reshaping
> (planned for future work)."

### Implementation

**Module**: `core/device_formation/formation_rebalance_engine.py`

Provides:
- `FormationHealthSignal` — health signal (score, reachability, reason) for one device.
- `MemberRebalanceAction` — enum of actions: `KEEP`, `PROMOTE_TO_PRIMARY`,
  `DEMOTE_TO_FALLBACK`, `REMOVE`, `WARN`.
- `RebalanceDecision` — outcome of a rebalance evaluation: which devices to
  promote/demote/remove/keep.
- `FormationRebalanceEngine` — stateless engine:
  - `evaluate(group, health_map)` → `RebalanceDecision`
  - `reshape(group, decision)` → `(DeviceFormationGroup, FormationPolicy)`
- Convenience functions:
  - `evaluate_formation_health(group, health_map)` — evaluate without applying.
  - `apply_rebalance(group, health_map)` — evaluate and apply in one step.
  - `maybe_promote_fallback(group, unhealthy_primary_id, best_fallback_id)` — targeted surgery.
  - `maybe_remove_unhealthy(group, unhealthy_device_ids)` — targeted surgery.

**Design**:
- Stateless — consumes a snapshot and returns a new one.
- SOURCE member is NEVER removed (policy: `REBALANCE_MUST_PRESERVE_SOURCE_POLICY`).
- Always ensures at least one `PRIMARY_EXECUTION` member after reshape
  (policy: `REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY`).
- Configurable health thresholds (default: unhealthy < 0.3, degraded < 0.6).

**Exported from**: `core/device_formation/__init__.py`

**Tests**: `tests/test_formation_rebalance_engine.py` (33 tests)

**Sentinels**:
- `FORMATION_REBALANCE_ENGINE_IS_AUTHORITY`
- `FORMATION_REBALANCE_GAP_CLOSURE_SENTINEL`
- `REBALANCE_MUST_PRESERVE_SOURCE_POLICY`
- `REBALANCE_MUST_MAINTAIN_PRIMARY_POLICY`
- `HEALTH_THRESHOLD_GOVERNS_REMOVAL_POLICY`

---

## PR-2: Formation Rebalance and Runtime Recovery Hooks

### Problem

The existing `formation_rebalance_engine.py` (Gap 2, above) provides a **stateless**
health-evaluation engine but stops short of providing **trigger-point-driven** recovery
semantics.  There are no named trigger hooks for readiness changes, participant loss,
role instability, or partial-formation degradation.  As a result, the multi-device
runtime has no explicit API for reacting to changing formation conditions — callers must
manually thread health maps into the engine with no guidance on what decision should
follow.

### Implementation

**Module**: `core/device_formation/formation_runtime_controller.py`

Provides the trigger-point and recovery-decision layer that connects runtime state
changes to formation reshaping:

- `FormationTriggerType` — named trigger categories: `PARTICIPANT_LOST`,
  `READINESS_CHANGED`, `HEALTH_DEGRADED`, `ROLE_INSTABILITY`, `PARTICIPANT_JOINED`.
- `FormationTriggerEvent` — structured event carrying trigger type, affected device,
  session/formation context, health score, and caller metadata.
- `DegradedContinuationDecision` — set of recovery decisions: `CONTINUE_DEGRADED`,
  `RESHAPE_AND_CONTINUE`, `AWAIT_RECOVERY`, `ABORT`.
- `FormationRecoveryPlan` — complete recovery output with continuation decision,
  reshaped formation, policy, affected device IDs, degradation flag, reason, and
  structured `recovery_hints` for downstream consumers.
- `FormationRuntimeController` — processes trigger events and returns recovery plans:
  - `process_trigger(event, formation)` — generic dispatch to the appropriate hook.
  - `on_participant_lost(event, formation)` — handles device loss by role.
  - `on_readiness_changed(event, formation)` — unready device → delegates to lost path;
    ready device → continue with no action.
  - `on_health_degraded(event, formation)` — below unhealthy threshold → lost path;
    degraded band → CONTINUE_DEGRADED with warn; above degraded → no-op.
  - `on_role_instability(event, formation)` — re-evaluates device as lost from its role.
  - `on_participant_joined(event, formation)` — signals whether re-resolution is
    recommended.
- Module-level convenience functions for each trigger type.

**Trigger routing table**:

| Device role | Trigger result |
|-------------|----------------|
| SOURCE | AWAIT_RECOVERY |
| PRIMARY_EXECUTION (fallback available) | RESHAPE_AND_CONTINUE (promotes fallback) |
| PRIMARY_EXECUTION (no fallback) | ABORT |
| FALLBACK | CONTINUE_DEGRADED |
| SUPPORT / RELAY / OBSERVER | CONTINUE_DEGRADED |

**Design**:
- Additive only — does not modify any existing module.
- Delegates all reshaping to `FormationRebalanceEngine` — recovery decisions stay
  consistent with health-evaluation policy.
- Graceful degradation — every method returns a valid `FormationRecoveryPlan` even when
  inputs are `None` or malformed.
- Stateless — callers update their own formation reference from `plan.reshaped_formation`.

**Exported from**: `core/device_formation/__init__.py`

**Tests**: `tests/test_formation_runtime_controller.py` (51 tests)

**Sentinels**:
- `FORMATION_RUNTIME_CONTROLLER_IS_AUTHORITY`
- `FORMATION_RUNTIME_CONTROLLER_PR2_SENTINEL`
- `SOURCE_LOSS_REQUIRES_AWAIT_RECOVERY_POLICY`
- `PRIMARY_LOSS_WITH_FALLBACK_TRIGGERS_RESHAPE_POLICY`
- `NON_CRITICAL_LOSS_CONTINUES_DEGRADED_POLICY`

---

## Gap 3: Scheduling / Truth Convergence Hardening

### Problem (from `RESIDUAL_GAP_MAP.md`)

- **GAP-512-002** (HIGH): Scheduler relay/mesh paths front-load `CanonicalTask`
  but do not register in `TaskGraphRuntime` before dispatch.
- **GAP-512-004** (MEDIUM): `CommandRouter` does not call `query_routable_executors()`
  / `query_network_path()` before selecting dispatch targets.

### Implementation

**Module**: `core/scheduling_truth_harness.py`

Provides:
- `SchedulingTruthHarness` — façade over the three canonical scheduling truth sources:
  - `TaskGraphRuntime` — task lifecycle truth.
  - `CapabilityNetworkRuntimePolicy` — routable-executor / network-path truth.
  - `CanonicalCapabilitySchedulingBasis` — device capability scheduling truth.
- Methods:
  - `ensure_task_registered(canonical_task)` → `bool` — closes GAP-512-002.
  - `query_routable_executors(canonical_task, candidate_device_ids)` → `List[str]`
    — closes GAP-512-004 for new call sites.
  - `assert_convergence(canonical_task)` → `ConvergenceAssertionResult` — CI-gate ready.
- `ConvergenceAssertionResult` — result struct with all three truth-source checks.
- Module-level functions: `ensure_task_registered`, `query_routable_executors_for_task`,
  `assert_scheduling_truth_convergence`.
- Singleton: `get_scheduling_truth_harness`, `reset_scheduling_truth_harness`.

**Design**:
- Additive only — does not modify `CommandRouter`, `scheduler.py`, or any existing module.
- Graceful degradation — every function returns valid results when backing truth sources
  are unavailable (e.g. optional imports fail).
- CI-gate ready — sentinels are importable strings for architecture test assertions.

**Tests**: `tests/test_scheduling_truth_harness.py` (20 tests)

**Sentinels**:
- `SCHEDULING_TRUTH_HARNESS_IS_AUTHORITY`
- `GAP_512_002_CLOSED_SENTINEL`
- `GAP_512_004_ADDRESSED_SENTINEL`
- `TASK_MUST_BE_REGISTERED_BEFORE_DISPATCH_POLICY`
- `ROUTING_MUST_CONSULT_CAPABILITY_NETWORK_TRUTH_POLICY`

---

## Gap 4: Multi-Device Runtime Systemization Groundwork

### Problem

The three new layers (mesh persistence, formation rebalance, scheduling truth) existed
independently without an integration surface. No runtime lifecycle path called them.

### Implementation

**Module**: `core/multi_device_runtime_harness.py`

Provides the integration harness that wires all three layers into explicit lifecycle hooks:

- `MultiDeviceRuntimeHarness` — singleton integration point:
  - `on_coordinator_state_updated(coordinator_state)` — persists snapshot to durable store.
  - `on_device_health_changed(event, formation)` — evaluates formation rebalance on
    device disconnect / heartbeat miss.
  - `on_task_admitted_for_dispatch(canonical_task)` — ensures task registration and
    routable-executor query before dispatch.
  - `recover_sessions()` — returns non-terminal session snapshots for recovery.
- `DeviceHealthEvent` — structured health event for use from connection/heartbeat monitors.
- `RuntimeHarnessResult` — result struct with all operation outcomes.
- Module-level hook functions: `on_coordinator_state_updated`, `on_device_health_changed`,
  `on_task_admitted_for_dispatch`.
- Singleton: `get_multi_device_runtime_harness`, `reset_multi_device_runtime_harness`.

**Design**:
- Hooks over invasive wiring — all integration points are explicit hook functions that
  can be called from existing code with minimal churn.
- `on_task_admitted_for_dispatch` always returns `success=True` — dispatch is never
  blocked by harness availability (graceful degradation).

**Tests**: `tests/test_multi_device_runtime_harness.py` (20 tests)

**Sentinels**:
- `MULTI_DEVICE_RUNTIME_HARNESS_IS_AUTHORITY`
- `MULTI_DEVICE_RUNTIME_HARNESS_GAP_CLOSURE_SENTINEL`
- `HARNESS_WIRES_PERSISTENCE_REBALANCE_SCHEDULING_POLICY`

---

## Calling Conventions

### Wiring mesh persistence into coordinator update paths

```python
from core.multi_device_runtime_harness import on_coordinator_state_updated

# After any MeshSessionCoordinatorState update:
result = on_coordinator_state_updated(coordinator_state)
```

### Wiring formation rebalance into device disconnect handlers

```python
from core.multi_device_runtime_harness import on_device_health_changed, DeviceHealthEvent

# On device disconnect or heartbeat miss:
event = DeviceHealthEvent(
    device_id=device_id,
    health_score=0.0,
    is_reachable=False,
    event_type="disconnect",
    session_id=current_session_id,
)
result = on_device_health_changed(event, formation=current_formation)
if result.rebalance_triggered:
    # result contains the reshaped formation — use new_group for subsequent dispatch
    pass
```

### Wiring scheduling truth into relay/mesh dispatch paths

```python
from core.multi_device_runtime_harness import on_task_admitted_for_dispatch

# Before relay/mesh dispatch:
result = on_task_admitted_for_dispatch(
    canonical_task,
    candidate_device_ids=candidate_ids,
    trace_id=trace_id,
)
# result.task_registered — whether task was registered in TaskGraphRuntime
# result.routable_executor_ids — canonical executor candidates
```

### Session recovery on startup

```python
from core.mesh.mesh_session_persistence import recover_mesh_sessions

recoverable = recover_mesh_sessions()
for snapshot in recoverable:
    # Re-hydrate coordinator from snapshot.snapshot_dict
    coordinator = MeshSessionCoordinatorState(**snapshot.snapshot_dict)
```

---

## Files Changed

| File | Type | Description |
|------|------|-------------|
| `core/mesh/mesh_session_persistence.py` | New | Durable mesh session persistence store |
| `core/mesh/__init__.py` | Modified | Export new persistence symbols |
| `core/device_formation/formation_rebalance_engine.py` | New | Health-driven formation rebalance engine |
| `core/device_formation/formation_runtime_controller.py` | New | Formation trigger hooks and runtime recovery controller (PR-2) |
| `core/device_formation/__init__.py` | Modified | Export rebalance engine and runtime controller symbols |
| `core/scheduling_truth_harness.py` | New | Scheduling/truth convergence harness |
| `core/multi_device_runtime_harness.py` | New | Multi-device runtime integration harness |
| `tests/test_mesh_session_persistence.py` | New | 25 tests for mesh session persistence |
| `tests/test_formation_rebalance_engine.py` | New | 33 tests for formation rebalance engine |
| `tests/test_formation_runtime_controller.py` | New | 51 tests for formation runtime controller (PR-2) |
| `tests/test_scheduling_truth_harness.py` | New | 20 tests for scheduling truth harness |
| `tests/test_multi_device_runtime_harness.py` | New | 20 tests for multi-device runtime harness |
| `docs/ARCHITECTURE_GAP_CLOSURE.md` | Modified | Added PR-2 section |

---

## What Remains (Future PRs)

This document covers two implementation rounds (gap-closure PR and PR-2). The
following gaps are noted but deferred:

1. **Live coordinator engine** — a runtime class that continuously evolves
   `MeshSessionCoordinatorState` across session phases (barrier wait, assignment
   progress, merge trigger). The `MeshSessionPersistenceStore` provides the durable
   substrate for this future engine.

2. **Wiring existing call sites** — `core/scheduler.py` relay/mesh paths and
   `galaxy_gateway/device_router.py` should call `on_task_admitted_for_dispatch` and
   `on_device_health_changed` respectively.  The new `FormationRuntimeController`
   trigger hooks should similarly be wired into gateway connection-loss handlers and
   heartbeat-miss paths. This can be done incrementally without breaking existing behavior.

3. **Android-side health signal forwarding** — the Android repo should forward
   device health events through the gateway's WebSocket channel so the
   `on_device_health_changed` hook and `FormationRuntimeController.on_participant_lost`
   hook receive them automatically.

4. **Redis/SQLite backend for persistence** — the pluggable backend interface in
   `MeshSessionPersistenceStore` is ready; a Redis adapter can be added for
   production deployments.

5. **Participant replacement / re-resolution path** — `on_participant_joined` signals
   when re-resolution is recommended but does not call `resolve_formation()`.  A future
   PR can wire this into a full participant-replacement loop.

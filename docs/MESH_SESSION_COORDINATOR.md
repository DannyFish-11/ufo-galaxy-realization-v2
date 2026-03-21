# Mesh Session Coordinator

> PR-37 — Canonical coordinator layer for multi-device mesh sessions.

## Overview

The **Mesh Session Coordinator** is the canonical coordinator layer that
manages a mesh session across multiple devices/runtimes.  It answers the
architectural question:

> "Once a mesh session exists, what canonical coordinator manages
> participation, assignment, status, and merge/barrier posture across
> the session?"

The coordinator is introduced as an **additive** layer that consumes the
contracts introduced in PR-29 through PR-36.  It does not replace or
redesign any existing module.

---

## What the Mesh Session Coordinator Does

The coordinator tracks:

| Concern | Field(s) |
|---|---|
| Who is coordinating | `coordinator_id` |
| Which session | `session_id`, `mesh_id`, `trace_id` |
| Who participates | `participants` (list of `MeshParticipantCoordinationState`) |
| What work is assigned | `assignments` (list of `MeshAssignmentState`) |
| Synchronisation barrier | `barrier_state` (`MeshBarrierState`) |
| Result merge ownership | `merge_owner_device_id` |
| Device progress | `pending_device_ids`, `completed_device_ids`, `failed_device_ids` |
| Overall lifecycle | `status` (`MeshCoordinatorStatus`) |
| Advisory event log | `coordination_events` |
| Merge summary | `result_merge_summary` |

---

## How it Differs from Related Contracts

| Contract | Purpose |
|---|---|
| **Mesh Membership** (PR-32) | Describes a single device's membership, role, authority scope, and routing intent within a mesh body. |
| **Mesh Session** (PR-33) | Describes the session itself: participants, subtask assignments, merge policy, barrier posture, status. |
| **Source Dispatch** (PR-35) | Describes the source runtime's decision and result when choosing *how* to dispatch work. |
| **Cross-Runtime Result Merge** (PR-36) | Describes the merged outputs after work is completed across runtimes. |
| **Mesh Session Coordinator** (PR-37, this PR) | *Manages* the session lifecycle: tracks readiness, assignment progress, barriers, and merge posture across all participants. Consumes PR-33/35/36 inputs to evolve coordinator state. |

The coordinator is the **lifecycle manager**; the mesh session is the
**session descriptor**; the dispatch orchestrator is the **work planner**.

---

## Contract Types

### `MeshSessionCoordinatorState`

Top-level coordinator state.  Built once per session and evolved as the
session progresses.

```python
from contracts.mesh_session_coordinator import (
    MeshSessionCoordinatorState,
    build_mesh_session_coordinator,
    from_mesh_session,
)

from contracts.mesh_session import build_mesh_session

# Build from a mesh session
session = build_mesh_session(
    source_device_id="phone_001",
    primary_device_id="tablet_002",
    mesh_id="mesh_alpha",
)
coordinator = from_mesh_session(session)
print(coordinator.to_json(indent=2))
```

**Key fields:**

| Field | Type | Description |
|---|---|---|
| `coordinator_id` | `str` | Stable globally-unique coordinator identifier |
| `session_id` | `str?` | Links to PR-33 MeshSession |
| `mesh_id` | `str?` | Optional mesh/body identifier |
| `trace_id` | `str?` | Links to PR-25 ExecutionTraceEnvelope |
| `task_id` | `str?` | Correlates to originating task |
| `status` | `MeshCoordinatorStatus` | Overall coordinator lifecycle status |
| `participants` | `List[MeshParticipantCoordinationState]` | Per-device coordination state |
| `assignments` | `List[MeshAssignmentState]` | Per-subtask assignment state |
| `barrier_state` | `MeshBarrierState` | Synchronisation barrier state |
| `merge_owner_device_id` | `str?` | Device responsible for result merging |
| `pending_device_ids` | `List[str]` | Devices with in-progress assignments |
| `completed_device_ids` | `List[str]` | Devices with completed assignments |
| `failed_device_ids` | `List[str]` | Devices with failed assignments |
| `coordination_events` | `List[MeshCoordinationEvent]` | Advisory event log |
| `result_merge_summary` | `Dict?` | Optional PR-36 merge summary |

---

### `MeshParticipantCoordinationState`

Per-device coordination state tracked by the coordinator.

| Field | Type | Description |
|---|---|---|
| `device_id` | `str` | Stable device identifier |
| `runtime_id` | `str?` | Optional runtime/session ID on this device |
| `roles` | `List[str]` | Roles: `primary`, `support`, `fallback`, `relay`, `observer` |
| `online` | `bool?` | Whether device is reachable |
| `ready` | `bool?` | Whether device has confirmed readiness |
| `status` | `MeshParticipantStatus` | Participant lifecycle status |
| `last_seen` | `float?` | Unix timestamp of last signal |

---

### `MeshAssignmentState`

Per-subtask assignment tracked by the coordinator.

| Field | Type | Description |
|---|---|---|
| `subtask_id` | `str` | Stable subtask identifier |
| `device_id` | `str` | Assigned device |
| `status` | `MeshAssignmentStatus` | Assignment lifecycle status |
| `capability_required` | `str?` | Required device capability |
| `handoff_id` | `str?` | Links to PR-31 HandoffEnvelopeV2 |
| `result_unit_id` | `str?` | Links to PR-36 RuntimeResultUnit |

---

### `MeshBarrierState`

Synchronisation barrier state.

| Field | Type | Description |
|---|---|---|
| `status` | `MeshBarrierStatus` | `not_required`, `open`, `waiting`, `released`, `failed`, `unknown` |
| `waiting_device_ids` | `List[str]` | Devices blocked at the barrier |
| `released` | `bool` | Whether barrier has been released |
| `barrier_reason` | `str?` | Human-readable explanation |

---

### `MeshSessionCoordinatorSummary`

Lightweight read-only summary suitable for projection endpoints.

| Field | Type | Description |
|---|---|---|
| `summary_id` | `str` | Stable summary snapshot ID |
| `coordinator_id` | `str?` | Source coordinator ID |
| `status` | `MeshCoordinatorStatus` | Overall coordinator status |
| `participant_count` | `int` | Total registered participants |
| `assignment_count` | `int` | Total subtask assignments |
| `pending_count` | `int` | Pending devices |
| `completed_count` | `int` | Completed devices |
| `failed_count` | `int` | Failed devices |
| `barrier_status` | `MeshBarrierStatus` | Barrier synchronisation status |
| `has_result_merge_summary` | `bool` | Whether merge summary is available |

---

## Participant Readiness / Assignment / Barrier / Merge Status

### Readiness flow

1. Device registers via `BodyMeshRegistry` → appears in `participants` with `status=pending`.
2. Device confirms readiness → `status=ready`.
3. Assignment dispatched → `status=working`, assignment `status=dispatched`.
4. Work completes → `status=completed`, assignment `status=completed`, device moves to `completed_device_ids`.
5. If work fails → `status=failed`, device moves to `failed_device_ids`.

### Assignment lifecycle

```
pending → dispatched → accepted → in_progress → completed
                                              ↘ failed
                                  cancelled
```

### Barrier lifecycle

```
not_required (no barrier needed)
unknown → open → waiting → released
                         → failed
```

The barrier status reflects the session's `barrier_posture` from PR-33:
- `hard_barrier` / `soft_barrier` → barrier `open` initially.
- `none` → barrier `not_required`.

### Merge lifecycle

When all `pending_device_ids` are empty and `completed_device_ids` is
non-empty, the coordinator transitions to `merging`.  After a
`MergedRuntimeResult` (PR-36) is applied, it transitions to `completed`
(or `partial` / `failed` based on the merge result).

---

## Builders and Adapters

### `build_mesh_session_coordinator(...)`

Convenience factory accepting all fields as keyword arguments.

```python
from contracts.mesh_session_coordinator import build_mesh_session_coordinator

state = build_mesh_session_coordinator(
    session_id="msess_abc",
    mesh_id="mesh_alpha",
    trace_id="trace_001",
)
```

### `from_mesh_session(mesh_session, ...)`

Build coordinator state from a PR-33 `MeshSession`.

```python
from contracts.mesh_session_coordinator import from_mesh_session
from contracts.mesh_session import build_mesh_session

session = build_mesh_session(source_device_id="phone", primary_device_id="tablet")
coordinator = from_mesh_session(session)
```

### `update_coordinator_with_dispatch_result(coordinator, dispatch_result)`

Incorporate a PR-35 `SourceDispatchResult` into coordinator state.

### `update_coordinator_with_takeover_result(coordinator, takeover_result, device_id=...)`

Incorporate a PR-34 `LocalTakeoverResult` into coordinator state.

### `update_coordinator_with_merged_result(coordinator, merged_result)`

Incorporate a PR-36 `MergedRuntimeResult` into coordinator state.

### `build_coordinator_summary(coordinator=...)`

Build a lightweight `MeshSessionCoordinatorSummary` from coordinator state.

---

## Integration Points

### `core/mesh/body_mesh_registry.py`

`BodyMeshRegistry.get_mesh_session_coordinator()` builds a coordinator from
the live registry state:

```python
from core.mesh.body_mesh_registry import get_body_mesh_registry

registry = get_body_mesh_registry()
coordinator = registry.get_mesh_session_coordinator(mesh_id="default_mesh")
summary = coordinator.to_compact_summary()
```

### `core/mesh/mesh_session_coordinator.py`

High-level module with `MeshSessionCoordinator` class and convenience functions:

```python
from core.mesh.mesh_session_coordinator import (
    MeshSessionCoordinator,
    coordinate_mesh_session,
    get_coordinator_summary,
)

handler = MeshSessionCoordinator()
state = handler.from_mesh_session(mesh_session)
state = handler.update_with_takeover_result(state, takeover_result, device_id="tablet")
summary = handler.get_summary(state)
```

### REST API — `GET /api/v1/mesh/coordinator-summary`

Returns a `MeshSessionCoordinatorSummary` JSON payload derived from the
live registry state.  Read-only.  Degrades gracefully.

---

## Serialisation

All contracts are fully serialisable:

```python
# to_dict / to_json
d = coordinator.to_dict()
j = coordinator.to_json(indent=2)

# Round-trip
from contracts.mesh_session_coordinator import MeshSessionCoordinatorState
recovered = MeshSessionCoordinatorState.from_dict(d)
assert recovered.coordinator_id == coordinator.coordinator_id
```

---

## Explicit Non-Goals

This PR does **not** implement:

- A full distributed scheduler or task queue.
- An advanced recovery / reconciliation engine.
- Persistence or streaming of coordinator state.
- UI / dashboard redesign.
- Broad execution-core rewrites.
- Full registration-flow rewrites.
- Node_71 major rewrites.

These are deferred to future PRs (PR-38 and beyond).

---

## Dependencies

| PR | Contract | Role |
|---|---|---|
| PR-32 | `MeshMembership` | Participant role definitions |
| PR-33 | `MeshSession` | Session seeding |
| PR-34 | `LocalTakeoverResult` | Target-side update input |
| PR-35 | `SourceDispatchResult` | Source-side update input |
| PR-36 | `MergedRuntimeResult` | Merge completion input |

---

## Future Work

- PR-38: Unified Multi-Device Runtime Projection — may consume coordinator summary.
- Recovery / reconciliation: can use `failed_device_ids` and `barrier_state` to drive re-dispatch.
- Durable coordinator state: persist `MeshSessionCoordinatorState` for session replay.

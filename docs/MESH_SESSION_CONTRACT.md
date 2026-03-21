# Mesh Session Contract

**PR-33** — Canonical Multi-Device Session Contract

---

## Overview

The **Mesh Session Contract** (`contracts/mesh_session.py`) answers the canonical architectural question:

> "When multiple devices cooperate on one task flow, what is the canonical session object that represents that cooperation?"

A `MeshSession` is a **single, fully serialisable contract** that captures everything needed to understand a multi-device cooperative execution session:

- **Who participates** — `participants` (list of `MeshSessionParticipant`)
- **Who initiated** — `source_device_id`
- **Who executes primarily** — `primary_device_id`
- **Who owns the merge** — `merge_owner_device_id`
- **How subtasks are distributed** — `subtask_assignments` (list of `MeshSubtaskAssignment`)
- **How results are merged** — `merge_policy` (`MeshMergePolicy`)
- **How devices synchronise** — `barrier_posture` (`MeshBarrierPosture`)
- **What is the session's lifecycle state** — `status` (`MeshSessionStatus`)

---

## What a Mesh Session Is (and Is Not)

### What It Is

A `MeshSession` is a **read-only, snapshot-style contract**. It:

- Represents a cooperative multi-device execution context at a point in time.
- Is the canonical way to express "who is in this session and what are they doing".
- Is the foundation for later coordinator and takeover work (PR-34, PR-35, PR-37).
- Is fully serialisable to/from JSON.
- Is tolerant of partial data — all fields except `session_id` are optional.

### How It Differs from Mesh Membership (PR-32)

| Aspect | `MeshMembership` (PR-32) | `MeshSession` (PR-33) |
|---|---|---|
| **Scope** | A single device's membership in a mesh/body | An entire cooperative session across all participants |
| **Granularity** | Per-device | Per-session |
| **Subtask tracking** | Not included | Included via `subtask_assignments` |
| **Merge/barrier semantics** | Not included | Included via `merge_policy` / `barrier_posture` |
| **Source vs. primary** | Not explicitly distinguished | Explicitly tracked (`source_device_id` vs. `primary_device_id`) |

### How It Differs from Device Formation Summaries (PR-17)

| Aspect | Formation Summary (PR-17) | `MeshSession` (PR-33) |
|---|---|---|
| **Source** | Formation/projection layer | Contract layer |
| **Serialisability** | Variable | Guaranteed JSON-stable |
| **Subtask assignments** | Not included | Included |
| **Session lifecycle** | Not included | Included via `status` |
| **Usage** | Formation planning | Runtime session tracking |

---

## Contract Types

### `MeshSession`

Top-level contract representing one multi-device session.

```python
from contracts.mesh_session import MeshSession, build_mesh_session

session = build_mesh_session(
    source_device_id="phone_001",
    primary_device_id="tablet_002",
    mesh_id="mesh_alpha",
)
print(session.to_json(indent=2))
```

**Key fields:**

| Field | Type | Description |
|---|---|---|
| `session_id` | `str` | Stable globally-unique session identifier |
| `trace_id` | `str?` | Links to PR-25 ExecutionTraceEnvelope |
| `task_id` | `str?` | Correlates to an originating task |
| `mesh_id` | `str?` | Links to a formation or mesh membership |
| `source_device_id` | `str` | Device that initiated the session |
| `primary_device_id` | `str` | Primary executor device |
| `merge_owner_device_id` | `str?` | Device responsible for merging results |
| `participants` | `List[MeshSessionParticipant]` | All participating devices |
| `subtask_assignments` | `List[MeshSubtaskAssignment]` | Per-device subtask records |
| `barrier_posture` | `MeshBarrierPosture` | Synchronisation barrier semantics |
| `merge_policy` | `MeshMergePolicy` | How results are merged |
| `multi_device_required` | `bool` | Whether multi-device is required |
| `merge_confirmation_required` | `bool` | Whether confirmation is needed before merge |
| `status` | `MeshSessionStatus` | Lifecycle state |
| `created_at` / `updated_at` | `float` | Unix timestamps |
| `metadata` | `Dict` | Arbitrary extension data |

### `MeshSessionParticipant`

One device's participation record within a session.

| Field | Type | Description |
|---|---|---|
| `device_id` | `str` | Device identifier |
| `runtime_id` | `str?` | Optional LocalRuntimeHost ID (PR-30) |
| `roles` | `List[str]` | e.g. `['primary', 'source']` |
| `authority_scope` | `str?` | e.g. `'mesh_authority'`, `'execution_authority'` |
| `online` | `bool?` | Was device online at session creation? |
| `health_score` | `float?` | Health score [0.0, 1.0] |
| `metadata` | `Dict` | Extension data |

### `MeshSubtaskAssignment`

One subtask's device assignment within a session.

| Field | Type | Description |
|---|---|---|
| `subtask_id` | `str` | Unique subtask ID |
| `device_id` | `str` | Assigned device |
| `capability_required` | `str?` | Required device capability or type |
| `status` | `str` | `pending` / `running` / `success` / `failed` / `skipped` / `cancelled` |
| `result_ref` | `str?` | Reference to the result artefact |
| `metadata` | `Dict` | Extension data |

### `MeshSessionStatus`

| Value | Meaning |
|---|---|
| `pending` | Session created, participants not yet confirmed |
| `active` | Execution in progress |
| `merging` | Subtasks done, merge in progress |
| `completed` | All done successfully |
| `cancelled` | Cancelled before completion |
| `failed` | Unrecoverable failure |
| `unknown` | Status could not be determined |

### `MeshMergePolicy`

| Value | Meaning |
|---|---|
| `no_merge` | Results are independent |
| `sequential` | Results merged in completion order |
| `parallel` | Results merged in any order |
| `barrier` | Synchronisation barrier before merge |
| `owner_decides` | Merge owner determines strategy |
| `unknown` | Not yet determined |

### `MeshBarrierPosture`

| Value | Meaning |
|---|---|
| `no_barrier` | No synchronisation required |
| `wait_primary` | Wait for primary device signal |
| `wait_all` | All participants must signal |
| `wait_merge_owner` | Wait for merge-owner signal |
| `soft_barrier` | Best-effort barrier |
| `unknown` | Not yet determined |

---

## Adapters / Builders

### `from_device_formation_summary(summary, session_id, task_id, trace_id, status)`

Builds a `MeshSession` from a `FormationSummary` (`core.device_formation`).

```python
from core.device_formation import resolve_formation_summary
from contracts.mesh_session import from_device_formation_summary

summary = resolve_formation_summary()
session = from_device_formation_summary(
    summary,
    task_id="task_001",
    trace_id="trace_abc",
)
print(session.to_dict())
```

Maps: `formation_id` → `mesh_id`, `source_device_id`, `primary_execution_device_id` → `primary_device_id`, `barrier_posture`, `merge_policy`, `multi_device_required`, fallback/support/observer/relay device IDs → `participants`.

### `from_cross_device_routing_summary(summary, session_id, task_id, trace_id, status)`

Builds a `MeshSession` from a `CrossDeviceAssignmentSummary` (`core.cross_device_policy`).

```python
from core.cross_device_policy import build_assignment_summary, DEFAULT_LOCAL_ROUTING_POLICY
from contracts.mesh_session import from_cross_device_routing_summary

routing = build_assignment_summary(DEFAULT_LOCAL_ROUTING_POLICY)
session = from_cross_device_routing_summary(routing)
```

Maps routing posture to merge policy / barrier posture:
- `split_execution` → `parallel` merge, `wait_all` barrier
- `sequential` → `sequential` merge, `wait_primary` barrier
- `remote_required` → `no_merge`, `no_barrier`

### `from_constellation_decomposition(decomposition, session_id, task_id, trace_id, source_device_id, primary_device_id, mesh_id, status)`

Builds a `MeshSession` from a `TaskDecomposition` (`core.schemas.orchestration`).

```python
from core.schemas.orchestration import TaskDecomposition
from contracts.mesh_session import from_constellation_decomposition

session = from_constellation_decomposition(
    decomposition=decomp,
    session_id="sess_abc",
    source_device_id="phone_001",
    primary_device_id="phone_001",
    task_id="task_xyz",
)
```

Materialises `subtask_assignments` from `decomposition.subtasks`. Infers session status from subtask statuses (all success → `completed`, any failed → `failed`, any running → `active`). Infers `multi_device_required` when subtasks span multiple device IDs.

### `build_mesh_session(source_device_id, primary_device_id, **kwargs)`

Generic convenience factory for constructing a `MeshSession` from scratch.

```python
from contracts.mesh_session import build_mesh_session, MeshSessionStatus, MeshMergePolicy

session = build_mesh_session(
    source_device_id="phone_001",
    primary_device_id="tablet_002",
    mesh_id="mesh_beta",
    status=MeshSessionStatus.ACTIVE,
    merge_policy=MeshMergePolicy.PARALLEL,
    multi_device_required=True,
)
```

### `BodyMeshRegistry.get_mesh_session(mesh_id, session_id)`

Integration helper on `BodyMeshRegistry` that normalises registered `BodyEntry` objects into a canonical `MeshSession` contract.

```python
from core.mesh.body_mesh_registry import get_body_mesh_registry

registry = get_body_mesh_registry()
session = registry.get_mesh_session(mesh_id="default_mesh")
print(session.to_compact_summary())
```

The highest-scoring entry is treated as primary; the lowest-scoring (if different) as source.

---

## Normalisation Sources

| Source | Adapter | What it provides |
|---|---|---|
| `core.device_formation.FormationSummary` | `from_device_formation_summary` | Device roles, barrier/merge, multi-device flag |
| `core.cross_device_policy.CrossDeviceAssignmentSummary` | `from_cross_device_routing_summary` | Routing posture → merge/barrier, assigned devices |
| `core.schemas.orchestration.TaskDecomposition` | `from_constellation_decomposition` | Subtask assignments, per-device status, multi-device flag |
| `core.mesh.body_mesh_registry.BodyMeshRegistry` | `BodyMeshRegistry.get_mesh_session()` | Live participant list from registry state |

---

## Exports

The contract is available from both the `contracts` package and `core.unified`:

```python
# From contracts.mesh_session directly
from contracts.mesh_session import (
    MeshSession,
    MeshSessionParticipant,
    MeshSubtaskAssignment,
    MeshMergePolicy,
    MeshBarrierPosture,
    MeshSessionStatus,
    from_device_formation_summary,
    from_cross_device_routing_summary,
    from_constellation_decomposition,
    build_mesh_session,
)

# From contracts package root
from contracts import MeshSession, build_mesh_session

# From core.unified
from core.unified import MeshSession, build_mesh_session
```

Note: to avoid colliding with PR-32's `from_device_formation_summary` and `from_cross_device_routing_summary` (which return `MeshMembership` objects), the `contracts` package and `core.unified` re-export the PR-33 adapters under the aliases:
- `mesh_session_from_formation` → `contracts.mesh_session.from_device_formation_summary`
- `mesh_session_from_routing` → `contracts.mesh_session.from_cross_device_routing_summary`

---

## REST API

### `GET /api/v1/mesh/session`

Returns the current mesh session contract derived from the `BodyMeshRegistry` state.

**Response:**

```json
{
  "session_id": "msess_abc123def456",
  "status": "pending",
  "source_device_id": "phone_001",
  "primary_device_id": "tablet_002",
  "merge_owner_device_id": null,
  "mesh_id": "default_mesh",
  "task_id": null,
  "trace_id": null,
  "participants": [
    {
      "device_id": "phone_001",
      "runtime_id": null,
      "roles": ["source"],
      "authority_scope": null,
      "online": true,
      "health_score": 0.5,
      "metadata": {}
    },
    {
      "device_id": "tablet_002",
      "runtime_id": null,
      "roles": ["primary"],
      "authority_scope": null,
      "online": true,
      "health_score": 0.9,
      "metadata": {}
    }
  ],
  "subtask_assignments": [],
  "barrier_posture": "unknown",
  "merge_policy": "unknown",
  "multi_device_required": true,
  "merge_confirmation_required": false,
  "created_at": 1234567890.0,
  "updated_at": 1234567890.0,
  "metadata": {"adapter_source": "BodyMeshRegistry.get_mesh_session"}
}
```

This endpoint is **read-only** and **additive**. It does not modify any existing registry, projection, or orchestration module.

---

## What This PR Explicitly Does Not Do

This PR establishes the canonical session contract but deliberately **does not** include:

- **No Mesh Session Coordinator execution engine** — that is PR-37.
- **No target runtime local takeover path** — that is PR-34.
- **No source runtime dispatch orchestrator** — that is PR-35.
- **No handoff protocol redesign** — already in PR-31.
- **No write-capable session APIs** — all surfaces are read-only.
- **No persistence or streaming redesign** — out of scope.
- **No UI/dashboard redesign** — out of scope.
- **No full registration-flow rewrite** — out of scope.

---

## Participant Roles

Participant roles are plain strings (not an enum) for forward-compatibility. The following values are defined by convention:

| Role | Description |
|---|---|
| `source` | Device that originated the session |
| `primary` | Primary executor device |
| `support` | Co-execution / support device |
| `fallback` | Fallback device (promoted if primary fails) |
| `observer` | Receives events, does not act |
| `relay` | Forwards tasks/results between members |
| `merge_owner` | Responsible for merging distributed results |

A device may carry multiple roles simultaneously (e.g. `["source", "primary"]`).

---

## Relationship to the Contract Chain

| PR | Contract | Answers |
|---|---|---|
| PR-25 | ExecutionTraceEnvelope | What happened during execution? |
| PR-26 | ProjectionAssemblyGovernance | Is the projection valid? |
| PR-27 | RuntimeGovernanceSnapshot | What is the current governance posture? |
| PR-28 | ExecutionPolicyAlignmentSurface | Are policies aligned for execution? |
| PR-29 | RegisteredRuntimeDevice | What is this runtime-capable device? |
| PR-30 | LocalRuntimeHost | What must a local runtime host expose? |
| PR-31 | HandoffEnvelopeV2 | What does a cross-device handoff carry? |
| PR-32 | MeshMembership | How does a device participate in a mesh? |
| **PR-33** | **MeshSession** | **What is the multi-device cooperative session?** |
| PR-34 | *(planned)* LocalTakeoverPath | How does a target runtime take over? |
| PR-35 | *(planned)* SourceDispatchOrchestrator | How does the source orchestrate dispatch? |
| PR-37 | *(planned)* MeshSessionCoordinator | Who coordinates the session? |

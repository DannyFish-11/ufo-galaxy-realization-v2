# Live Mesh Session Coordination

> **Closes MESH-001 and MESH-002** from `docs/DUAL_REPO_GAP_MATRIX.md`.
>
> This document describes how mesh/session coordination is **actively driven**
> rather than only modeled by static contract shapes.

---

## Overview

Galaxy multi-device coordination uses three co-operating runtime components:

| Component | Module | Role |
|---|---|---|
| `LiveMeshRuntimeEngine` | `core/mesh/live_mesh_runtime_engine.py` | Stateless **batch** engine: given a snapshot of all participant results, drives `MeshSessionCoordinatorState` to completion in one shot |
| `LiveMeshSessionCoordinator` | `core/mesh/live_mesh_session_coordinator.py` | Stateful **incremental** coordinator: accepts participant lifecycle events one at a time, drives `MeshSessionCoordinatorState` |
| `MeshSessionProgressionDriver` | `core/mesh/mesh_session_progression_driver.py` | Stateful **progression** driver: bridges `MeshSession` ↔ `LiveMeshSessionCoordinator`, driving both `MeshSession.status` (from `contracts/mesh_session.py`) and `MeshSubtaskAssignment.status` in lock-step with participant events |

---

## How Barrier Wait Behaves

Barrier wait is **runtime-driven**, not passively modelled:

1. When a participant calls `on_participant_result()`, the result is stored
   and the barrier is re-evaluated.
2. The session remains in `ACTIVE` status while any participant has not yet
   submitted a result (barrier not released).
3. When **all** participants have submitted results (or been dropped/failed),
   the coordinator marks the barrier as `released` and advances the session to
   `MERGING`.
4. No caller action is required to trigger the merge step; it happens
   automatically.

```python
driver = MeshSessionProgressionDriver(session)
driver.add_participant("device_a")
driver.add_participant("device_b")

driver.on_participant_result("device_a", {"output": "part_a"})
# Barrier NOT yet released — only one of two arrived
assert driver.session.status == MeshSessionStatus.ACTIVE

driver.on_participant_result("device_b", {"output": "part_b"})
# Barrier released — all arrived → MERGING
assert driver.session.status == MeshSessionStatus.MERGING
```

---

## How Assignment Progression Behaves

`MeshSubtaskAssignment.status` is updated in lock-step with participant events:

| Participant event | Assignment status |
|---|---|
| `on_participant_working(device_id)` | `"running"` |
| `on_participant_result(device_id, ...)` | `"success"` |
| `on_participant_failed(device_id, ...)` | `"failed"` |
| `on_participant_dropped(device_id, ...)` | `"failed"` |

```python
driver.on_participant_working("device_a")
assert session.subtask_assignments[0].status == "running"

driver.on_participant_result("device_a", {"x": 1})
assert session.subtask_assignments[0].status == "success"
```

---

## How Merge Triggering Behaves

Merge is triggered automatically when the barrier is released:

1. `on_participant_result()` stores the result and re-evaluates the barrier.
2. When barrier is released, the coordinator advances to `merging`.
3. `MeshSession.status` transitions to `MERGING`.
4. `finalize()` runs the batch `LiveMeshRuntimeEngine` to aggregate all
   participant results into a merged output dict.
5. `MeshSession.status` transitions to `COMPLETED` (or `FAILED`).

```python
result = driver.finalize()
assert result.outcome == "completed"
assert result.session.status == MeshSessionStatus.COMPLETED
assert "_participants" in result.run_result.merged_result
```

---

## Session Status Lifecycle

```
PENDING
  │
  ├─ (first participant starts working)
  │
ACTIVE
  │
  ├─ (all participants submit results / barrier released)
  │
MERGING
  │
  ├─ (finalize() called)
  │
COMPLETED   ← all or some participants succeeded
FAILED      ← all participants failed / dropped
```

---

## Full Example

```python
from contracts.mesh_session import build_mesh_session, MeshSubtaskAssignment
from core.mesh.mesh_session_progression_driver import (
    MeshSessionProgressionDriver,
    create_progression_driver,
)

# 1. Build a session with two subtask assignments
session = build_mesh_session(
    source_device_id="desktop",
    primary_device_id="desktop",
    mesh_id="mesh_alpha",
    subtask_assignments=[
        MeshSubtaskAssignment(device_id="phone_01", status="pending"),
        MeshSubtaskAssignment(device_id="tablet_02", status="pending"),
    ],
)

# 2. Create the driver
driver = MeshSessionProgressionDriver(session)

# 3. Register participants
driver.add_participant("phone_01", roles=["primary"])
driver.add_participant("tablet_02", roles=["support"])

# 4. Emit lifecycle events as participants progress
driver.on_participant_ready("phone_01")
driver.on_participant_working("phone_01")
# → MeshSession.status = ACTIVE
# → subtask_assignments[phone_01].status = "running"

driver.on_participant_ready("tablet_02")
driver.on_participant_working("tablet_02")
# → subtask_assignments[tablet_02].status = "running"

driver.on_participant_result("phone_01", {"ocr_text": "Galaxy UI"})
# → subtask_assignments[phone_01].status = "success"
# → barrier still waiting for tablet_02

driver.on_participant_result("tablet_02", {"screenshot": "base64..."})
# → subtask_assignments[tablet_02].status = "success"
# → barrier released — MeshSession.status = MERGING

# 5. Finalize and inspect result
result = driver.finalize()
assert result.outcome == "completed"
assert result.success is True
assert result.session.status.value == "completed"
assert result.run_result.barrier_released is True
print(result.run_result.merged_result)
# {"ocr_text": "Galaxy UI", "screenshot": "base64...",
#  "_participants": ["phone_01", "tablet_02"]}
```

---

## Convenience Factory

```python
# Without an existing session — build from kwargs
driver = create_progression_driver(
    source_device_id="desktop",
    primary_device_id="desktop",
    mesh_id="mesh_beta",
    barrier_timeout_seconds=60.0,
)
```

---

## Thread Safety

All public methods on `MeshSessionProgressionDriver` are thread-safe.  A
single `threading.Lock` guards all state mutations.  Participant results may
be emitted from multiple threads simultaneously without data corruption.

---

## Partial and Failure Outcomes

| Scenario | `outcome` | `MeshSession.status` |
|---|---|---|
| All participants succeed | `"completed"` | `COMPLETED` |
| Some succeed, some fail | `"partial"` | `COMPLETED` |
| All participants fail / drop | `"failed"` | `FAILED` |

```python
# Partial failure
driver.on_participant_result("device_a", {"x": 1})
driver.on_participant_failed("device_b", reason="subtask_error")
result = driver.finalize()
assert result.outcome == "partial"
assert result.success is True  # partial counts as success
```

---

## Re-exports

All types and sentinels are re-exported at the package level:

```python
# From core.runtime
from core.runtime import (
    MeshSessionProgressionDriver,
    MeshSessionProgressionFinalResult,
    create_progression_driver,
    MESH_SESSION_PROGRESSION_DRIVER_SENTINEL,
    SESSION_STATUS_DRIVEN_BY_COORDINATOR_POLICY,
    SUBTASK_ASSIGNMENT_STATUS_DRIVEN_BY_PARTICIPANT_POLICY,
    MERGE_TRIGGERED_WHEN_BARRIER_RELEASED_POLICY,
)

# From core.mesh.mesh_session_coordinator
from core.mesh.mesh_session_coordinator import (
    MeshSessionProgressionDriver,
    create_progression_driver,
)
```

---

## Tests

- `tests/test_mesh_session_progression_driver.py` — 60 tests covering:
  - Session status lifecycle (Groups D, G)
  - Assignment status progression (Group E)
  - Barrier semantics (Group F)
  - Partial and failure outcomes (Groups H, I, J)
  - Thread-safety (Group L)
  - Re-exports (Group M)
- `tests/test_live_mesh_session_coordinator.py` — 70 tests covering incremental coordinator
- `tests/test_prj_live_mesh_runtime_engine.py` — 77 tests covering batch engine

---

## Gap Matrix Status

| Gap | Status |
|---|---|
| MESH-001: No live coordinator engine | **RESOLVED** — `LiveMeshRuntimeEngine` + `LiveMeshSessionCoordinator` |
| MESH-002: MeshSessionStatus not driven | **RESOLVED** — `MeshSessionProgressionDriver` |

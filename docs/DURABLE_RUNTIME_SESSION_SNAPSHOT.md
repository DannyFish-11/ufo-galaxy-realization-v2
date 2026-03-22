# Durable Runtime Session Snapshot Contract

> **PR-40** — Canonical durable read-model for a runtime session.
>
> Module: `contracts/runtime_session_snapshot.py`

---

## Overview

The **Durable Runtime Session Snapshot Contract** introduces a single, stable,
fully serialisable object — `RuntimeSessionSnapshot` — that captures all
known state of a runtime session at a specific point in time.

It answers the architectural question:

> *"If we need one stable snapshot of a runtime session that can be persisted,
> reloaded, projected, or inspected later, what is the canonical contract
> for that snapshot?"*

This contract is the foundation for later persistence, replay, audit,
and recovery automation work.

---

## How it differs from related contracts

| Contract | Purpose |
|----------|---------|
| `MultiDeviceRuntimeProjection` (PR-38) | Live, continuously-updated multi-device **read model** |
| `MeshSession` (PR-33) | Mesh-specific session **membership and assignment** state |
| `MeshSessionCoordinatorState` (PR-37) | Coordination **event log and barrier** state |
| `RuntimeReconciliationState` (PR-39) | **Recovery and reconciliation** advisory posture |
| **`RuntimeSessionSnapshot` (PR-40)** | **Durable, point-in-time snapshot** for persistence/replay/audit |

A `RuntimeSessionSnapshot` is intentionally **not** a live projection.
It is a stable snapshot taken at a specific moment: the last-known state
of all relevant session components, packaged into one durable object.

---

## Snapshot Contracts

### `RuntimeSessionSnapshot` (top-level)

The canonical durable snapshot.  See `contracts/runtime_session_snapshot.py`
for the full field reference.

Key fields:

| Field | Type | Description |
|-------|------|-------------|
| `snapshot_id` | `str` | `rsnap_<hex>` — stable unique ID for this snapshot |
| `session_id` | `str` | The runtime session this snapshot belongs to |
| `trace_id` | `Optional[str]` | Execution trace identifier (PR-25) |
| `task_id` | `Optional[str]` | Task identifier |
| `mesh_session_id` | `Optional[str]` | Mesh session identifier (PR-33) |
| `source_device_id` | `Optional[str]` | Originating device |
| `primary_device_id` | `Optional[str]` | Primary/authoritative device |
| `created_at` | `float` | Unix epoch seconds — snapshot creation time |
| `updated_at` | `float` | Unix epoch seconds — snapshot last update time |
| `status` | `str` | `RuntimeSessionSnapshotStatus` enum value |
| `runtime_devices` | `List[Dict]` | Compact registered device entries (PR-29) |
| `runtime_hosts` | `List[Dict]` | Compact local runtime host entries (PR-30) |
| `mesh_memberships` | `List[Dict]` | Compact mesh membership entries (PR-32) |
| `mesh_session` | `Optional[Dict]` | Mesh session state snapshot (PR-33) |
| `dispatch_state` | `Optional[RuntimeSessionSnapshotDispatchState]` | Source dispatch state (PR-35) |
| `takeover_states` | `List[RuntimeSessionSnapshotTakeoverState]` | Target takeover states (PR-34) |
| `coordinator_state` | `Optional[RuntimeSessionSnapshotCoordinatorState]` | Coordinator state (PR-37) |
| `merged_result` | `Optional[RuntimeSessionSnapshotResultState]` | Merged result state (PR-36) |
| `recovery_state` | `Optional[RuntimeSessionSnapshotRecoveryState]` | Recovery posture (PR-39) |
| `governance_snapshot` | `Optional[Dict]` | Governance snapshot (PR-27) |
| `policy_alignment` | `Optional[Dict]` | Policy alignment (PR-28) |
| `metadata` | `Dict[str, Any]` | Arbitrary extensibility bag |

### `RuntimeSessionSnapshotStatus` (enum)

| Value | Description |
|-------|-------------|
| `active` | Session currently in progress |
| `completed` | Session completed successfully |
| `failed` | Session ended in failure |
| `partial` | Session partially completed |
| `interrupted` | Session interrupted before completion |
| `recovering` | Session in a recovery cycle |
| `unknown` | Status cannot be determined |

### Sub-contracts

| Contract | From PR | Description |
|----------|---------|-------------|
| `RuntimeSessionSnapshotIdentity` | — | Identity block (IDs + timestamps) |
| `RuntimeSessionSnapshotDispatchState` | PR-35 | Source dispatch state snapshot |
| `RuntimeSessionSnapshotTakeoverState` | PR-34 | Per-device takeover state snapshot |
| `RuntimeSessionSnapshotCoordinatorState` | PR-37 | Coordinator state snapshot |
| `RuntimeSessionSnapshotResultState` | PR-36 | Merged result state snapshot |
| `RuntimeSessionSnapshotRecoveryState` | PR-39 | Recovery posture snapshot |
| `RuntimeSessionSnapshotSummary` | — | Lightweight summary for embedding |

---

## Usage

### Build directly

```python
from contracts.runtime_session_snapshot import (
    RuntimeSessionSnapshot,
    build_runtime_session_snapshot,
    build_runtime_session_snapshot_summary,
)

# Build from explicit inputs
snapshot = build_runtime_session_snapshot(
    session_id="sess_abc123",
    trace_id="trace_xyz",
    source_device_id="phone_001",
    primary_device_id="tablet_002",
)
print(snapshot.to_json(indent=2))

# Build a compact summary
summary = build_runtime_session_snapshot_summary(snapshot)
print(summary.to_dict())
```

### Build from existing contracts

```python
from contracts.runtime_session_snapshot import (
    from_mesh_session,
    from_source_dispatch_result,
    from_target_takeover_result,
    from_result_merge,
    from_recovery_state,
    from_multi_device_runtime_projection,
)

# From mesh session (PR-33)
snapshot = from_mesh_session(mesh_session_obj)

# From source dispatch result (PR-35)
snapshot = from_source_dispatch_result(dispatch_result_obj)

# From target takeover result (PR-34)
snapshot = from_target_takeover_result(takeover_result_obj)

# From cross-runtime merged result (PR-36)
snapshot = from_result_merge(merged_result_obj)

# From runtime reconciliation state (PR-39)
snapshot = from_recovery_state(reconciliation_state_obj)

# From unified multi-device runtime projection (PR-38)
snapshot = from_multi_device_runtime_projection(projection_obj, session_id="sess_abc")
```

### Serialisation / round-trip

```python
# Serialise
d = snapshot.to_dict()           # JSON-safe dict
j = snapshot.to_json(indent=2)   # JSON string

# Deserialise
snapshot2 = RuntimeSessionSnapshot.from_dict(d)
assert snapshot2.snapshot_id == snapshot.snapshot_id
```

### Attach to MultiDeviceRuntimeProjection

```python
from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

projection = build_multi_device_runtime_projection(
    runtime_devices=[...],
    runtime_session_snapshot=snapshot.to_dict(),
)
assert projection.runtime_session_snapshot is not None
```

---

## REST API

### `GET /api/v1/projection/runtime/session-snapshot`

Returns a compact `RuntimeSessionSnapshotSummary` derived from the
current unified multi-device runtime projection.

**Example response:**

```json
{
  "summary_id": "rsnsum_abc1234567",
  "snapshot_id": "rsnap_def456789012",
  "session_id": "",
  "trace_id": null,
  "task_id": null,
  "mesh_session_id": null,
  "source_device_id": null,
  "primary_device_id": null,
  "status": "unknown",
  "runtime_device_count": 0,
  "runtime_host_count": 0,
  "mesh_membership_count": 0,
  "takeover_count": 0,
  "has_dispatch_state": false,
  "has_coordinator_state": false,
  "has_merged_result": false,
  "has_recovery_state": false,
  "has_mesh_session": false,
  "has_governance_snapshot": false,
  "has_policy_alignment": false,
  "created_at": 1711060572.0,
  "updated_at": 1711060572.0,
  "generated_at": 1711060572.5,
  "metadata": {}
}
```

Always returns HTTP 200; failures produce a minimal safe default response.

---

## Integration Points

### `contracts/runtime_session_snapshot.py`

Primary module.  All contracts, builders, and adapters.

```python
from contracts.runtime_session_snapshot import (
    RuntimeSessionSnapshot,
    build_runtime_session_snapshot,
    from_multi_device_runtime_projection,
)
```

### `contracts/__init__.py`

All public symbols re-exported from the contracts package root.

```python
from contracts import RuntimeSessionSnapshot, build_runtime_session_snapshot
```

### `core/unified/__init__.py`

All public symbols re-exported from the unified namespace.

```python
from core.unified import RuntimeSessionSnapshot, session_snapshot_from_projection
```

### `contracts/multi_device_runtime_projection.py`

`MultiDeviceRuntimeProjection` gains an optional `runtime_session_snapshot` field
(PR-40 additive).  `build_multi_device_runtime_projection` accepts a
`runtime_session_snapshot` keyword argument.

### `core/routes/projection.py`

New read-only route: `GET /api/v1/projection/runtime/session-snapshot`

---

## Explicit non-goals for this PR

This PR intentionally does **not** include:

- A database or persistence backend
- A write/save/load/replay engine
- UI/dashboard redesign
- Automatic session recovery automation
- Streaming or event-sourcing infrastructure
- Full registration-flow rewrite
- Any breaking changes to existing contracts or routes

---

## Architectural position

```
PR-25  Execution Trace Contract
PR-26  Projection Assembly Governance
PR-27  Runtime Governance Snapshot
PR-28  Execution Policy Alignment Surface
PR-29  Unified Registered Runtime Device Contract
PR-30  Local Runtime Host Contract
PR-31  Unified Handoff Envelope v2
PR-32  Mesh Membership Contract
PR-33  Mesh Session Contract
PR-34  Target Runtime Local Takeover Path
PR-35  Source Runtime Dispatch Orchestrator
PR-36  Cross-Runtime Result Merge Contract
PR-37  Mesh Session Coordinator
PR-38  Unified Multi-Device Runtime Projection
PR-39  Runtime Recovery and Reconciliation Contract
PR-40  Durable Runtime Session Snapshot Contract  ← this PR
```

PR-38 unified the multi-device runtime read-model.
PR-39 added recovery/reconciliation posture.
**PR-40 defines the durable snapshot object for runtime sessions** —
the canonical stable form for persistence, rehydration, audit, and replay.

---

## Design Principles

- **Additive only** — no existing module is modified beyond backward-compatible additions.
- **Fully serialisable** — `to_dict` / `to_json` / `from_dict` are stable and round-trippable.
- **Persistence-friendly** — stable field names; no storage-backend-specific semantics.
- **Tolerant of partial/missing data** — all builders and adapters accept `None` gracefully.
- **No UI semantics** — purely a runtime/persistence contract.
- **No write/persist engine** — this PR defines the contract shape only.

# Unified Multi-Device Runtime Projection

> **PR-38** — Read-only top-level projection of the multi-device runtime state.

> **V1 Authority Baseline:** `MultiDeviceRuntimeProjection` is the **canonical
> top-level multi-device read projection** for the Galaxy / OpenClawd system.
> It aggregates per-device `RegisteredRuntimeDevice` entries (the canonical
> single-device read contract) along with session, handoff, dispatch,
> coordination, and result state into a single coherent snapshot.  It sits
> **above** `RegisteredRuntimeDevice`, not beside it.  See
> `docs/architecture/unified_device_registration_runtime_participation_v1.md`
> for the normative V1 architecture spec.

## Overview

The **Unified Multi-Device Runtime Projection** is the canonical read-only
snapshot that answers:

> *"What is the current multi-device runtime state across devices, runtimes,
> sessions, dispatch decisions, handoffs, coordination, and merged results?"*

It provides a single, stable, serialisable object that aggregates all
multi-device runtime state surfaces introduced in PR-29 through PR-37.
Downstream consumers — observability, operator tooling, governance, routing,
and scheduling — should read this projection instead of assembling
cross-runtime state by piecing together multiple route payloads or contract
modules.

---

## Contract chain

| PR | Module | Answers |
|----|--------|---------|
| PR-25 | `contracts/execution_trace.py` | What happened during execution? |
| PR-26 | `core/projection/assembly_governance.py` | Is the projection valid? |
| PR-27 | `core/runtime_governance/snapshot.py` | What is the governance posture? |
| PR-28 | `core/runtime_governance/policy_alignment.py` | Are policies aligned? |
| PR-29 | `contracts/registered_runtime_device.py` | What runtime-capable devices exist? |
| PR-30 | `contracts/local_runtime_host.py` | What are the local runtime hosts? |
| PR-31 | `contracts/handoff_envelope_v2.py` | What does a cross-device handoff carry? |
| PR-32 | `contracts/mesh_membership.py` | How does a device participate in a mesh? |
| PR-33 | `contracts/mesh_session.py` | What is the cooperative multi-device session? |
| PR-34 | `contracts/local_takeover_result.py` | How did the target runtime take over? |
| PR-35 | `contracts/source_dispatch.py` | What dispatch decision did the source make? |
| PR-36 | `contracts/cross_runtime_result_merge.py` | How were multi-runtime results merged? |
| PR-37 | `contracts/mesh_session_coordinator.py` | What is the coordination state? |
| **PR-38** | **`contracts/multi_device_runtime_projection.py`** | **What is the full read-only runtime projection?** |

---

## Module

### `contracts/multi_device_runtime_projection.py`

The primary module.  Defines all serialisable contracts and builder functions.

#### Top-level projection contract

```python
from contracts.multi_device_runtime_projection import MultiDeviceRuntimeProjection

# Empty (always valid)
projection = MultiDeviceRuntimeProjection()
print(projection.to_json(indent=2))
```

**Stable fields:**

| Field | Type | Description |
|-------|------|-------------|
| `projection_id` | `str` | Globally-unique projection snapshot ID |
| `generated_at` | `float` | Unix timestamp when assembled |
| `runtime_devices` | `list[RuntimeProjectionDeviceEntry]` | PR-29 device entries |
| `runtime_hosts` | `list[RuntimeProjectionHostEntry]` | PR-30 host entries |
| `mesh_memberships` | `list[dict]` | PR-32 compact membership dicts |
| `mesh_sessions` | `list[RuntimeProjectionMeshSessionEntry]` | PR-33 session entries |
| `source_dispatches` | `list[RuntimeProjectionDispatchEntry]` | PR-35 dispatch entries |
| `handoff_summaries` | `list[RuntimeProjectionHandoffEntry]` | PR-31 handoff entries |
| `takeover_summaries` | `list[RuntimeProjectionTakeoverEntry]` | PR-34 takeover entries |
| `coordinator_summaries` | `list[RuntimeProjectionCoordinatorEntry]` | PR-37 coordinator entries |
| `merged_results` | `list[RuntimeProjectionResultEntry]` | PR-36 result entries |
| `governance_snapshot` | `dict \| None` | PR-27 compact governance dict |
| `policy_alignment` | `dict \| None` | PR-28 compact alignment dict |
| `metadata` | `dict` | Extensibility bag |

#### Sub-projection entry contracts

| Class | Source contract | PR |
|-------|-----------------|----|
| `RuntimeProjectionDeviceEntry` | `RegisteredRuntimeDevice` | PR-29 |
| `RuntimeProjectionHostEntry` | `LocalRuntimeHost` | PR-30 |
| `RuntimeProjectionMeshSessionEntry` | `MeshSession` | PR-33 |
| `RuntimeProjectionDispatchEntry` | `SourceDispatchSummary` | PR-35 |
| `RuntimeProjectionHandoffEntry` | `HandoffEnvelopeV2` | PR-31 |
| `RuntimeProjectionTakeoverEntry` | `LocalTakeoverResult` | PR-34 |
| `RuntimeProjectionCoordinatorEntry` | `MeshSessionCoordinatorSummary` | PR-37 |
| `RuntimeProjectionResultEntry` | `ResultMergeSummary` | PR-36 |

---

## Builder / adapter functions

### `build_multi_device_runtime_projection(**kwargs)`

The **canonical projection builder**.  Accepts all sub-contract inputs and
returns a fully populated `MultiDeviceRuntimeProjection`.

```python
from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

projection = build_multi_device_runtime_projection(
    runtime_devices=[device_contract_or_dict, ...],
    runtime_hosts=[host_contract_or_dict, ...],
    mesh_sessions=[session_contract_or_dict, ...],
    coordinator_summaries=[coordinator_summary_or_dict, ...],
    merged_results=[result_merge_summary_or_dict, ...],
    governance_snapshot=governance_snapshot_dict,   # optional
    policy_alignment=policy_alignment_dict,          # optional
)
print(projection.to_compact_summary())
```

All parameters are optional.  The function never raises.

### Per-block adapters

| Function | Input contracts |
|----------|----------------|
| `project_runtime_devices(runtime_devices)` | `RegisteredRuntimeDevice` / dicts |
| `project_runtime_hosts(runtime_hosts)` | `LocalRuntimeHost` / dicts |
| `project_mesh_sessions(mesh_sessions)` | `MeshSession` / dicts |
| `project_source_dispatches(source_dispatches)` | `SourceDispatchSummary` / dicts |
| `project_handoffs(handoff_summaries)` | `HandoffEnvelopeV2` / dicts |
| `project_takeovers(takeover_summaries)` | `LocalTakeoverResult` / dicts |
| `project_coordinator_state(coordinator_summaries)` | `MeshSessionCoordinatorSummary` / dicts |
| `project_merged_results(merged_results)` | `ResultMergeSummary` / dicts |

---

## REST API

### `GET /api/v1/projection/runtime/multi-device`

Returns the unified multi-device runtime projection assembled from live
system state.

**Response:**

```json
{
  "projection_id": "mdrt_proj_abc123def456",
  "generated_at": 1700000000.0,
  "runtime_devices": [
    {
      "device_id": "phone_001",
      "platform": "android",
      "form_factor": "phone",
      "status": "online",
      "connection_state": "connected",
      "runtime_capable": true,
      "health_score": 0.9,
      "metadata": {}
    }
  ],
  "runtime_hosts": [...],
  "mesh_memberships": [...],
  "mesh_sessions": [
    {
      "session_id": "msess_abc123",
      "mesh_id": "default_mesh",
      "status": "active",
      "source_device_id": "phone_001",
      "primary_device_id": "tablet_002",
      "participant_count": 2,
      "multi_device_required": true,
      "merge_policy": "parallel",
      "metadata": {}
    }
  ],
  "source_dispatches": [],
  "handoff_summaries": [],
  "takeover_summaries": [],
  "coordinator_summaries": [...],
  "merged_results": [],
  "governance_snapshot": null,
  "policy_alignment": null,
  "metadata": {}
}
```

**Behaviour:**
- Read-only (GET).  Never modifies any state.
- Degrades gracefully: if any sub-component is unavailable, it is omitted or
  returned as an empty list.
- Always returns a valid `MultiDeviceRuntimeProjection` JSON object.

---

## Package exports

### `contracts/__init__.py`

All PR-38 contracts and builders are re-exported from the top-level
`contracts` package:

```python
from contracts import (
    MultiDeviceRuntimeProjection,
    RuntimeProjectionDeviceEntry,
    RuntimeProjectionHostEntry,
    RuntimeProjectionMeshSessionEntry,
    RuntimeProjectionDispatchEntry,
    RuntimeProjectionHandoffEntry,
    RuntimeProjectionTakeoverEntry,
    RuntimeProjectionCoordinatorEntry,
    RuntimeProjectionResultEntry,
    build_multi_device_runtime_projection,
    project_runtime_devices,
    project_runtime_hosts,
    project_mesh_sessions,
    project_source_dispatches,
    project_handoffs,
    project_takeovers,
    project_coordinator_state,
    project_merged_results,
)
```

### `core/unified/__init__.py`

All PR-38 symbols are also re-exported from `core.unified`:

```python
from core.unified import (
    MultiDeviceRuntimeProjection,
    build_multi_device_runtime_projection,
    # ... etc.
)
```

---

## Relationship to lower-level contract modules

| Level | Description |
|-------|-------------|
| **PR-29–37 contracts** | Canonical per-domain contracts.  Answer individual questions about a single device, session, dispatch, etc. |
| **PR-38 projection** | Top-level read model.  Aggregates all of the above into a single coherent, serialisable snapshot. |

The projection does **not** replace the lower-level contracts — it wraps them
into compact entry records and presents them as a unified read model.  Callers
that need the full contract detail for a specific domain should use the
relevant lower-level contract module directly.

---

## What this PR explicitly does NOT do

- **No write / command route redesign** — this module is purely read-only.
- **No runtime code refactors** — purely additive.
- **No persistence / streaming redesign** — snapshot only; no event sourcing.
- **No advanced recovery engine** — outside scope.
- **No broad execution-core rewrite** — purely additive.
- **No full registration-flow rewrite** — uses existing registration contracts.

---

## Design principles

1. **Additive only** — no existing module is modified except for the
   backward-compatible `__all__` extensions in `contracts/__init__.py` and
   `core/unified/__init__.py`.
2. **Fully serialisable** — `to_dict()` / `to_json()` / `from_dict()` produce
   stable, round-trippable output for all contracts.
3. **Tolerant of partial/missing data** — all builders accept `None` inputs
   and all collection fields default to empty lists.
4. **Stable field names** — downstream consumers can rely on all field names.
5. **Read-only semantics** — the projection is a snapshot; it does not mutate
   state.
6. **UI-agnostic** — all contracts are defined for runtime, projection, and
   observability use.  Any future UI or dashboard is a downstream consumer of
   this projection; it does not drive the projection's design.

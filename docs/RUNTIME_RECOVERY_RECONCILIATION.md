# Runtime Recovery and Reconciliation Contract (PR-39)

## Overview

The **Runtime Recovery and Reconciliation Contract** is the canonical read-only advisory layer that describes how interrupted, partial, failed, or divergent multi-device runtime activity is represented, assessed, and reconciled across the source runtime, target runtime, mesh session, coordinator state, and merged results.

It answers the architectural question:

> "When multi-device runtime activity is interrupted, partially completed, or diverges across devices/runtimes, what canonical contract describes recovery posture and reconciliation state?"

**Module**: `contracts/runtime_recovery_reconciliation.py`

---

## Contract Hierarchy

```
RecoverySummary                          ← compact embedding for projections/routes
RuntimeReconciliationState               ← full reconciliation posture (multi-incident)
RuntimeRecoveryIncident                  ← single incident: one failure/divergence event
  ├── RecoveryParticipantState[]         ← per-participant recovery posture
  ├── RecoveryActionRecommendation[]     ← advisory actions (retry, resume, escalate…)
  └── RecoveryBarrierState               ← optional barrier blocking recovery
```

---

## Contracts

### `RuntimeRecoveryIncident`

The primary advisory contract for a single runtime interruption or failure.

| Field | Type | Description |
|-------|------|-------------|
| `recovery_id` | `str` | Stable, globally-unique incident identifier |
| `generated_at` | `float` | Unix epoch seconds when the incident was recorded |
| `trace_id` | `str?` | Optional link to an execution trace |
| `task_id` | `str?` | Optional task identifier |
| `session_id` | `str?` | Optional runtime session identifier |
| `mesh_session_id` | `str?` | Optional mesh session identifier |
| `source_device_id` | `str?` | Device that initiated the operation |
| `primary_device_id` | `str?` | Device designated as primary for merge/authority |
| `incident_type` | `str` | Categorical incident type (see `RecoveryIncidentType`) |
| `status` | `str` | Lifecycle status (see `RecoveryStatus`) |
| `affected_devices` | `List[str]` | Device IDs affected by this incident |
| `affected_runtime_ids` | `List[str]` | Runtime session IDs affected |
| `participant_states` | `List[RecoveryParticipantState]` | Per-participant postures |
| `stale_result_unit_ids` | `List[str]` | Stale result units |
| `authoritative_result_unit_ids` | `List[str]` | Authoritative result units |
| `pending_result_unit_ids` | `List[str]` | Pending result units |
| `replay_required` | `bool` | Whether any participant must replay work |
| `resume_allowed` | `bool` | Whether local resume is a valid path |
| `merge_confirmation_required` | `bool` | Whether merge confirmation is required |
| `barrier_state` | `RecoveryBarrierState?` | Optional blocking barrier |
| `recommended_actions` | `List[RecoveryActionRecommendation]` | Advisory actions |
| `reason` | `str` | Human-readable rationale |
| `metadata` | `Dict` | Arbitrary extensibility bag |

### `RuntimeReconciliationState`

Captures the full reconciliation posture across all participants, result units, and incidents.  This is the top-level advisory read-model that downstream recovery orchestration (in a future PR) will consume.

Contains the same fields as `RuntimeRecoveryIncident` at the aggregate level, plus:

| Field | Type | Description |
|-------|------|-------------|
| `reconciliation_id` | `str` | Stable unique identifier |
| `recovery_id` | `str?` | Link to a primary `RuntimeRecoveryIncident` |
| `incidents` | `List[RuntimeRecoveryIncident]` | Contributing incidents |

### `RecoverySummary`

A compact read-only summary suitable for embedding in the unified multi-device projection and in route payloads.

| Field | Type | Description |
|-------|------|-------------|
| `summary_id` | `str` | Stable unique identifier |
| `overall_status` | `str` | Aggregated status across all incidents |
| `incident_count` | `int` | Total detected incidents |
| `resolved_incident_count` | `int` | Resolved incidents |
| `pending_incident_count` | `int` | Pending incidents |
| `needs_intervention_count` | `int` | Incidents requiring manual intervention |
| `replay_required` | `bool` | True if any incident requires replay |
| `resume_allowed` | `bool` | True if resume is allowed for any participant |
| `merge_confirmation_required` | `bool` | True if any merge needs explicit confirmation |
| `has_barrier` | `bool` | True if any active barrier blocks recovery |
| `recommended_action_types` | `List[str]` | Deduplicated advisory action types |
| `most_recent_incident_type` | `str?` | Most recently created incident type |
| `most_recent_recovery_id` | `str?` | Most recently created incident ID |
| `reason` | `str` | Human-readable posture description |

### `RecoveryParticipantState`

Per-participant recovery posture.

| Field | Type | Description |
|-------|------|-------------|
| `device_id` | `str` | Participant device identifier |
| `runtime_id` | `str?` | Optional runtime session ID |
| `status` | `str` | Recovery status for this participant |
| `authoritative` | `bool?` | Whether this participant holds authoritative results |
| `replay_required` | `bool?` | Whether this participant must replay work |
| `resume_allowed` | `bool?` | Whether local resume is permissible |
| `last_known_assignment_ids` | `List[str]` | Last known subtask assignment IDs |
| `last_known_result_unit_ids` | `List[str]` | Last known result unit IDs |

### `RecoveryActionRecommendation`

An advisory action recommendation.

| Field | Type | Description |
|-------|------|-------------|
| `action_type` | `str` | Action type (see `RecoveryActionType`) |
| `target_device_id` | `str?` | Target device for this recommendation |
| `result_unit_id` | `str?` | Related result unit |
| `reason` | `str` | Human-readable rationale |

### `RecoveryBarrierState`

Recovery-perspective view of a blocking barrier.

| Field | Type | Description |
|-------|------|-------------|
| `barrier_id` | `str` | Stable barrier identifier |
| `blocking` | `bool` | Whether the barrier is currently blocking |
| `pending_device_ids` | `List[str]` | Devices that have not cleared this barrier |
| `clearable` | `bool` | Whether the barrier can be auto-cleared |
| `description` | `str` | Human-readable description |

---

## Enumerations

### `RecoveryIncidentType`

| Value | Meaning |
|-------|---------|
| `dispatch_failure` | Source dispatch failed or timed out |
| `handoff_interrupted` | Handoff was sent but not completed |
| `takeover_failed` | Target takeover encountered a fatal error |
| `merge_conflict` | Cross-runtime merge detected conflicting results |
| `coordinator_lost` | Mesh session coordinator became unreachable |
| `session_diverged` | Mesh session participants reported inconsistent states |
| `result_stale` | One or more result units are stale |
| `partial_completion` | Multi-device task partially completed |
| `unknown` | Incident type could not be determined |

### `RecoveryStatus`

| Value | Meaning |
|-------|---------|
| `pending` | Incident detected; no recovery started |
| `in_progress` | Recovery actions underway |
| `resolved` | Incident resolved |
| `needs_intervention` | Automated recovery cannot proceed; manual action required |
| `stale` | Incident record superseded by newer state |

### `RecoveryActionType`

| Value | Meaning |
|-------|---------|
| `retry_handoff` | Re-attempt handoff from source to target |
| `resume_local` | Allow local resume on source or target |
| `request_merge_confirmation` | Request explicit merge confirmation |
| `repair_mesh_session` | Repair or re-establish the mesh session |
| `mark_stale` | Mark identified result units or participant states as stale |
| `fallback_local` | Fall back to fully local execution |
| `replay_assignment` | Replay subtask assignments to affected participants |
| `wait_for_participant` | Pause reconciliation while awaiting participant response |
| `escalate` | Escalate for manual review |

---

## Builders

### `build_runtime_recovery_incident(...) → RuntimeRecoveryIncident`

Low-level keyword-argument factory. All parameters are optional; callers with partial context always produce a valid incident.

```python
from contracts.runtime_recovery_reconciliation import build_runtime_recovery_incident

incident = build_runtime_recovery_incident(
    incident_type="dispatch_failure",
    source_device_id="phone_001",
    affected_devices=["phone_001", "tablet_002"],
    replay_required=True,
    resume_allowed=True,
    reason="Dispatch timed out after 30s",
)
```

### `build_runtime_reconciliation_state(...) → RuntimeReconciliationState`

Builds a full reconciliation state from keyword arguments and optional incident list.

### `build_recovery_summary(incidents, reconciliation) → RecoverySummary`

Aggregates a list of incidents (and optional reconciliation state) into a compact summary.

---

## Adapters

### `from_source_dispatch_result(dispatch_result, ...) → RuntimeRecoveryIncident`

Derives a recovery incident from a `SourceDispatchResult` (PR-35).

```python
from contracts.runtime_recovery_reconciliation import from_source_dispatch_result

incident = from_source_dispatch_result(
    {"status": "failed", "source_device_id": "phone_001"},
    mesh_session_id="msess_001",
)
```

### `from_target_takeover_result(takeover_result, ...) → RuntimeRecoveryIncident`

Derives a recovery incident from a `LocalTakeoverResult` (PR-34).

### `from_mesh_session_coordinator(coordinator, ...) → RuntimeRecoveryIncident`

Derives a recovery incident from a `MeshSessionCoordinatorState` (PR-37).

### `from_merged_runtime_result(merged_result, ...) → RuntimeRecoveryIncident`

Derives a recovery incident from a `MergedRuntimeResult` (PR-36).

### `from_multi_device_projection(projection, ...) → RuntimeReconciliationState`

Derives a full `RuntimeReconciliationState` by inspecting all blocks of a `MultiDeviceRuntimeProjection` (PR-38).  This is the **canonical entry point** for holistic recovery posture:

```python
from contracts.runtime_recovery_reconciliation import from_multi_device_projection
from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection

projection = build_multi_device_runtime_projection(
    source_dispatches=[{"status": "failed", "source_device_id": "phone_001"}],
)
reconciliation = from_multi_device_projection(projection)
print(reconciliation.status)  # "pending" or "needs_intervention" etc.
```

---

## Projection Integration

### `MultiDeviceRuntimeProjection.runtime_recovery`

PR-38's `MultiDeviceRuntimeProjection` now includes a `runtime_recovery` optional field (type `Dict[str, Any]`).  It is populated from a `RecoverySummary.to_dict()` when passed to `build_multi_device_runtime_projection(runtime_recovery=...)`.

```python
from contracts.multi_device_runtime_projection import build_multi_device_runtime_projection
from contracts.runtime_recovery_reconciliation import build_recovery_summary

summary = build_recovery_summary([])
projection = build_multi_device_runtime_projection(
    runtime_recovery=summary,
)
assert projection.runtime_recovery is not None
```

### Route: `GET /api/v1/projection/runtime/recovery`

A new **read-only** endpoint that returns the current `RecoverySummary` derived from the live multi-device projection:

```
GET /api/v1/projection/runtime/recovery
```

Example response:

```json
{
  "summary_id": "rrsum_a1b2c3d4e5",
  "generated_at": 1700000000.0,
  "overall_status": "resolved",
  "incident_count": 0,
  "resolved_incident_count": 0,
  "pending_incident_count": 0,
  "needs_intervention_count": 0,
  "replay_required": false,
  "resume_allowed": false,
  "merge_confirmation_required": false,
  "has_barrier": false,
  "recommended_action_types": [],
  "most_recent_incident_type": null,
  "most_recent_recovery_id": null,
  "reason": "no incidents",
  "metadata": {}
}
```

---

## How Recovery Differs from Other Contracts

| Contract | Answers |
|----------|---------|
| **PR-34 Takeover** | Did the target adopt the handoff and execute locally? |
| **PR-35 Dispatch** | How did the source decide to dispatch and what was the result? |
| **PR-36 Result Merge** | How were cross-runtime results merged into a canonical set? |
| **PR-37 Coordinator** | What is the live coordination state of the mesh session? |
| **PR-38 Projection** | What is the current unified read-only view of all runtime state? |
| **PR-39 Recovery** | _If anything went wrong, what is the advisory posture for recovery?_ |

The recovery/reconciliation contract is **purely advisory and read-only**.  It does not write state, issue commands, trigger actions, or drive automated repair.  It provides the **canonical read-model** that a future automated recovery engine will consume.

---

## Authoritative vs. Stale vs. Pending Results

| Category | Meaning | Field |
|----------|---------|-------|
| **Authoritative** | Confirmed, canonical result units after merge | `authoritative_result_unit_ids` |
| **Stale** | Superseded, rejected, or out-of-date result units | `stale_result_unit_ids` |
| **Pending** | Result units awaiting confirmation or completion | `pending_result_unit_ids` |

Adapters (`from_source_dispatch_result`, `from_merged_runtime_result`, etc.) automatically classify result units into these categories based on their reported status.

---

## Advisory Recovery Actions Encoding

`RecoveryActionRecommendation` objects are **advisory only**.  They describe what recovery step is recommended, which device it targets, and why.  The action type is drawn from `RecoveryActionType`:

```python
action = RecoveryActionRecommendation(
    action_type="retry_handoff",
    target_device_id="tablet_002",
    reason="Dispatch failed; retry handoff to target tablet",
)
```

Downstream consumers (future recovery engine) interpret these recommendations but are not required to act on them.

---

## Explicit Non-Goals (This PR)

The following are **out of scope** for PR-39:

- No automated recovery engine
- No write/command repair endpoints
- No persistence or streaming redesign
- No UI/dashboard redesign
- No broad execution-core rewrite
- No automated replay or rollback orchestration
- No state mutation based on recovery recommendations

---

## Testing

Tests are in `tests/test_pr39_runtime_recovery_reconciliation.py`.

Coverage includes:
- Serialisation stability (to_dict / to_json / from_dict round-trips)
- Stable field names
- Builder behaviour with full and partial inputs
- Adapter behaviour (from dispatch, takeover, coordinator, merge, projection)
- Graceful handling of missing/None/garbage input
- `build_recovery_summary` aggregation logic
- `contracts` and `core.unified` package re-exports
- Route `GET /api/v1/projection/runtime/recovery`
- `MultiDeviceRuntimeProjection.runtime_recovery` field integration

---

## Module Reference

```
contracts/runtime_recovery_reconciliation.py
├── RecoveryIncidentType  (enum)
├── RecoveryStatus        (enum)
├── RecoveryActionType    (enum)
├── RecoveryParticipantState     (Pydantic BaseModel)
├── RecoveryActionRecommendation (Pydantic BaseModel)
├── RecoveryBarrierState         (Pydantic BaseModel)
├── RuntimeRecoveryIncident      (Pydantic BaseModel)
├── RuntimeReconciliationState   (Pydantic BaseModel)
├── RecoverySummary              (Pydantic BaseModel)
├── build_runtime_recovery_incident(...)
├── build_runtime_reconciliation_state(...)
├── build_recovery_summary(...)
├── from_source_dispatch_result(...)
├── from_target_takeover_result(...)
├── from_mesh_session_coordinator(...)
├── from_merged_runtime_result(...)
└── from_multi_device_projection(...)
```

# Distributed Task Merge & Recovery (PR-14)

> **Status:** Merged — V4 PR-14

---

## Overview

This document describes the `core/distributed_execution/` package introduced
in PR-14.  The package formalises how multi-device, DAG-based, and parallel
execution results are merged into coherent outcomes and how recovery decisions
are expressed in stable, machine-readable form.

This is an **additive layer** — it does not replace `TaskGraph`,
`DAGScheduler`, `ConstellationRuntime`, `DesktopPresenceRuntime`, or any
existing orchestration module.

---

## Package structure

```
core/distributed_execution/
├── __init__.py          # Public API re-exports
├── merge_status.py      # MergeStatus enum + severity helpers
├── result_merge.py      # Merge helpers for heterogeneous result inputs
├── recovery_policy.py   # RecoveryPosture enum + recommendation logic
└── merge_summary.py     # MergeSummary dataclass + projection adapter
```

---

## 1. Merge Status Definitions

`MergeStatus` classifies the overall outcome of merging results from multiple
tasks, devices, or DAG branches.

| Status | Meaning |
|---|---|
| `success` | All required branches completed successfully.  No failures, no timeouts. |
| `partial_success` | Some branches completed; some failed or were skipped, but the core intent was achieved. |
| `degraded_success` | The goal was nominally achieved via a fallback path or with reduced fidelity. |
| `failed` | One or more required branches failed and the overall task goal was not achieved. |
| `timed_out` | The merge window expired before sufficient branches completed. |

**Severity ordering (best → worst):**
`success` < `partial_success` < `degraded_success` < `failed` < `timed_out`

Use `worst_of(a, b)` to combine statuses when aggregating across sub-groups.

### Success helpers

```python
from core.distributed_execution import is_successful_outcome, is_terminal_failure

is_successful_outcome(MergeStatus.PARTIAL_SUCCESS)  # True
is_terminal_failure(MergeStatus.TIMED_OUT)           # True
```

---

## 2. Recovery Posture Definitions

`RecoveryPosture` classifies what recovery action should be recommended when
a distributed task experiences failures or degradation.

| Posture | Meaning |
|---|---|
| `no_recovery_needed` | No action required; task fully or acceptably succeeded. |
| `retry_same_device` | Re-attempt on the same device/executor (transient error). |
| `reroute_device` | Redirect to a different device or execution path. |
| `skip_optional_branch` | Skip the failed branch; it is not required for success. |
| `require_confirmation` | Pause and request human/orchestrator confirmation. |
| `abort_task` | Cancel the entire task; no safe automatic recovery path. |

### Recovery resolution logic (in precedence order)

1. `success` → `no_recovery_needed`
2. `degraded_success` → `no_recovery_needed`
3. `partial_success` + optional branch available → `skip_optional_branch`
4. `partial_success` + confirmation required → `require_confirmation`
5. `partial_success` + retry attempted + reroute available → `reroute_device`
6. `partial_success` → `retry_same_device`
7. `requires_confirmation` hint (for any terminal state) → `require_confirmation`
8. `timed_out` + reroute available → `reroute_device`
9. `timed_out` → `retry_same_device`
10. `failed` + no prior retry → `retry_same_device`
11. `failed` + retry done + reroute available → `reroute_device`
12. `failed` + optional branch available → `skip_optional_branch`
13. `failed` (all options exhausted) → `abort_task`

---

## 3. MergeSummary — the canonical read surface

`MergeSummary` is the stable, immutable, serialisable summary of a completed
merge.  All downstream projection / observability consumers should read from
this dataclass rather than constructing their own summaries.

### Fields

| Field | Type | Description |
|---|---|---|
| `merge_status` | `MergeStatus` | Overall merge outcome. |
| `total_count` | int | Total branches/devices/subtasks in the merge. |
| `successful_count` | int | Successfully completed branches. |
| `failed_count` | int | Failed branches (non-timeout). |
| `timed_out_count` | int | Timed-out branches. |
| `skipped_count` | int | Skipped / optional branches. |
| `merged_payloads` | list[dict] | Per-branch result payload summaries. |
| `errors` | list[str] | Human-readable error strings from failed branches. |
| `warnings` | list[str] | Warnings (e.g. skipped / degraded branches). |
| `recovery_recommendation` | `RecoveryRecommendation \| None` | Attached recovery recommendation. |
| `task_id` | str | Task identifier. |
| `trace_id` | str | Trace identifier. |
| `runtime_session_id` | str | Session identifier. |
| `merged_at` | float | Unix timestamp when the summary was created. |

### Derived properties

| Property | Description |
|---|---|
| `is_successful` | True for any success variant. |
| `is_terminal_failure` | True for `failed` and `timed_out`. |
| `success_rate` | Float fraction of successful branches (0.0–1.0). |

### Serialisation

```python
summary = merge_dict_results([...])
d = summary.to_dict()           # JSON-safe dict
summary2 = MergeSummary.from_dict(d)  # round-trip
```

---

## 4. Merge Helpers

### `merge_result_envelopes(envelopes, …)`

Merge a list of `ResultEnvelope` objects (PR-2 canonical executor results).

```python
from core.distributed_execution import merge_result_envelopes

summary = merge_result_envelopes(
    [envelope_a, envelope_b, envelope_c],
    task_id="t-123",
    trace_id="trace-abc",
)
```

### `merge_graph_result(graph_result, …)`

Wrap a `GraphExecutionResult` (PR-5 TaskGraph output) into a `MergeSummary`.

```python
from core.distributed_execution import merge_graph_result

graph = TaskGraph(trace_id="abc123")
# ... add nodes and execute ...
graph_result = await graph.execute()

summary = merge_graph_result(graph_result)
```

### `merge_dict_results(results, …)`

Merge a list of plain dict result payloads (e.g. from a parallel tracker
aggregate or ad-hoc subtask results).

```python
from core.distributed_execution import merge_dict_results

summary = merge_dict_results([
    {"success": True, "task_id": "t1", "device_id": "dev-a"},
    {"success": False, "error": "connection refused", "device_id": "dev-b"},
    {"success": True, "task_id": "t3", "device_id": "dev-c"},
])
```

### `merge_any(inputs, …)`

Auto-dispatch merge for a heterogeneous list of result inputs.  Accepts any
mix of `ResultEnvelope`, `GraphExecutionResult`, and plain `dict` objects.

```python
from core.distributed_execution import merge_any

summary = merge_any([envelope_a, graph_result_b, {"success": True}])
```

---

## 5. Recovery Recommendation

```python
from core.distributed_execution import recommend_recovery, MergeStatus

rec = recommend_recovery(
    MergeStatus.FAILED,
    failed_count=2,
    timed_out_count=0,
    retry_attempted=True,
    reroute_available=True,
    task_id="t-123",
    trace_id="trace-abc",
)

print(rec.posture)  # RecoveryPosture.REROUTE_DEVICE
print(rec.to_dict())
```

Attaching a recommendation to a summary:

```python
import dataclasses

summary_with_rec = dataclasses.replace(summary, recovery_recommendation=rec)
```

---

## 6. Projection Adapter

### Attaching to a RuntimeProjection dict

```python
from core.distributed_execution import attach_merge_summary_to_projection

projection_dict = runtime_projection.to_dict()
enriched = attach_merge_summary_to_projection(projection_dict, summary)
# enriched["merge_summary"] is now populated
```

### Quick hints

```python
from core.distributed_execution import get_merge_hints

hints = get_merge_hints(summary)
# {
#   "merge_status": "partial_success",
#   "is_successful": True,
#   "is_terminal_failure": False,
#   "has_errors": True,
#   "has_warnings": False,
#   "success_rate": 0.6667,
#   "has_recovery_recommendation": True,
#   "recovery_posture": "retry_same_device",
#   "total_count": 3,
#   "task_id": "t-123",
#   "trace_id": "trace-abc"
# }
```

---

## 7. Read-only API Endpoint

PR-14 adds one new read-only endpoint to the existing projection router:

```
GET /api/v1/execution/merge-summary
```

**Response:** Standard `RuntimeProjection` fields + `merge_summary` +
`merge_hints`.

This endpoint uses `EMPTY_MERGE_SUMMARY` as the default idle state when no
live merge context is available.  Future code that performs live merges
should store the `MergeSummary` in a registry and retrieve it here.

---

## 8. Relationship to other PR-14 foundations

| Module | Relationship |
|---|---|
| `core/execution_observability/` (PR-7) | Downstream consumer — can display merge status and recovery posture on the observability surface. |
| `core/envelope_consolidation/` (PR-8) | `ResultEnvelope` fields are accepted as merge inputs; trace propagation contract is respected. |
| `core/orchestration_authority/` (PR-9) | Authority role can be used as a hint for recovery posture (future integration). |
| `core/return_intelligence/` (PR-10) | Both layers are attached to the projection dict; they do not overlap. |
| `core/execution_policy/` (PR-11) | `requires_confirmation` flag from `ExecutionPolicy` can be forwarded to `recommend_recovery()`. |
| `core/cross_device_policy/` (PR-13) | `reroute_available` hint can be derived from cross-device routing policy availability. |
| `core/task_graph.py` (PR-5) | `GraphExecutionResult` is an accepted input to `merge_graph_result()`. **`TaskGraph` is not modified.** |

---

## 9. What this PR does NOT yet solve

- **Live merge registry:** there is no in-memory store for active merge
  summaries.  The `/api/v1/execution/merge-summary` endpoint returns the idle
  default until a registry is added.
- **Streaming / incremental merge:** results are merged as a batch.  Real-time
  partial updates are not yet supported.
- **Step semantics:** individual task steps have no semantic classification yet
  (planned for PR-15 Task Semantics & Step Classes).
- **Automatic recovery execution:** recovery recommendations are advisory only;
  they are not yet wired to any execution path that acts on them.
- **Persistence:** merge summaries are not persisted across process restarts.

---

## 10. How future code should publish merge/recovery summaries

1. After completing a multi-device or DAG execution, call one of the merge
   helpers:

   ```python
   from core.distributed_execution import merge_any, recommend_recovery
   import dataclasses

   summary = merge_any(result_inputs, task_id=task_id, trace_id=trace_id)
   rec = recommend_recovery(
       summary.merge_status,
       failed_count=summary.failed_count,
       timed_out_count=summary.timed_out_count,
       total_count=summary.total_count,
       reroute_available=reroute_available,
       task_id=task_id,
       trace_id=trace_id,
   )
   summary = dataclasses.replace(summary, recovery_recommendation=rec)
   ```

2. Store the `MergeSummary` in a future merge registry (to be added).

3. Emit it to the observability surface:

   ```python
   from core.distributed_execution import attach_merge_summary_to_projection, get_merge_hints

   projection_dict = runtime_projection.to_dict()
   enriched = attach_merge_summary_to_projection(projection_dict, summary)
   ```

4. Log the recovery posture for traceability:

   ```python
   logger.info(
       "Merge complete | status=%s recovery=%s task=%s trace=%s",
       summary.merge_status.value,
       rec.posture.value,
       task_id,
       trace_id,
   )
   ```

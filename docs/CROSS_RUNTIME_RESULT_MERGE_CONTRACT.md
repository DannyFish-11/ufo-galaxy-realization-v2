# Cross-Runtime Result Merge Contract (PR-36)

## Overview

The **Cross-Runtime Result Merge Contract** is the canonical answer to:

> "When work is executed across one or more runtimes, what canonical contract
> describes the resulting outputs, their provenance, and how they are merged
> into one coherent result?"

It is the result-side foundation for the chain of runtime contracts
established in PR-25 through PR-35, and serves as the base for future
coordinator and session work (PR-37 Mesh Session Coordinator, PR-38 Unified
Multi-Device Runtime Projection).

---

## Why This Contract Exists

Before PR-36, the Galaxy execution runtime had:

- Execution trace summaries (PR-25)
- Governance / policy alignment summaries (PR-27 / PR-28)
- Target-side local takeover results (PR-34)
- Source-side dispatch results (PR-35)

However, there was **no single stable contract** that answered:

- What counts as a **runtime result unit** (the atomic output from one
  participating runtime)?
- How are **local vs. remote vs. multi-device** outputs represented
  consistently?
- How is **provenance / source-runtime metadata** preserved?
- How are **partial, fallback, and merged results** explained?

PR-36 provides that missing merge layer.

---

## Module Location

```
contracts/cross_runtime_result_merge.py
```

The module is re-exported from:

- `contracts/__init__.py`
- `core/unified/__init__.py`
- `core/runtime/__init__.py`

---

## Core Contracts

### `RuntimeResultRole`

Enum describing the role of a result unit within the merge:

| Value | Meaning |
|-------|---------|
| `source` | Originates from the source runtime that initiated dispatch |
| `target` | Originates from a remote target runtime (handoff path) |
| `primary` | Designated as the primary / authoritative result |
| `support` | Supplements the primary result |
| `fallback` | Used when the preferred path failed |
| `partial` | A partial result when full execution was not possible |
| `unknown` | Role could not be determined |

### `RuntimeResultStatus`

Enum describing the execution outcome of a result unit:

| Value | Meaning |
|-------|---------|
| `succeeded` | Execution completed successfully |
| `failed` | Execution completed with a failure |
| `partial` | Partial / degraded result |
| `blocked` | Blocked before it started |
| `skipped` | Not executed (superseded by another unit) |
| `timeout` | Timed out before completion |
| `unknown` | Status could not be determined |

### `ResultMergePolicy`

Enum describing the strategy for merging multiple result units:

| Value | Meaning |
|-------|---------|
| `primary_wins` | The designated primary (or first succeeded) unit is authoritative |
| `first_success` | The first succeeded unit wins |
| `last_success` | The last succeeded unit wins |
| `all_required` | All units must succeed; any failure marks the merge as failed |
| `best_effort` | Collect all succeeded units; partial success is acceptable |
| `fallback_chain` | Try units in order; use the first that succeeds |
| `unknown` | Policy could not be determined |

### `RuntimeResultProvenance`

Per-unit provenance metadata:

```python
class RuntimeResultProvenance(BaseModel):
    device_id: Optional[str]
    runtime_id: Optional[str]
    session_id: Optional[str]
    trace_id: Optional[str]
    task_id: Optional[str]
    execution_path: Optional[str]        # "local" / "remote_handoff" / etc.
    governance_snapshot_ref: Optional[str]   # PR-27 ref
    policy_alignment_ref: Optional[str]      # PR-28 ref
    execution_trace_ref: Optional[str]       # PR-25 ref
    metadata: Dict[str, Any]
```

### `RuntimeResultUnit`

The canonical result from a single runtime participant:

```python
class RuntimeResultUnit(BaseModel):
    result_unit_id: str              # UUID4
    device_id: Optional[str]
    runtime_id: Optional[str]
    role: RuntimeResultRole
    status: RuntimeResultStatus
    output: Optional[Dict[str, Any]]
    error: Optional[str]
    reason: Optional[str]
    trace_id: Optional[str]
    task_id: Optional[str]
    session_id: Optional[str]
    mesh_session_id: Optional[str]   # PR-33
    execution_trace: Optional[Dict]  # PR-25
    governance_snapshot: Optional[Dict]  # PR-27
    policy_alignment: Optional[Dict]     # PR-28
    provenance: Optional[RuntimeResultProvenance]
    timestamp: float
    metadata: Dict[str, Any]
```

### `ResultMergeInput`

Container wrapping all inputs to a merge operation:

```python
class ResultMergeInput(BaseModel):
    merge_id: str                      # UUID4
    trace_id: Optional[str]
    task_id: Optional[str]
    session_id: Optional[str]
    mesh_session_id: Optional[str]     # PR-33
    result_units: List[RuntimeResultUnit]
    merge_policy: ResultMergePolicy
    primary_result_unit_id: Optional[str]
    execution_trace_refs: List[str]    # PR-25
    governance_snapshot_refs: List[str]  # PR-27
    policy_alignment_refs: List[str]     # PR-28
    merge_reason: Optional[str]
    metadata: Dict[str, Any]
```

### `MergedRuntimeResult`

The top-level merged result from cross-runtime execution:

```python
class MergedRuntimeResult(BaseModel):
    merge_id: str                      # UUID4
    trace_id: Optional[str]
    task_id: Optional[str]
    session_id: Optional[str]
    mesh_session_id: Optional[str]     # PR-33
    result_units: List[RuntimeResultUnit]
    primary_result_unit_id: Optional[str]
    merge_policy: ResultMergePolicy
    merged_output: Optional[Dict[str, Any]]
    success: bool
    partial: bool
    fallback_applied: bool
    conflicts: List[str]
    execution_trace_refs: List[str]
    governance_snapshot_refs: List[str]
    policy_alignment_refs: List[str]
    merge_reason: Optional[str]
    errors: List[str]
    timestamp: float
    metadata: Dict[str, Any]
```

### `ResultMergeSummary`

Lightweight read-only summary for projection / debug surfaces:

```python
class ResultMergeSummary(BaseModel):
    summary_id: str                    # UUID4
    merge_id: Optional[str]
    trace_id: Optional[str]
    task_id: Optional[str]
    session_id: Optional[str]
    merge_policy: ResultMergePolicy
    success: bool
    partial: bool
    fallback_applied: bool
    unit_count: int
    succeeded_unit_count: int
    failed_unit_count: int
    conflict_count: int
    error_count: int
    has_merged_output: bool
    merge_reason: Optional[str]
    timestamp: float
    metadata: Dict[str, Any]
```

---

## Builders and Adapters

### Adapters from existing result sources

```python
# From PR-34 LocalTakeoverResult (target-side handoff execution)
unit = from_local_takeover_result(
    takeover_result,          # LocalTakeoverResult instance or dict
    role=RuntimeResultRole.target,
    mesh_session_id="mesh_001",
)

# From PR-35 SourceDispatchResult (source-side dispatch execution)
unit = from_source_dispatch_result(
    dispatch_result,          # SourceDispatchResult instance or dict
    role=RuntimeResultRole.source,
)

# From raw execution output (OpenClawd._run_execution() output dict)
unit = from_execution_output(
    execution_output,
    trace_id="trace_abc",
    task_id="task_001",
    session_id="sess_xyz",
    role=RuntimeResultRole.primary,
)
```

### Merge entry point

```python
merged = merge_runtime_results(
    result_units=[unit_local, unit_remote],
    trace_id="trace_abc",
    task_id="task_001",
    session_id="sess_xyz",
    merge_policy=ResultMergePolicy.primary_wins,
    merge_reason="local_preferred_with_remote_fallback",
)
print(merged.success)          # True / False
print(merged.fallback_applied) # True if fallback was used
print(merged.merged_output)    # The authoritative output dict
```

### Direct builder

```python
result = build_merged_runtime_result(
    result_units=[unit],
    trace_id="trace_abc",
    merge_policy=ResultMergePolicy.first_success,
    success=True,
    merged_output={"action_taken": "click", ...},
)
```

### Summary builder

```python
# From a MergedRuntimeResult
summary = build_result_merge_summary(result=merged)

# Or directly
summary = build_result_merge_summary(
    merge_policy=ResultMergePolicy.primary_wins,
    success=True,
    unit_count=2,
    succeeded_unit_count=1,
)
```

---

## How It Differs from Related Contracts

| Contract | Scope |
|----------|-------|
| `ExecutionTraceEnvelope` (PR-25) | Traces the lifecycle events of a single local execution |
| `RuntimeGovernanceSnapshot` (PR-27) | Captures the governance posture at one point in time |
| `ExecutionPolicyAlignmentSurface` (PR-28) | Evaluates policy alignment for a dispatch decision |
| `LocalTakeoverResult` (PR-34) | Result from the **target** side after adopting a handoff |
| `SourceDispatchResult` (PR-35) | Result from the **source** side after completing a dispatch |
| **`MergedRuntimeResult` (PR-36)** | **Unified output combining results from all participating runtimes** |

PR-36 sits *above* PR-34 and PR-35: it consumes their outputs as inputs and
produces a single explainable, provenance-preserving merged result.

---

## Provenance, Partial Results, Fallback, and Conflicts

### Provenance

Each `RuntimeResultUnit` carries a `RuntimeResultProvenance` sub-contract
that records:

- The device and runtime that produced the unit
- The execution path taken (`"local"`, `"remote_handoff"`, `"staged_mesh"`)
- Reference IDs for the governance snapshot (PR-27), policy alignment (PR-28),
  and execution trace (PR-25) associated with this unit

The `MergedRuntimeResult` aggregates these into `execution_trace_refs`,
`governance_snapshot_refs`, and `policy_alignment_refs` lists for
cross-cutting correlation.

### Partial Results

`MergedRuntimeResult.partial = True` when:

- Some units failed but the merge policy still produced an output (e.g.
  `best_effort` with at least one succeeded unit), or
- The `all_required` policy succeeded but one or more units returned partial
  status.

### Fallback

`MergedRuntimeResult.fallback_applied = True` when:

- The preferred unit(s) failed and a `role=fallback` unit was used as the
  primary result, or
- The `fallback_chain` policy exhausted non-fallback units and reached a
  fallback unit.

### Conflicts

`MergedRuntimeResult.conflicts` is a list of human-readable strings when
multiple succeeded units produced **differing outputs**.  This is possible
when parallel remote execution is used and the results disagree.  The
conflict list is informational — the merge still selects a primary output
via the policy.

---

## HTTP Endpoint

PR-36 adds a read-only GET endpoint:

```
GET /api/v1/runtime/result-merge-summary
```

Returns a `ResultMergeSummary` for the current merge posture (currently
returns an empty/no-active-merge summary; a future PR can wire it to live
merge state).

Example response:

```json
{
  "summary_id": "...",
  "merge_id": "...",
  "trace_id": null,
  "merge_policy": "primary_wins",
  "success": false,
  "partial": false,
  "fallback_applied": false,
  "unit_count": 0,
  "succeeded_unit_count": 0,
  "failed_unit_count": 0,
  "conflict_count": 0,
  "error_count": 0,
  "has_merged_output": false,
  "merge_reason": "no_active_merge",
  "timestamp": 1700000000.0
}
```

---

## What This PR Does Not Do

- **No full Mesh Session Coordinator** — deferred to PR-37.
- **No advanced semantic conflict-resolution** — conflicts are detected and
  recorded but not automatically resolved.
- **No persistence or streaming redesign** — in-memory only.
- **No UI/dashboard redesign** — purely contract and narrow integration layer.
- **No broad execution-core rewrite** — additive only.
- **No live merge-state wiring** — the endpoint returns an empty summary;
  live wiring is deferred to the coordinator work in PR-37.

---

## Architectural Intent

PR-36 provides the result-side foundation for:

- **PR-37** Mesh Session Coordinator — can use `MergedRuntimeResult` as the
  coordinator's output contract.
- **PR-38** Unified Multi-Device Runtime Projection — can attach
  `ResultMergeSummary` to projection payloads.
- Future recovery / reconciliation work — `fallback_applied`, `partial`, and
  `conflicts` fields provide explicit signals for recovery logic.

In sequence:

- PR-34 introduced **target-side** takeover execution
- PR-35 introduced **source-side** dispatch orchestration
- **PR-36 unifies the result merge/output contract across those flows**

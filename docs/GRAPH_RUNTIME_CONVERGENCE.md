# Graph Runtime Convergence (PR-C)

## Overview

PR-C implements **Graph Runtime Convergence** for Galaxy.  It extends the
Task Graph Runtime (PR-6) so that **every execution — including retries,
fallbacks, and multi-target fanout/fanin — is expressed as an explicit graph
relation** rather than scattered log entries.

After PR-C, `core/task_graph_runtime.py` becomes the single canonical runtime
view for all task lifecycle, dependency, dispatch, result, retry, fallback,
and fanout/fanin relations in the system.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  TASK GRAPH RUNTIME  (core/task_graph_runtime.py)                    │
│                                                                      │
│  Full lifecycle:                                                     │
│    queued → admitted → planned → routed → dispatch → running         │
│          → result | partial_result → completed | failed              │
│          → cancelled | degraded | replayed                           │
│                                                                      │
│  Edge types:                                                         │
│    dependency_edge  — structural DAG dependency                      │
│    dispatch_edge    — transport/carrier selected                     │
│    result_edge      — result flow back to requester                  │
│    retry_edge       — retry attempt lineage           (PR-C NEW)     │
│    fallback_edge    — degraded path lineage           (PR-C NEW)     │
│    fanout_edge      — multi-target dispatch child     (PR-C NEW)     │
│    fanin_edge       — aggregated result from children (PR-C NEW)     │
└──────────────────────────────────────────────────────────────────────┘
                     ↑ projection adapters
┌───────────────────────────────────────────────────────────────────┐
│  Legacy orchestrators — GRAPH CONTRIBUTORS only                   │
│  • galaxy_gateway.orchestrator.GalaxyOrchestrator                 │
│  • fusion.unified_orchestrator.UnifiedOrchestrator                │
│  These are NOT removed; they register nodes/edges via the runtime.│
└───────────────────────────────────────────────────────────────────┘
```

---

## Authority

| Sentinel | Value | Meaning |
|---|---|---|
| `TASK_GRAPH_RUNTIME_AUTHORITY` | `TASK_GRAPH_RUNTIME_V1` | Core runtime authority |
| `GRAPH_RUNTIME_CONVERGENCE_AUTHORITY` | `GRAPH_RUNTIME_CONVERGENCE_V1` | PR-C convergence active |

---

## Lifecycle State Machine

### GraphNodeState (complete)

| State | Description |
|---|---|
| `queued` | Node created, not yet admitted |
| `admitted` | Accepted for execution by runtime authority |
| `planned` | Execution plan (targets, transport, constraints) resolved |
| `routed` | Routing decision made; transport selected |
| `dispatch` | TaskEnvelope emitted into CommandRouter |
| `running` | Executor confirmed task is actively running |
| `result` | Result received (intermediate for fanin / streaming) |
| `partial_result` | At least one result received, not yet complete |
| `completed` | Task completed successfully |
| `failed` | Task failed; error_code populated |
| `cancelled` | Task explicitly cancelled |
| `degraded` | Task completed via fallback path |
| `replayed` | Task being re-executed as replay |

### Transition rules

- `CANCELLED`, `DEGRADED`, `COMPLETED`, `FAILED` are **terminal** states —
  they set `completed_at` and create a `result_edge`.
- `PARTIAL_RESULT` sets `result_at` but is **not** terminal.
- `ADMITTED`, `PLANNED`, `ROUTED`, `REPLAYED` create no automatic edges.

---

## Retry / Fallback Lineage

### Retry

```python
from core.task_graph_runtime import get_task_graph_runtime

rt = get_task_graph_runtime()

# Register original and retry nodes
rt.register_envelope(original_envelope)
rt.register_envelope(retry_envelope)

# Record the retry relation (creates retry_edge + RetryRecord)
record = rt.register_retry(
    original_task_id="task_abc",
    retry_task_id="task_abc_retry1",
    attempt_number=1,
    reason="transient_network_error",
)

# Query retry chain
lineage = rt.get_retry_lineage("task_abc")
```

### Fallback

```python
# Record the fallback relation (creates fallback_edge + FallbackRecord)
record = rt.register_fallback(
    primary_task_id="task_abc",
    fallback_task_id="task_abc_fallback",
    reason="device_unavailable",
)

# Query fallback chain
lineage = rt.get_fallback_lineage("task_abc")
```

---

## Multi-target Fanout / Fanin

```python
# Fanout: one parent dispatches to N children
rt.register_fanout("task_parent", ["task_child_0", "task_child_1", "task_child_2"])

# Fanin: N children aggregate into one collector
rt.register_fanin(["task_child_0", "task_child_1", "task_child_2"], "task_aggregator")

# Query relations
children = rt.get_fanout_children("task_parent")
parents  = rt.get_fanin_parents("task_aggregator")
```

---

## CanonicalTask Integration

```python
# Register a CanonicalTask entity directly into the runtime
# (reads task_id, trace_id, session_id, intent.tool_name,
#  routing.selected_device_id, lifecycle from the CanonicalTask)
node = rt.register_canonical_task(canonical_task_instance)
```

CanonicalTask lifecycle values are automatically mapped to `GraphNodeState`:

| CanonicalTask lifecycle | GraphNodeState |
|---|---|
| `created` | `queued` |
| `admitted` | `admitted` |
| `planned` | `planned` |
| `routed` | `routed` |
| `dispatched` | `dispatch` |
| `running` | `running` |
| `completed` | `completed` |
| `failed` | `failed` |
| `cancelled` | `cancelled` |
| `degraded` | `degraded` |

---

## Observability

### Snapshot

The `snapshot()` method returns a `GraphRuntimeSnapshot` suitable for
consumption by `status_board_v2` and the operator console:

```python
snap = rt.snapshot()
snap.total_nodes          # all tracked nodes
snap.total_edges          # all tracked edges
snap.nodes_by_state       # {state_value: count}
snap.total_retry_records  # retry lineage count
snap.total_fallback_records  # fallback lineage count
snap.total_fanout_records    # fanout+fanin count
snap.convergence_authority   # "GRAPH_RUNTIME_CONVERGENCE_V1"
snap.to_dict()            # JSON-serialisable representation
```

### Ring Buffers (all 256-entry)

| Method | Contents |
|---|---|
| `get_observability_log()` | `GraphRuntimeRecord` — state transitions |
| `get_projection_log()` | `WorkflowProjectionRecord` — contributor projections |
| `get_retry_log()` | `RetryRecord` — retry relations |
| `get_fallback_log()` | `FallbackRecord` — fallback relations |
| `get_fanout_log()` | `FanoutRecord` — fanout/fanin relations |

---

## Workflow / Orchestrator Authority

Legacy orchestrators (`GalaxyOrchestrator`, `UnifiedOrchestrator`,
`E2EOchestrator`) are **not removed**.  They are demoted to **graph
contributors** and must use the runtime API:

| Role | Allowed | Forbidden |
|---|---|---|
| Graph contributor | `register_node()`, `register_envelope()`, `project_workflow()`, `register_retry()`, `register_fallback()`, `register_fanout()`, `register_fanin()` | Direct node state mutation outside the runtime API |
| Legacy facade | Acting as a local coordinator for their own internal steps | Claiming system-level execution authority |

### Projection example

```python
from core.task_graph_runtime import (
    get_task_graph_runtime,
    project_workflow_to_graph,
    WorkflowContributorKind,
)

rt = get_task_graph_runtime()
project_workflow_to_graph(
    {
        "trace_id": "trace_xyz",
        "session_id": "sess_1",
        "contributor": "galaxy_orchestrator",
        "node_statuses": {
            "step_0": "completed",
            "step_1": "running",
            "step_2": "queued",
        },
    },
    rt,
)
```

---

## Testing

PR-C adds three new test files covering the convergence additions:

| File | Tests | Coverage |
|---|---|---|
| `tests/test_retry_fallback_edges.py` | 36 | retry/fallback edge creation, records, lineage queries |
| `tests/test_multi_target_graph_edges.py` | 46 | fanout/fanin edge creation, records, round-trip |
| `tests/test_graph_lifecycle_state_machine.py` | 63 | extended states, transitions, CanonicalTask integration |

Run all graph runtime tests:

```bash
pytest tests/test_task_graph_runtime.py \
       tests/test_workflow_projection.py \
       tests/test_task_lifecycle_edges.py \
       tests/test_retry_fallback_edges.py \
       tests/test_multi_target_graph_edges.py \
       tests/test_graph_lifecycle_state_machine.py \
       -v
```

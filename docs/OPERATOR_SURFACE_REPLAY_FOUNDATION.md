# Operator Surface + Replay Foundation

**PR-E — Galaxy Architecture**

## Overview

PR-E establishes a unified **Operator Surface** and **Replay/Audit Foundation**
for the Galaxy runtime.  These two complementary layers ensure that:

1. All operator consoles, status boards, and topology viewers consume only
   **canonical runtime projections** — they do not infer system truth independently.
2. Every key execution decision (routing, fallback, retry, failure) is recorded
   in an **append-only, serialisable** replay foundation so the system can be
   observed, explained, and reviewed after the fact.

---

## Architecture Layers

```
Layer 10 — OperatorSurface / ReplayFoundation / AuditEventSemantics
            ↑ read-only projections
Layer 9  — CanonicalTask (core/canonical_task.py)
            ↑ task graph
Layer 8  — NetworkTopologyRuntime (core/network_topology_runtime.py)
            ↑ topology
Layer 7  — CapabilityAssimilationLayer (core/capability_assimilation.py)
            ↑ capability / presence
Layer 6  — TaskGraphRuntime (core/task_graph_runtime.py)
            ↑ lifecycle / edges
```

---

## Operator Surface (`core/operator_surface.py`)

### Authority

```python
from core.operator_surface import OPERATOR_SURFACE_AUTHORITY  # "OPERATOR_SURFACE_V1"
from core.operator_surface import OPERATOR_SURFACE_LAYER_POSITION  # 10
```

### Projection-Only Principle

The Operator Surface enforces the **projection-only principle**:

> All surfaces (operator console, status board, topology viewer) MUST
> consume canonical runtime projections from this module.  Surfaces MUST NOT
> infer system truth from legacy sources or raw subsystem internals.

Governed by `OPERATOR_SURFACE_PROJECTION_POLICY`.

### Role Boundaries

| Sentinel | Role |
|---|---|
| `OPERATOR_CONSOLE_ROLE` | Deep single-task inspection — uses `inspect_*` methods |
| `STATUS_BOARD_ROLE` | Compact runtime overview — uses `operator_snapshot()` |
| `TOPOLOGY_VIEWER_ROLE` | Graph structure display — consumes graph projections from snapshot |

### Inspection APIs

```python
from core.operator_surface import get_operator_surface

surface = get_operator_surface()

# Inspect a task by task_id
task_view = surface.inspect_task("task_abc123")
# → TaskInspection | None

# Inspect routing decisions for a task
route_view = surface.inspect_route("task_abc123")
# → RouteInspection | None

# Inspect an executor/provider node
exec_view = surface.inspect_executor("node_42")
# → ExecutorInspection | None

# Inspect failure domain for a task
failure_view = surface.inspect_failure_domain("task_abc123")
# → FailureDomainInspection | None

# Inspect task lineage / timeline
lineage_view = surface.inspect_lineage("task_abc123")
# → LineageInspection | None

# Inspect recovery disposition (PR-K)
recovery_view = surface.inspect_recovery("task_abc123")
# → RecoveryInspection | None

# Inspect hybrid partial-result outcome (PR-K)
partial_view = surface.inspect_partial_result("task_abc123")
# → PartialResultInspection | None

# Inspect durable audit evidence coverage (PR-K)
audit_view = surface.inspect_audit_evidence("task_abc123")
# → AuditEvidenceInspection  (always non-None)

# Unified end-to-end postmortem review (PR-K)
review = surface.end_to_end_review("task_abc123")
# → EndToEndReviewSummary  (always non-None)

# Compact operator snapshot (all dimensions)
snap = surface.operator_snapshot()
# → OperatorSnapshot
```

### End-to-End Review (PR-K)

`end_to_end_review(task_id)` returns an `EndToEndReviewSummary` containing:

| Field | Type | Description |
|---|---|---|
| `task` | `TaskInspection \| None` | Core lifecycle, intent, result |
| `route` | `RouteInspection \| None` | Routing decision details |
| `recovery` | `RecoveryInspection \| None` | Recovery disposition after interruption |
| `partial_result` | `PartialResultInspection \| None` | Hybrid partial-result outcome |
| `audit_evidence` | `AuditEvidenceInspection` | Durable evidence coverage |
| `lineage` | `LineageInspection \| None` | Task lineage / timeline |
| `reviewable` | `bool` | True when sufficient data exists for postmortem |
| `review_notes` | `List[str]` | Evidence gaps and notable findings |

This single API replaces the need to manually assemble data from multiple
surfaces for postmortem and operational diagnosis.

### Recovery Inspection (PR-K)

`inspect_recovery(task_id)` returns a `RecoveryInspection` showing:

- `recovery_disposition` — `"resumable"`, `"replay_only"`, `"reissuable"`, or `"terminal_on_interrupt"`
- `current_owner` — current lifecycle ownership stage from the live registry
- `recovery_action_taken` — whether a concrete registry action was taken (False for terminal records)
- `recovery_note` — human-readable summary of what happened during recovery

### Partial-Result Inspection (PR-K)

`inspect_partial_result(task_id)` returns a `PartialResultInspection` showing:

- `partial_result_disposition` — `"preserved"`, `"invalidated"`, `"merged"`, or `"resumed"`
- `partial_result_origin` — `"local"` or `"remote"`
- `resume_count` — number of times the hybrid execution was resumed
- `has_partial_result` — whether a partial result snapshot exists

### Audit Evidence Inspection (PR-K)

`inspect_audit_evidence(task_id)` returns an `AuditEvidenceInspection` showing:

- `has_evidence` — True when at least one durable audit record references this task
- `evidence_count` — total number of matching durable audit records
- `by_kind` — dict mapping audit record kind to count
- `audit_kinds_present` — sorted list of audit kinds present
- `earliest_record_at` / `latest_record_at` — timestamp range of matching records

### Projection Data Types

All inspection types carry a `_source` field indicating which canonical
runtime layer provided the data:

| Type | `_source` |
|---|---|
| `TaskInspection` | `"canonical_task_runtime"` |
| `RouteInspection` | `"admissibility_policy_convergence"` |
| `ExecutorInspection` | `"capability_assimilation"` |
| `FailureDomainInspection` | `"task_graph_runtime"` |
| `LineageInspection` | `"task_graph_runtime"` |
| `RecoveryInspection` | `"task_lifecycle_registry"` |
| `PartialResultInspection` | `"hybrid_orchestration_continuity_registry"` |
| `AuditEvidenceInspection` | `"durable_audit_store"` |
| `DevicePresenceSummary` | `"network_topology_runtime"` |

---

## Replay Foundation (`core/replay_foundation.py`)

### Authority

```python
from core.replay_foundation import REPLAY_FOUNDATION_AUTHORITY  # "REPLAY_FOUNDATION_V1"
from core.replay_foundation import REPLAY_ONLY_PRINCIPLE
```

### Record Types

| Type | Purpose |
|---|---|
| `TaskExecutionRecord` | Per-task execution snapshot (terminal state) |
| `RuntimeEventRecord` | Ordered audit event with causal `parent_event_ids` |
| `RouteDecisionRecord` | Routing decision snapshot (inputs + outputs) |
| `ReplayFallbackRecord` | Fallback trigger record |
| `ReplayRetryRecord` | Retry trigger record |

### Usage

```python
from core.replay_foundation import (
    get_replay_foundation,
    record_task_execution,
    record_route_decision,
    record_fallback,
    record_retry,
    emit_runtime_event,
    ReplayEventKind,
)

# Record a task execution (typically called after terminal lifecycle state)
rec = record_task_execution(canonical_task)

# Record a routing decision
record_route_decision(
    task_id="t1",
    trace_id="tr1",
    selected_targets=["device_A"],
    effective_path="direct",
    transport_strategy="websocket",
    capability_fit=True,
)

# Record a fallback trigger
record_fallback("t1", "t2", reason="transport_error")

# Record a retry trigger
record_retry("t1", "t1_retry1", reason="transient", attempt_number=1)

# Emit a runtime event for the replay timeline
emit_runtime_event(
    ReplayEventKind.ROUTE_DECISION,
    task_id="t1",
    source="command_router",
    message="route resolved via relay",
)

# Query lineage
foundation = get_replay_foundation()
lineage = foundation.get_task_lineage("t1")
timeline = foundation.replay_task_timeline("t1")  # ordered events for time-travel
```

### Design Invariants

1. **Append-only** — records are never mutated after creation.
2. **Serialisable** — all types provide `to_dict()` and `from_dict()`.
3. **256-entry ring buffer** — recent records are always queryable.
4. **Time-travel ready** — `replay_task_timeline(task_id)` returns an ordered
   event list for step-by-step replay.

---

## Audit Event Semantics (`core/audit_event_semantics.py`)

### Authority

```python
from core.audit_event_semantics import AUDIT_EVENT_SEMANTICS_AUTHORITY
from core.audit_event_semantics import AUDIT_UNIFIED_VOCABULARY_POLICY
```

### Unified Vocabulary

`AuditEventKind` is the canonical audit event vocabulary.  It aligns with and
subsumes:
- `core.replay_foundation.ReplayEventKind`
- `core.control_plane.audit_ledger.EventType`

All audit consumers must use `AuditEventKind` — parallel audit formats in
separate subsystems are prohibited.

### Helper Functions

```python
from core.audit_event_semantics import (
    audit_task_accepted,
    audit_task_admitted,
    audit_task_dispatched,
    audit_task_completed,
    audit_task_failed,
    audit_route_decision,
    audit_policy_decision,
    audit_fallback_triggered,
    audit_retry_triggered,
    audit_failure_domain,
    get_audit_event_semantics,
)

# Emit lifecycle events
r1 = audit_task_accepted("t1", origin="api", goal="do x")
r2 = audit_task_admitted("t1", parent_audit_ids=[r1.audit_id])
r3 = audit_task_dispatched("t1", targets=["dev_A"], transport="websocket")
r4 = audit_task_completed("t1", success=True)

# Emit route/policy events
audit_route_decision("t1", effective_path="direct", route_explanation="direct available")
audit_policy_decision("t1", verdict="admit", policy_score=0.95)

# Emit fallback/retry events
audit_fallback_triggered("t1", fallback_task_id="t2", reason="transport_error")
audit_retry_triggered("t1", retry_task_id="t1_r1", attempt_number=1)

# Emit failure domain
audit_failure_domain("t1", failure_domain="routing", error_code="NO_ROUTE")

# Query
semantics = get_audit_event_semantics()
records = semantics.get_by_task("t1")
by_kind = semantics.get_by_kind("task_failed")
by_trace = semantics.get_by_trace("trace_xyz")
```

### Explainability

Every `AuditEventRecord` provides a `.description()` method that returns the
canonical human-readable description for the event kind from
`AUDIT_EVENT_DESCRIPTIONS`.

---

## Projection Discipline

The three-layer projection discipline is formally enforced by PR-E:

```
Truth/Runtime Layer      CanonicalTask, TaskGraphRuntime, NetworkTopologyRuntime,
                         CapabilityAssimilationLayer
        │
        │  (read-only projection)
        ▼
Projection Layer         OperatorSurface (operator_surface.py)
                         ReplayFoundation (replay_foundation.py)
                         AuditEventSemantics (audit_event_semantics.py)
        │
        │  (read-only consumption)
        ▼
UI Surface Layer         operator console, status board, topology viewer,
                         audit dashboard, replay viewer
```

**Rule**: No UI surface may bypass the projection layer to query raw
subsystem internals or legacy caches directly.

---

## Files Added by PR-E / PR-K

| File | Purpose |
|---|---|
| `core/operator_surface.py` | Unified canonical operator surface |
| `core/replay_foundation.py` | Replay/audit foundation |
| `core/audit_event_semantics.py` | Unified audit event vocabulary |
| `tests/test_operator_surface_contracts.py` | Operator surface contract tests |
| `tests/test_operator_surface_review.py` | PR-K: recovery/audit/review inspection tests |
| `tests/test_projection_reads_runtime_only.py` | Projection discipline tests |
| `tests/test_replay_foundation.py` | Replay foundation tests |
| `tests/test_audit_event_semantics.py` | Audit event semantics tests |
| `tests/test_operator_task_route_failure_inspection.py` | End-to-end inspection tests |
| `docs/OPERATOR_SURFACE_REPLAY_FOUNDATION.md` | This document |

---

## Acceptance Criteria

- ✅ Operator surface based on canonical runtime, not ad-hoc data assembly.
- ✅ Task / route / provider / failure / fallback can be inspected and explained.
- ✅ Recovery disposition, routing causality, partial-result outcomes, and audit evidence are reviewable from a single surface (`end_to_end_review`).
- ✅ Replay/audit foundation supports reviewing execution chain and key decisions.
- ✅ UI/surface follows projection-only principle (`_source` fields declared).
- ✅ Unified audit vocabulary prevents parallel audit formats.
- ✅ All records are serialisable (JSON) for future persistence and time-travel.
- ✅ Operator inspection no longer depends on manual reconstruction from scattered log/JSONL sources.

# Execution Observability Unification (PR-7)

> **V3 PR-7 — Additive unification of existing execution observability signals.**
> This document covers *what* was unified, *what was intentionally not replaced*,
> and *how the new schemas should be used going forward*.

---

## 1. Background and motivation

After PR-1 through PR-6 established the topology bridge, runtime projection,
Status Board v2, liminal projection, and manifest stage surfaces, the system
had several stable projection layers that needed a consistent feed of
execution-level signals.

Those signals already existed in the code base — `trace_id`, `fallback_reason`,
`executor_level` — but each source used its own ad-hoc shape:

| Source | Trace field | Fallback field | Level field |
|---|---|---|---|
| `core/e2e_orchestrator.py` | `ctx["trace_id"]` | — | `ctx["mode"]` |
| `galaxy_gateway/orchestrator/task_orchestrator.py` | `envelope.trace_id` | `attempt.fallback_reason` | `attempt.executor_level` |
| `core/task_graph.py` | `graph.trace_id` | — | — |
| `core/windows_execution_arbiter.py` | — | `attempt.fallback_reason` | `attempt.executor_level` |

PR-7 introduces a **small, additive package** (`core/execution_observability/`)
that provides stable, serialisable types for those signals and adapter helpers
to convert each source into the unified shape — without removing or duplicating
any of the existing code.

---

## 2. New package: `core/execution_observability/`

```
core/execution_observability/
├── __init__.py          # re-exports the main public symbols
├── executor_level.py    # ExecutorLevel enum
├── fallback_schema.py   # FallbackReason enum + FallbackContext dataclass
├── trace_schema.py      # TraceCorrelation dataclass
├── event_schema.py      # ExecutionEvent (top-level unified event)
└── normalizers.py       # Adapter functions for each existing path
```

### 2.1 `ExecutorLevel`

A `str` enum with values that map 1-to-1 to the existing
`WinExecLevel` enum in `core/windows_execution_arbiter.py`:

| Value | Meaning |
|---|---|
| `system_api` | Win32 / OS-level calls |
| `uia` | UIAutomation COM accessibility |
| `gui` | Coordinate-based GUI automation |
| `vlm` | Vision-Language Model fallback |
| `remote_executor` | Cross-device / NATS dispatch |
| `orchestrator` | Decision at task-graph / arbiter level |
| `unknown` | Could not be determined |

### 2.2 `FallbackReason`

A `str` enum covering the cases already implied by the repo:

| Value | When it applies |
|---|---|
| `no_system_api_match` | System API level had no handler |
| `uia_unavailable` | UIAutomation COM layer not accessible |
| `visual_anchor_required` | Action needs visual coordinate |
| `cross_device_required` | Task must be routed to remote device |
| `local_capability_missing` | Required sensor / peripheral absent |
| `model_confidence_low` | VLM / planner confidence below threshold |
| `safety_hold` | Safety / HITL policy vetoed execution |
| `timeout` | Executor timed out |
| `partial_failure` | Some DAG subtasks failed |
| `unknown` | Could not be determined |

### 2.3 `TraceCorrelation`

Canonical trace fields:

```python
@dataclass
class TraceCorrelation:
    trace_id: str              # always non-empty; auto-generated if missing
    runtime_session_id: str    # session context
    task_id: Optional[str]     # TaskGraph.graph_id / TaskEnvelope.task_id
    action_id: Optional[str]   # fine-grained action within a task
```

### 2.4 `ExecutionEvent`

Top-level unified event:

```python
@dataclass
class ExecutionEvent:
    event_id: str
    timestamp: float
    trace: TraceCorrelation
    executor_level: ExecutorLevel
    fallback: Optional[FallbackContext]
    tri_state_phase: Optional[str]   # "silent" / "liminal" / "manifest"
    runtime_domain: Optional[str]    # "local" / "cross_device" / "transition"
    message: str
    metadata: Dict[str, Any]
```

---

## 3. Normalizers

`core/execution_observability/normalizers.py` provides four adapter functions,
one per existing source path:

```python
# From core/e2e_orchestrator.py context dict
normalize_e2e_context(ctx: dict) -> ExecutionEvent

# From TaskEnvelope / CommandEnvelope objects
normalize_task_envelope(envelope) -> ExecutionEvent

# From TaskGraph.run() result dict
normalize_task_graph_result(result: dict, *, graph=None) -> ExecutionEvent

# From WinExecAttempt dataclass / dict (arbiter log)
normalize_arbiter_attempt(attempt) -> ExecutionEvent

# Generic: existing GatewayTraceStore entries
normalize_observability_payload(payload: dict) -> ExecutionEvent
```

All normalizers are **tolerant**: missing or `None` fields are handled
gracefully; `trace_id` is auto-generated when absent.

---

## 4. What this PR does NOT replace

| Existing component | Status |
|---|---|
| `core/routes/observability.py` (all existing endpoints) | **Unchanged** — all existing routes remain functional |
| `WinExecLevel` / `WinExecStatus` in `core/windows_execution_arbiter.py` | **Unchanged** — `ExecutorLevel` maps to these; does not replace them |
| `GatewayTraceStore` in `core/command_router.py` | **Unchanged** — the new routes read from it additively |
| `TraceContext` in `galaxy_gateway/observability.py` | **Unchanged** — separate gateway-level trace context |
| Any top-level orchestrator | **No new orchestrator introduced** |
| Dashboard UI or dashboard backend | **Untouched** — no functionality moved into dashboard |

---

## 5. New read-only API endpoints (PR-7)

Three new endpoints were added to `core/routes/observability.py`.
All are read-only and additive.

### `GET /api/v1/observability/execution/schema`

Returns the stable enum values and field names of the unified schema.
Useful for consumers that need to validate or display executor levels /
fallback reasons without importing Python.

```json
{
  "schema_version": "pr7-v1",
  "executor_levels": ["system_api", "uia", "gui", "vlm", "remote_executor", "orchestrator", "unknown"],
  "fallback_reasons": ["no_system_api_match", "uia_unavailable", ...],
  "trace_fields": ["trace_id", "runtime_session_id", "task_id", "action_id"],
  "event_fields": ["event_id", "timestamp", "trace", "executor_level", "fallback", ...]
}
```

### `GET /api/v1/observability/execution/recent-events?limit=20`

Returns recent `GatewayTraceStore` entries normalised into the PR-7
`ExecutionEvent` shape.

### `GET /api/v1/observability/execution/trace/{trace_id}`

Looks up a trace by `command_id` or `task_id` and returns the unified
`TraceCorrelation` + `ExecutionEvent` shape.

---

## 6. How projection / surface layers should consume these signals

The new schemas are designed to be read by:

- **RuntimeProjection** — embed `TraceCorrelation` fields in projection outputs
  so every projection snapshot carries its originating trace context.
- **Status Board v2** — use `ExecutorLevel` and `FallbackReason` from
  `ExecutionEvent` to display "last executor used" and "last fallback reason"
  on the board surface.
- **Manifest stage** — call `event.projection_summary()` to get a compact
  dict with only non-empty fields; safe to embed directly in manifest payloads.

Example (projection layer):

```python
from core.execution_observability.normalizers import normalize_e2e_context
from core.execution_observability import ExecutionEvent

ev: ExecutionEvent = normalize_e2e_context(e2e_ctx)
manifest_payload["execution_summary"] = ev.projection_summary()
```

Example (arbiter → event):

```python
from core.execution_observability.normalizers import normalize_arbiter_attempt

for attempt in arbiter.attempt_log:
    ev = normalize_arbiter_attempt(attempt, tri_state_phase="manifest")
    logger.info("exec_event", extra=ev.to_dict())
```

---

## 7. Relationship to existing `core/routes/observability.py`

```
existing routes                     PR-7 additions
─────────────────────────────       ────────────────────────────────────────
/api/v1/observability/model-route   (unchanged)
/api/v1/observability/gateway       (unchanged)
/api/v1/observability/recent-calls  (unchanged)
/api/v1/observability/trace/{id}    (unchanged)
/api/v1/observability/stats         (unchanged)
/health/nats                        (unchanged)
/api/v1/observability/nats          (unchanged)
/api/v1/observability/bus-events    (unchanged)
                                    /api/v1/observability/execution/schema        ← new (PR-7)
                                    /api/v1/observability/execution/recent-events ← new (PR-7)
                                    /api/v1/observability/execution/trace/{id}    ← new (PR-7)
```

The new endpoints **read from the same `GatewayTraceStore`** as the existing
`/recent-calls` and `/trace/{id}` endpoints, but normalise the output into the
unified PR-7 schema.  There is no separate store or parallel observability bus.

---

## 8. Tests

See `tests/test_pr7_execution_observability.py` for:

- `TestExecutorLevel` — enum serialisation and `from_string` round-trips
- `TestFallbackReason` — enum serialisation and `from_string` round-trips
- `TestFallbackContext` — dataclass to/from dict, `from_arbiter_attempt`
- `TestTraceCorrelation` — `new()`, `from_dict()`, factory helpers, `child()`
- `TestExecutionEvent` — `build()`, `from_dict()`, `to_dict()`, `projection_summary()`
- `TestNormalizers` — all five normalizer functions with partial/missing fields
- `TestObservabilityRoutes` — the three new `/execution/…` endpoints

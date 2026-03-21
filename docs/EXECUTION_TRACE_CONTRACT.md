# Execution Trace Contract

> **PR-25** — Canonical execution lifecycle trace schema for Galaxy.

## What Is the Execution Trace Contract?

The **Execution Trace Contract** is a unified, serialisable schema that standardises how execution-related lifecycle events are represented and passed across the Galaxy system.

It answers four core questions for every execution event:

1. **What lifecycle stage is this?** (`intent_created`, `readiness_evaluated`, `fallback_selected`, `execution_started`, `execution_finished`, `execution_blocked`)
2. **Which request / session / intent / fallback decision does it belong to?** (via `trace_id`, `runtime_session_id`, `intent_id`)
3. **What is the outcome status?** (`pending`, `success`, `failed`, `blocked`, `degraded`, `skipped`)
4. **Where can downstream modules find stable fields?** (the canonical schema defined in this document)

---

## How It Differs from Fallback Trace and Readiness Evaluation

| Contract | PR | Purpose |
|---|---|---|
| `ExecutionIntentProfile` | PR-22 | Captures *what the system intends to execute* before any gate. |
| `ReadinessResult` | PR-23 | Answers *can we execute right now?* — the pre-execution gate. |
| `FallbackDecisionTrace` | PR-24 | Records *why fallback was chosen and which path was selected*. |
| **`ExecutionTraceEvent` / `ExecutionTraceEnvelope`** | **PR-25** | **Unifies all stages into a single, canonical trace schema consumed by runtime, governance, projection, and status surfaces.** |

Key differences:
- **Fallback Trace (PR-24)** focuses on *fallback routing logic*: which paths were considered, which was selected, and why the primary path was unavailable. It is a sub-component of the execution lifecycle.
- **Readiness Result (PR-23)** focuses on the *gate decision*: ready / blocked / confirm-required. It is a point-in-time evaluation result.
- **Execution Trace Contract (PR-25)** is the *envelope* layer: it spans the entire lifecycle from intent creation through execution completion, providing a single schema that downstream code can rely on without hand-rolling trace dicts.

---

## Module Location

```
contracts/execution_trace.py
```

Exported via `contracts/__init__.py` and re-exported from `core/execution/__init__.py`.

---

## Canonical Event Stages

Defined by `ExecutionTraceStage`:

| Stage | Value | When Emitted |
|---|---|---|
| Intent Created | `intent_created` | An `ExecutionIntentProfile` (PR-22) was built. |
| Readiness Evaluated | `readiness_evaluated` | The `ExecutionReadinessGate` (PR-23) produced a `ReadinessResult`. |
| Fallback Selected | `fallback_selected` | A `FallbackDecisionTrace` (PR-24) was produced. |
| Execution Started | `execution_started` | The executor was invoked (reserved for future integration). |
| Execution Finished | `execution_finished` | Execution completed with a result (success or failure). |
| Execution Blocked | `execution_blocked` | Execution was blocked at any point (gate, missing executor, internal error). |

---

## Canonical Event Statuses

Defined by `ExecutionTraceStatus`:

| Status | Value | Meaning |
|---|---|---|
| Pending | `pending` | Stage is in progress; no final determination. |
| Success | `success` | Stage completed successfully. |
| Failed | `failed` | Stage or execution failed. |
| Blocked | `blocked` | Execution was blocked (by policy, gate, or runtime). |
| Degraded | `degraded` | Stage completed at reduced capability; fallback path was used. |
| Skipped | `skipped` | Stage was skipped (e.g. observe-only intent, gate not consulted). |

---

## Required vs Optional Fields

### `ExecutionTraceEvent`

| Field | Type | Required | Description |
|---|---|---|---|
| `trace_id` | `str` | Auto-generated | Shared identifier for all events in one lifecycle run. |
| `event_id` | `str` | Auto-generated | Unique identifier for this specific event. |
| `stage` | `str` | Yes (default: `intent_created`) | Lifecycle stage. |
| `status` | `str` | Yes (default: `pending`) | Outcome status. |
| `action_level` | `str` | Yes (default: `observe`) | Decision Gate action level. |
| `source` | `str` | Yes (default: `openclawd`) | Originating component. |
| `timestamp` | `float` | Auto-generated | Unix timestamp. |
| `runtime_session_id` | `Optional[str]` | Optional | Active runtime session ID. |
| `intent_id` | `Optional[str]` | Optional | Originating intent profile ID. |
| `runtime_domain` | `Optional[str]` | Optional | Runtime domain (local / cross_device / transition). |
| `target_ref` | `Optional[str]` | Optional | Compact execution target reference. |
| `reason` | `Optional[str]` | Optional | Human-readable explanation (especially for blocked/failed events). |
| `details` | `Dict[str, Any]` | Optional (default: `{}`) | Narrow, additive structured metadata. |

### `ExecutionTraceEnvelope`

| Field | Type | Required | Description |
|---|---|---|---|
| `trace_id` | `str` | Auto-generated | Shared trace identifier. |
| `events` | `List[ExecutionTraceEvent]` | Auto-populated | Ordered lifecycle events. |
| `final_status` | `str` | Derived | Aggregate status (updated by `append()`). |
| `created_at` | `float` | Auto-generated | Unix timestamp. |
| `runtime_session_id` | `Optional[str]` | Optional | Active runtime session ID. |
| `intent_id` | `Optional[str]` | Optional | Originating intent profile ID. |

---

## Builder / Adapter Functions

All builders are **tolerant of partially available metadata** and **never raise**:

### `from_execution_intent(intent_profile, *, trace_id=None, source="openclawd")`
Builds an `intent_created` event from an `ExecutionIntentProfile` (PR-22).

### `from_readiness_result(readiness_result, *, intent_profile=None, trace_id=None, source="readiness_gate")`
Builds a `readiness_evaluated` event from a `ReadinessResult` (PR-23).

### `from_fallback_trace(fallback_trace, *, intent_profile=None, trace_id=None, source="fallback_router")`
Builds a `fallback_selected` event from a `FallbackDecisionTrace` (PR-24).

### `from_execution_result(execution_result, *, intent_profile=None, trace_id=None, source="executor")`
Builds an `execution_finished` or `execution_blocked` event from an execution result dict.

### `build_trace_envelope(*, intent_profile=None, readiness_result=None, fallback_trace=None, execution_result=None, runtime_session_id=None, trace_id=None)`
Builds a complete `ExecutionTraceEnvelope` covering all available lifecycle stages. All events share the same `trace_id`.

---

## Example Event Sequences

### Successful Execution Run

```
[intent_created    | status=success   | stage: intent profile built]
[readiness_evaluated | status=success | stage: gate passed, ready=True]
[fallback_selected | status=skipped   | stage: no fallback needed]
[execution_finished | status=success  | stage: action=click, success=True]
```

Final envelope `final_status`: `success`

### Blocked by Policy

```
[intent_created      | status=success  | stage: intent profile built]
[readiness_evaluated | status=blocked  | stage: gate blocked, blocked_by=policy]
[fallback_selected   | status=blocked  | stage: no fallback available]
[execution_blocked   | status=blocked  | stage: skipped_reason=readiness_gate:blocked:policy]
```

Final envelope `final_status`: `blocked`

### Degraded / Fallback Path

```
[intent_created      | status=success   | stage: intent profile built]
[readiness_evaluated | status=success   | stage: gate passed]
[fallback_selected   | status=degraded  | stage: primary executor unavailable, using local_fallback]
[execution_finished  | status=success   | stage: action=noop on degraded path]
```

Final envelope `final_status`: `success` (last substantive event)

### Observe-Only (No Execution)

```
[intent_created      | status=success  | stage: intent profile built]
[readiness_evaluated | status=skipped  | stage: observe_only action level]
[execution_blocked   | status=blocked  | stage: readiness_gate:observe_only:action_level]
```

Final envelope `final_status`: `blocked`

---

## Integration in `core/openclawd.py`

`OpenClawd._build_execution_trace()` is a minimal, additive helper that:

1. Calls `build_trace_envelope()` with the three available objects (intent profile, readiness result, execution result — including the embedded `fallback_trace`).
2. Returns `envelope.compact_summary()` as a narrow, projection-safe dict.
3. Attaches the result as `execution_trace` in the `_run_execution()` return dict.
4. Is fully isolated: exceptions are swallowed and `None` is returned, so the response flow is never interrupted.

The `execution_trace` key is additive: existing consumers of `_run_execution()` output do not need to be updated.

---

## What This PR Explicitly Does NOT Do Yet

- **No projection assembly governance overhaul** — `RuntimeProjection` is not restructured; trace events are not yet fed back into projection assembly rules.
- **No runtime governance snapshot** — there is no `RuntimeGovernanceSnapshot` object yet (planned for PR-27).
- **No execution policy alignment surface** — the final policy alignment layer across runtime / projection / governance is not built here (planned for PR-28).
- **No persistence or streaming** — trace events are in-memory only; no write path to a database, message bus, or audit ledger is implemented here.
- **No UI or dashboard** — no status board widget or dashboard panel for execution traces is added in this PR.
- **No `execution_started` events** — the `execution_started` stage is reserved for a future integration point where the executor is invoked asynchronously.

---

## Consuming the Trace Contract

### From `_run_execution()` output

```python
result = openclawd._run_execution(state_continuum)

trace = result.get("execution_trace")  # compact summary dict or None
if trace:
    print(trace["final_status"])   # e.g. "success"
    print(trace["stage_count"])    # e.g. 3
    print(trace["stages"])         # e.g. ["intent_created", "readiness_evaluated", "execution_finished"]
```

### Building a full envelope

```python
from contracts.execution_trace import build_trace_envelope

envelope = build_trace_envelope(
    intent_profile=profile,
    readiness_result=readiness,
    fallback_trace=fallback,
    execution_result=exec_result,
)
payload = envelope.to_dict()  # JSON-serialisable
summary = envelope.compact_summary()  # narrow projection-safe dict
```

### Using individual builders

```python
from contracts.execution_trace import (
    from_execution_intent,
    from_readiness_result,
    from_fallback_trace,
    from_execution_result,
)

tid = "shared-trace-id"
event1 = from_execution_intent(profile, trace_id=tid)
event2 = from_readiness_result(readiness, intent_profile=profile, trace_id=tid)
event3 = from_execution_result(exec_result, intent_profile=profile, trace_id=tid)
```

---

## Related Documents

- [`docs/EXECUTION_INTENT_PROFILE.md`](EXECUTION_INTENT_PROFILE.md) — PR-22
- [`docs/EXECUTION_READINESS_GATE.md`](EXECUTION_READINESS_GATE.md) — PR-23
- [`docs/FALLBACK_DECISION_TRACE.md`](FALLBACK_DECISION_TRACE.md) — PR-24

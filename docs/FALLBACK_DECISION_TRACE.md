# Fallback Decision Trace (PR-24)

## Overview

The **Fallback Decision Trace** is a unified, serialisable record that
explains *how* and *why* execution fell back when the primary execution path
was blocked, unavailable, or downgraded.

Before this layer, fallback behaviour was implicit: the system might retry,
no-op, block, degrade, or route to a different path, but there was no
canonical object that answered:

- What was the original execution attempt?
- Why was the primary path not taken?
- Which fallback path was selected?
- What rules or conditions caused that selection?
- What was the final outcome of the fallback decision?

PR-24 introduces that missing decision-trace layer.

---

## Difference Between Readiness Failure and Fallback Selection

These are related but distinct concepts:

| Concept | What it answers | Module |
|---|---|---|
| **Readiness failure** | *Can the system execute at all right now?* Checks pre-conditions: policy, HITL, domain, missing target, action level. | `core/execution/readiness_gate.py` (PR-23) |
| **Fallback selection** | *Given that the primary path was blocked/failed, what alternative was chosen?* Records the decision, source, and outcome. | `core/execution/fallback_trace.py` (PR-24) |

A readiness failure is an *input signal* to the fallback trace.  The trace
wraps the full context and answers "here is what happened and why".

---

## Canonical Objects

### `FallbackDecisionTrace`

The main record. Produced by `build_fallback_trace()`.

| Field | Type | Description |
|---|---|---|
| `trace_id` | `str` (UUID4) | Unique identifier for this trace record |
| `runtime_session_id` | `Optional[str]` | Active OpenClawd session ID |
| `intent_id` | `Optional[str]` | ID of the originating `ExecutionIntentProfile` |
| `action_level` | `str` | Decision Gate action level (`observe` / `hint` / `assist` / `execute`) |
| `primary_path` | `Optional[str]` | The execution path that was originally attempted |
| `primary_block_reason` | `Optional[str]` | Why the primary path was not taken |
| `fallback_path` | `Optional[str]` | The fallback path that was selected |
| `fallback_reason` | `Optional[str]` | Explanation of the fallback selection |
| `decision_source` | `str` | Which component made the fallback decision (see `FallbackDecisionSource`) |
| `candidate_paths` | `List[dict]` | All paths considered during selection (optional) |
| `outcome` | `str` | Final outcome (see `FallbackOutcome`) |
| `notes` | `Optional[str]` | Optional debug/context note |
| `timestamp` | `float` | Unix timestamp when the trace was created |

### `FallbackCandidate`

A single execution path considered during fallback selection.

| Field | Type | Description |
|---|---|---|
| `path` | `str` | Human-readable path name (e.g. `"local_executor"`, `"noop"`) |
| `executor_level` | `Optional[str]` | Executor tier (aligned with `ExecutorLevel`) |
| `reason_blocked` | `Optional[str]` | Why this candidate was not selected, or `None` if it was |
| `evaluated` | `bool` | Whether this candidate was actively evaluated |
| `selected` | `bool` | Whether this was the final chosen path |
| `metadata` | `dict` | Additional context |

### `FallbackDecisionResult`

Wraps a trace together with a resolved outcome for consumers.

| Field | Type | Description |
|---|---|---|
| `trace` | `dict` | Full `FallbackDecisionTrace` as a serialisable dict |
| `outcome` | `str` | Resolved `FallbackOutcome` value |
| `has_fallback` | `bool` | `True` when a fallback path was selected |

---

## Outcome Vocabulary (`FallbackOutcome`)

| Value | Meaning |
|---|---|
| `selected` | A fallback path was identified and selected; execution proceeded on it |
| `blocked` | Execution was fully blocked — no viable path was available |
| `noop` | No execution attempted; action level/policy permitted only observe/hint |
| `degraded` | Execution proceeded but at reduced capability (e.g. executor unavailable) |
| `failed` | The selected fallback path was attempted but ultimately failed |

---

## Decision Source Vocabulary (`FallbackDecisionSource`)

| Value | Meaning |
|---|---|
| `policy` | Policy layer (PolicyBand / HITL) blocked the primary path |
| `readiness_gate` | Execution Readiness Gate blocked it (missing target, domain, etc.) |
| `runtime` | Runtime signals (tri-state phase, runtime domain) caused unavailability |
| `bridge` | Bridge / remote-handoff layer fell back to local (remote unavailable) |
| `executor` | Executor-level failure (UIA unavailable, no system API match, …) |
| `unknown` | Could not be determined from available context |

---

## Typical Examples

### Example 1: Policy block → noop

```
action_level:         execute
primary_path:         local_executor
primary_block_reason: policy band OBSERVE_ONLY does not permit execution
decision_source:      policy
fallback_path:        noop
fallback_reason:      readiness_gate:observe_only:action_level
outcome:              noop
```

### Example 2: Missing target → blocked

```
action_level:         execute
primary_path:         local_executor
primary_block_reason: execution target is required but was not resolved
decision_source:      readiness_gate
fallback_path:        null
fallback_reason:      readiness_gate:blocked:missing_target
outcome:              blocked
```

### Example 3: Remote unavailable → local fallback

```
action_level:         execute
primary_path:         cross_device
primary_block_reason: remote device unreachable
decision_source:      bridge
fallback_path:        local_fallback
fallback_reason:      remote_device_unavailable
outcome:              selected
```

### Example 4: Executor unavailable → degraded

```
action_level:         execute
primary_path:         local_executor
primary_block_reason: null
decision_source:      executor
fallback_path:        local_fallback
fallback_reason:      executor_unavailable
outcome:              degraded
```

### Example 5: Observe-level intent → noop (expected)

```
action_level:         observe
primary_path:         local_executor
primary_block_reason: null
decision_source:      unknown
fallback_path:        noop
fallback_reason:      action_level_observe_only
outcome:              noop
```

---

## Usage

```python
from core.execution.fallback_trace import (
    build_fallback_trace,
    summarize_fallback_trace,
    FallbackDecisionTrace,
    FallbackDecisionResult,
)

# Build a trace from available execution signals
trace = build_fallback_trace(
    intent_profile=profile,       # ExecutionIntentProfile (PR-22)
    readiness_result=readiness,   # ReadinessResult (PR-23)
    execution_result=exec_result, # dict from _run_execution
)

# Full serialisable dict
payload = trace.to_dict()

# Compact governance/projection summary
summary = summarize_fallback_trace(trace)
```

The module-level `build_fallback_trace()` accepts `None` for any parameter
and always returns a valid trace; it never raises.

---

## Integration in `core/openclawd.py`

`OpenClawd._run_execution()` emits a fallback trace for every execution
result path:

- Readiness gate blocked → trace emitted with `decision_source=readiness_gate`
- Executor unavailable → trace with `outcome=degraded`
- Internal error → trace with `outcome=failed`
- Successful execution → trace with `outcome=selected`

The trace is attached as `"fallback_trace"` in the returned dict (alongside
the existing `"execution_intent"` and `"readiness"` keys).  Consuming code
is not required to read it.

---

## What This PR Does NOT Do

This PR intentionally does **not** implement:

- A full execution trace contract (PR-25)
- Projection assembly governance overhaul (PR-26)
- Runtime governance snapshot (PR-27)
- Execution policy alignment surface (PR-28)
- Any change to public response contracts beyond the additive `"fallback_trace"` key
- Any modification to the execution engine logic

The fallback decision trace is purely **additive** and **observational**.
It records what happened without changing what happens.

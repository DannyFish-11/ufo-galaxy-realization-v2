# Execution Policy Enforcement

> **PR-12 (V4)** — Additive enforcement of the execution-policy schema introduced in PR-11.

## Overview

PR-12 applies the execution-policy schema defined in PR-11 to real execution
paths so the system begins to honour phase/domain/authority/return-derived
constraints in practice.

Enforcement is **additive**, **observable**, and **safe-by-default**:

- Existing paths continue to work without any policy supplied (backward compatible).
- When a policy is supplied, enforcement decisions are structured and logged.
- When a guardrail check fails it returns a stable, JSON-serialisable outcome
  rather than raising an opaque exception.

---

## Architecture Overview

```
                ┌────────────────────────────────────────────┐
                │        core/execution_policy/              │
                │                                            │
                │  PR-11 (schema):                           │
                │   policy_band.py    ExecutionPolicy        │
                │   execution_policy.py  resolve_policy()    │
                │   policy_resolver.py   policy_summary.py   │
                │                                            │
                │  PR-12 (enforcement):                      │
                │   policy_decision.py   PolicyOutcome       │
                │                        PolicyDecision      │
                │   policy_guardrails.py (5 check functions) │
                │   policy_enforcement.py (orchestration)    │
                └─────────────────┬──────────────────────────┘
                                  │ enforce_execution_intent()
                                  │ enforce_cross_device()
                                  │ enforce_executor_levels()
                                  │ emit_policy_decision()
            ┌─────────────────────┼─────────────────────────┐
            │                     │                          │
   WindowsExecutionArbiter  TaskGraph.execute()  run_multi_device_via_task_graph()
   (core/windows_execution_  (core/task_graph.py) (core/e2e_orchestrator.py)
    arbiter.py)
            │
   DesktopPresenceRuntime (lightweight policy_hint)
   (core/desktop_presence_runtime.py)
```

---

## Enforcement Paths (PR-12)

### ✅ Enforced in this PR

| Path | Enforcement type | Description |
|------|-----------------|-------------|
| `WindowsExecutionArbiter.execute()` | Block / confirm / level-cap | Policy applied before the 4-level fallback chain |
| `TaskGraph.execute()` | Block / confirm / node skip | Policy applied at graph entry; cross-device nodes pre-skipped |
| `run_multi_device_via_task_graph()` | Cross-device gate | Policy cross-device check before TaskGraph dispatch |
| `DesktopPresenceRuntime.handle_request()` | Observable hint | Policy computed and attached as `policy_hint`; non-blocking |

### ❌ Not yet enforced in this PR

| Path | Notes |
|------|-------|
| `ConstellationRuntime.run()` | Planning/DAG loop; future PR |
| `EndToEndPipeline.execute()` | Legacy path; future PR |
| `SmartOrchestrator` | Future PR |
| `Node_71` / `DAGScheduler` | Future PR |
| `compile_and_run_dag()` | Policy passed through to `TaskGraph.execute()` only |
| `process_user_input()` | Routes through `DesktopPresenceRuntime`; indirect enforcement |

---

## Policy Outcomes (stable codes)

All enforcement decisions return a `PolicyDecision` with one of these stable
`PolicyOutcome` codes:

| Code | Meaning |
|------|---------|
| `allowed` | Execution is permitted under the current policy |
| `blocked_by_policy` | Band is `observe_only` or `assistive`; side-effectful execution denied |
| `confirmation_required` | Action is not blocked outright, but must be confirmed before proceeding |
| `cross_device_not_allowed` | `cross_device_allowed=False`; expansion to remote devices denied |
| `executor_level_capped` | Requested executor level not in `allowed_executor_levels`; suggest downgrade |
| `downgraded` | Execution intent downgraded to a lower band or level |

---

## Block / Degrade / Hold Behavior

### Block (`blocked_by_policy`)

Triggered when `policy_band` is `observe_only` or `assistive` and the action
is side-effectful.

```python
decision = check_side_effectful_execution(policy, is_side_effectful=True)
if decision.is_blocked:
    # Return structured result, do not proceed
    return decision.to_dict()
```

**Effect on execution paths:**
- `WindowsExecutionArbiter.execute()` returns `WinExecResult(success=False, policy_outcome="blocked_by_policy")`.
- `TaskGraph.execute()` returns `GraphExecutionResult(success=False, error="blocked_by_policy: ...")` with all nodes marked `SKIPPED`.

### Hold (`confirmation_required`)

Triggered when `requires_confirmation=True` in the policy (typically `bounded_execute` band).

```python
decision = check_side_effectful_execution(policy, is_side_effectful=True)
if decision.needs_confirmation:
    # Surface confirmation requirement to the caller
    return {"status": "pending_confirmation", "reason": decision.reason}
```

**Effect on execution paths:**
- `WindowsExecutionArbiter.execute()` returns `WinExecResult(success=False, policy_outcome="confirmation_required")`.
- `TaskGraph.execute()` returns a failed result with all nodes `SKIPPED` and `error` containing `"confirmation_required: ..."`.

> **Note:** Confirmation gating is a *hold*, not a permanent block. Once the caller obtains confirmation and re-submits with a higher-band policy, execution proceeds normally.

### Cross-device deny (`cross_device_not_allowed`)

Triggered when `cross_device_allowed=False` and cross-device expansion is requested.

```python
decision = enforce_cross_device(policy)
if not decision.is_allowed:
    return {
        "success": False,
        "error": "cross_device_not_allowed",
        "policy_reason": decision.reason,
    }
```

**Effect on execution paths:**
- `run_multi_device_via_task_graph()` returns early with `policy_outcome="cross_device_not_allowed"`.
- `TaskGraph.execute()` pre-skips any node whose `device_id` is not empty and not `"local"`.

### Executor level cap (`executor_level_capped`)

Triggered when a requested level is not in `allowed_executor_levels`.

```python
permitted, blocked = filter_executor_levels(policy, ["system_api", "uia", "gui", "vlm"])
# e.g. bounded_execute → permitted=["system_api", "uia"], blocked=["gui", "vlm"]
```

**Effect on execution paths:**
- `WindowsExecutionArbiter.execute()` removes disallowed levels from the fallback chain before execution begins.

---

## Confirmation Requirement Surfacing

When `requires_confirmation=True`:

1. `check_confirmation_required(policy)` returns `PolicyDecision(outcome=CONFIRMATION_REQUIRED)`.
2. Callers receive `decision.needs_confirmation == True` (a property, not an exception).
3. The structured result includes `hint="confirmation_required"` and a human-readable `reason`.
4. Callers may surface this to the UI or a human-in-the-loop system before re-submitting.

---

## Observability

### Structured logging

Every call to any enforcement helper emits a structured log via
`Galaxy.ExecutionPolicy.Enforcement` logger:

```
policy_enforcement | blocked_by_policy | band=observe_only | policy_band=observe_only does not permit side-effectful execution
```

Fields always present:
- `policy_decision` — the outcome code
- `policy_band` — the active policy band
- `reason` — human-readable explanation
- `cross_device_allowed` — current flag value
- `requires_confirmation` — current flag value

Optional fields:
- `blocked_levels` — executor levels removed from the chain
- `downgraded_to` — suggested alternative level
- Any fields from the `context` dict passed by the caller (e.g. `trace_id`, `device_id`)

### Log levels

| Outcome | Level |
|---------|-------|
| `blocked_by_policy` | `INFO` |
| `cross_device_not_allowed` | `INFO` |
| `confirmation_required` | `INFO` |
| `executor_level_capped` | `INFO` |
| `allowed` | `DEBUG` |

### `policy_hint` in `DesktopPresenceRuntime`

After PR-12, every response from `DesktopPresenceRuntime.handle_request()`
includes an additive `policy_hint` field:

```json
{
  "success": true,
  "response": "...",
  "policy_hint": {
    "policy_band": "observe_only",
    "can_execute": false,
    "can_expand_cross_device": false,
    "should_require_confirmation": true,
    "max_executor_level": null,
    "risk_budget": 0.0,
    "action_budget": 0,
    "return_pressure": 0.0
  }
}
```

This field is **additive and non-blocking** — it never affects the response
path; it is purely for downstream observability and debugging.

---

## Usage Examples

### Check before side-effectful execution

```python
from core.execution_policy import resolve_policy, enforce_execution_intent

# Derive policy from current runtime signals
policy = resolve_policy(phase="liminal")

# Enforce before executing
decision = enforce_execution_intent(
    policy,
    is_side_effectful=True,
    requires_cross_device=False,
)
if decision.is_blocked:
    return {"error": decision.hint, "detail": decision.reason}
if decision.needs_confirmation:
    return {"status": "pending_confirmation", "reason": decision.reason}
# proceed with execution...
```

### WindowsExecutionArbiter with policy

```python
from core.windows_execution_arbiter import get_windows_arbiter
from core.execution_policy import resolve_policy

arbiter = get_windows_arbiter()
policy = resolve_policy(phase="manifest")

result = await arbiter.execute(
    action="click",
    params={"x": 100, "y": 200},
    device_id="windows-1",
    policy=policy,
)
if not result.success:
    print(result.policy_outcome)  # e.g. "confirmation_required"
```

### TaskGraph with policy

```python
from core.task_graph import TaskGraph
from core.execution_policy import resolve_policy

policy = resolve_policy(phase="manifest", domain="cross_device")
graph = TaskGraph()
# ... add nodes ...
result = await graph.execute(policy=policy)
if not result.success:
    print(result.error)  # e.g. "blocked_by_policy: observe_only..."
```

### Multi-device with policy

```python
from core.e2e_orchestrator import run_multi_device_via_task_graph
from core.execution_policy import resolve_policy

policy = resolve_policy(phase="manifest")  # no cross_device

result = await run_multi_device_via_task_graph(
    subtasks,
    policy=policy,
)
if result.get("policy_outcome") == "cross_device_not_allowed":
    # route to local-only execution
    ...
```

---

## Public API Surface (PR-12 additions to `core/execution_policy`)

```python
from core.execution_policy import (
    # Decision types
    PolicyOutcome,          # Enum: allowed / blocked_by_policy / ...
    PolicyDecision,         # Immutable result dataclass

    # Guardrail helpers (stateless, pure)
    check_side_effectful_execution,   # block when observe_only / assistive
    check_confirmation_required,      # surface requires_confirmation
    check_cross_device_expansion,     # deny when cross_device_allowed=False
    check_executor_level,             # cap to allowed executor levels
    filter_executor_levels,           # partition candidate levels

    # Orchestration helpers
    enforce_execution_intent,         # composite check
    enforce_cross_device,             # cross-device check only
    enforce_executor_levels,          # level filter + observability
    emit_policy_decision,             # structured log emission
)
```

---

## Tests

Tests are in `tests/test_pr12_execution_policy_enforcement.py` and cover:

| Section | Coverage |
|---------|---------|
| A | `PolicyOutcome` enum values and stability |
| B | `PolicyDecision` construction, properties, serialisation |
| C | `check_side_effectful_execution` — all band combinations |
| D | `check_confirmation_required` |
| E | `check_cross_device_expansion` |
| F | `check_executor_level` |
| G | `filter_executor_levels` |
| H | `enforce_execution_intent` composite |
| I | `enforce_cross_device` |
| J | `enforce_executor_levels` |
| K | `emit_policy_decision` smoke tests |
| L | `WindowsExecutionArbiter` integration |
| M | `TaskGraph` integration |
| N | `run_multi_device_via_task_graph` integration |
| O | Structured result stability |
| P | `DesktopPresenceRuntime` policy_hint observability |

Run with:
```bash
python -m pytest tests/test_pr12_execution_policy_enforcement.py -v
```

---

## Relationship to PR-11

| Aspect | PR-11 | PR-12 |
|--------|-------|-------|
| Schema | ✅ defines `ExecutionPolicy`, `PolicyBand` | reads only |
| Resolver | ✅ `resolve_policy()` from runtime signals | reads only |
| Guardrails | ❌ | ✅ `policy_guardrails.py` |
| Decision types | ❌ | ✅ `policy_decision.py` |
| Enforcement orchestrator | ❌ | ✅ `policy_enforcement.py` |
| WindowsExecutionArbiter | ❌ | ✅ additive `policy=` param |
| TaskGraph | ❌ | ✅ additive `policy=` param |
| E2E orchestrator | ❌ | ✅ additive `policy=` param |
| DesktopPresenceRuntime | ❌ | ✅ `policy_hint` field |

---

## Design Decisions

### Why additive params, not constructor injection?

The `policy=` parameter on `execute()` methods is optional and defaults to
`None`. This means:

1. **Backward compatible**: all existing callers work without modification.
2. **Gradual adoption**: policy can be introduced per-call-site without a big-bang refactor.
3. **Testable in isolation**: tests can pass specific policies without affecting the singleton.

### Why not throw on block?

Returning a structured `PolicyDecision` (or enriched `WinExecResult` / `GraphExecutionResult`)
allows callers to:
- Inspect the reason programmatically
- Route to fallbacks (e.g. local-only path)
- Surface the confirmation requirement to a UI
- Log the outcome with full context

Throwing would force callers to catch and parse exception messages, which is fragile.

### Why `emit_policy_decision` rather than structured events?

PR-12 uses Python logging rather than a full event bus for two reasons:
1. `Galaxy.ExecutionPolicy.Enforcement` logger entries are already captured by
   the existing execution observability infrastructure (PR #262).
2. A lightweight log is sufficient for this enforcement layer; heavier event
   bus integration is reserved for future policy audit PRs.

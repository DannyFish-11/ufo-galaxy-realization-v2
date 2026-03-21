# EXECUTION_READINESS_GATE.md

## Execution Readiness Gate — PR-23

---

## What the Readiness Gate Is

The **Execution Readiness Gate** is the single canonical pre-execution decision
layer that answers:

- **Is the system ready to execute?** (`ready: bool`)
- **If not, why not?** (`blocked_by`, `reason`)
- **If yes, does it still require confirmation?** (`requires_confirmation`, `status`)
- **Which policy band explains the result?** (`policy_band`)

It is implemented in `core/execution/readiness_gate.py` and is invoked by
`OpenClawd._run_execution()` before dispatching any action to the executor.

---

## What Inputs It Consumes

| Input | Source | Notes |
|-------|--------|-------|
| `ExecutionIntentProfile` | PR-22 `core/execution/intent_profile.py` | Structured intent — action_level, target_ref, domain, session_id |
| `state_continuum` dict | `OpenClawd._run_execution()` | Serialised `ContinuumState`; feeds the policy resolver |
| Tri-state phase | `state_continuum["phase"]` | Feeds `resolve_policy(phase=…)` |
| Runtime domain | `state_continuum["runtime_domain"]` or intent profile | Feeds `resolve_policy(domain=…)` |
| `ExecutionPolicy` | `core/execution_policy/policy_resolver.resolve_policy()` | Resolved from phase + domain |
| HITL mode / decision | `core/policy/hitl_policy.get_hitl_policy()` | Evaluated for confirmation or block |

All inputs are **optional**. The gate degrades conservatively when signals are
absent.

---

## How It Composes Policy / HITL / Runtime-State Checks

The gate evaluates readiness in the following priority order:

### 1. Action-level check
If `action_level` is `observe` or `hint`, the result is immediately
`observe_only` — no side-effectful execution is permitted regardless of
policy or HITL state.

### 2. Missing intent guard
If no `intent_profile` was provided and no explicit `action_level` override
was given, the result is `blocked` with `blocked_by=missing_intent`.

### 3. Missing target guard *(optional)*
When `require_target=True`, a missing `target_ref` blocks execution with
`blocked_by=missing_target`. Disabled by default.

### 4. Execution-policy gate
The gate delegates to `core.execution_policy.resolve_policy()` using
`phase` and `runtime_domain` from the continuum dict. If the resolved
`PolicyBand` is `observe_only` or `assistive` (i.e.
`band_allows_execution()` returns `False`), the result is `blocked` with
`blocked_by=policy`.

### 5. HITL gate
The gate delegates to `core.policy.hitl_policy.HITLPolicy.evaluate()`.
- A **REJECTED** decision → `blocked` with `blocked_by=hitl`.
- **MANUAL** mode or `bounded_execute` band in **SEMI** mode → `confirm_required`.

### 6. Confirmation gate
If either the execution policy has `requires_confirmation=True` or HITL
signals a confirmation requirement, the result is `confirm_required`
(`ready=True` but `requires_confirmation=True`).

### 7. Ready
All gates passed → `ready=True`, `status=ready`.

---

## Possible Statuses and Reasons

| `status` | `ready` | `requires_confirmation` | Typical `blocked_by` |
|----------|---------|------------------------|----------------------|
| `ready` | `True` | `False` | `none` |
| `confirm_required` | `True` | `True` | `confirmation_required` |
| `blocked` | `False` | `False` | `policy` / `hitl` / `missing_target` / `missing_intent` / `domain` |
| `observe_only` | `False` | `False` | `action_level` |

---

## Examples

### Ready path

```python
from core.execution.readiness_gate import evaluate_readiness
from core.execution.intent_profile import build_execution_intent_profile

continuum = {
    "phase": "manifest",
    "runtime_domain": "local",
    "decision": {"action_level": "execute", "decision_confidence": 0.9},
    "metadata": {"execution_target": "notepad.exe"},
}
profile = build_execution_intent_profile(continuum)
result = evaluate_readiness(profile, state_continuum=continuum)

assert result.ready is True
assert result.status == "ready"
assert result.requires_confirmation is False
assert result.policy_band in ("bounded_execute", "full_execute")
```

### Blocked path — policy (observe_only phase)

```python
continuum = {
    "phase": "silent",           # → policy_band = observe_only
    "runtime_domain": "local",
    "decision": {"action_level": "execute"},
}
result = evaluate_readiness(action_level="execute", state_continuum=continuum)

assert result.ready is False
assert result.status == "blocked"
assert result.blocked_by == "policy"
```

### Blocked path — action_level observe

```python
result = evaluate_readiness(action_level="observe")

assert result.ready is False
assert result.status == "observe_only"
assert result.blocked_by == "action_level"
```

### Blocked path — missing intent/target

```python
# No intent_profile and no explicit action_level
result = evaluate_readiness()

assert result.ready is False
assert result.blocked_by == "missing_intent"
```

```python
# require_target=True but no target was resolved
result = evaluate_readiness(action_level="execute", require_target=True)

assert result.ready is False
assert result.blocked_by == "missing_target"
```

### Confirm-required path — HITL / policy requires confirmation

```python
from core.policy.hitl_policy import HITLPolicy, HITLMode, get_hitl_policy

policy = get_hitl_policy()
policy.mode = HITLMode.MANUAL  # all actions require confirmation

result = evaluate_readiness(action_level="execute")

assert result.ready is True
assert result.status == "confirm_required"
assert result.requires_confirmation is True
```

---

## Governance Summary Hook

`ReadinessResult.governance_summary()` returns a compact dict suitable for
inclusion in projection surfaces or runtime governance assemblies:

```python
result = evaluate_readiness(profile, state_continuum=continuum)
summary = result.governance_summary()
# {
#   "ready": True,
#   "status": "ready",
#   "requires_confirmation": False,
#   "policy_band": "full_execute",
#   "blocked_by": "none",
#   "action_level": "execute",
#   "intent_id": "<uuid>",
# }
```

`OpenClawd._run_execution()` includes this summary as the `"readiness"` key in
every execution result dict (additive, backward-compatible).

---

## Module Locations

| File | Role |
|------|------|
| `core/execution/readiness_gate.py` | `ReadinessStatus`, `BlockedBy`, `ReadinessResult`, `ExecutionReadinessGate`, `evaluate_readiness`, `reset_readiness_gate` |
| `core/execution/__init__.py` | Re-exports all gate symbols |
| `core/openclawd.py` | `_check_readiness()` helper; `_run_execution()` integrates gate before dispatch |
| `docs/EXECUTION_READINESS_GATE.md` | This document |
| `tests/test_pr23_execution_readiness_gate.py` | Focused tests |

---

## What This PR Explicitly Does NOT Do Yet

- **No fallback decision trace** — the gate reports a decision but does not
  record a full fallback trace chain. That is scope for PR-24.
- **No full execution trace contract** — the gate does not emit a structured
  trace event bus entry. PR-25 handles the execution trace contract.
- **No runtime governance snapshot** — the gate provides a narrow governance
  summary hook but does not assemble a full runtime governance snapshot. PR-27
  handles that.
- **No final policy alignment surface** — the gate does not produce a
  policy-alignment surface. PR-28 handles that.
- **No Windows execution arbiter** — the gate gates dispatch but does not
  select or arbitrate between executor levels. That is scope for PR-24.
- **No multi-device execution routing** — the gate records `runtime_domain`
  but does not route across devices. PR-27 handles domain-aware routing.

---

## Dependencies

| Dependency | Role |
|------------|------|
| `core/execution/intent_profile.py` (PR-22) | `ExecutionIntentProfile` — structured intent input |
| `core/execution_policy/` (PR-11/12) | Policy resolver, `PolicyBand`, enforcement guardrails |
| `core/policy/hitl_policy.py` (PR-4) | HITL mode, decision evaluation |
| `pydantic` | `ReadinessResult` serialisation |

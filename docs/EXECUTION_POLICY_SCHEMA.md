# Execution Policy Schema — Design Document

**PR-11 (V4) — Execution Policy Schema**

---

## Overview

`core/execution_policy/` is a focused, additive package that introduces a
formal **execution-policy schema layer** for the Galaxy runtime.

It consumes signals already present in PRs 262–265 (observability,
envelope consolidation, orchestration authority, return intelligence) and
turns them into explicit, stable **execution constraints and budgets**.

This PR is about **policy schema + resolver + summary**. Enforcement in
active execution paths belongs in the follow-up PR.

---

## What Policy Band Means

`PolicyBand` is the top-level classifier of what execution class is currently
permitted:

| Band | Meaning | Typical context |
|------|---------|-----------------|
| `observe_only` | Sensing / read-only only. No side-effectful actions. | `silent` phase, or high return pressure |
| `assistive` | Advisory / suggestive output. No direct device actions. | `liminal` phase, early intent formation |
| `bounded_execute` | Constrained execution within an explicit risk/action budget. Confirmation required. | `manifest` phase, local domain |
| `full_execute` | Full execution authority. Cross-device eligible. | `manifest` phase, `cross_device` domain, active authority |

---

## Policy Fields

An `ExecutionPolicy` object carries the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `policy_band` | `PolicyBand` | Top-level execution tier |
| `risk_budget` | `float [0,1]` | Normalised risk allowance |
| `action_budget` | `int` | Max side-effectful steps permitted (`-1` = unbounded) |
| `fallback_budget` | `int` | Max fallback/retry attempts |
| `allowed_executor_levels` | `list[str]` | Permitted executor tiers |
| `cross_device_allowed` | `bool` | Whether cross-device expansion is permitted |
| `requires_confirmation` | `bool` | Whether HITL confirmation is required |
| `reason` | `str` | Human-readable explanation |
| `source_phase` | `str \| None` | `TriStatePhase` that contributed |
| `source_domain` | `str \| None` | `RuntimeDomain` that contributed |
| `source_authority_role` | `str \| None` | `AuthorityRole` that contributed |
| `return_pressure` | `float [0,1]` | Normalised return/receding pressure |

Derived helpers (also included in `to_dict()`):

| Helper | Type | Description |
|--------|------|-------------|
| `can_execute` | `bool` | Policy permits at least some direct execution |
| `can_expand_cross_device` | `bool` | Cross-device expansion is allowed |
| `should_require_confirmation` | `bool` | Confirmation is required |
| `max_executor_level` | `str \| None` | Highest permitted executor level |

---

## How Policy Is Derived

`resolve_policy()` accepts all-optional signals and applies these rules in
priority order:

### 1. Return-pressure override

If the normalised return pressure (derived from `ReturnSummary` + optional
`retreat_tendency`) is `>= 0.75`, the band is forced to `observe_only`
regardless of other signals.

### 2. Phase-primary band

| `TriStatePhase` | Base band |
|-----------------|-----------|
| `silent` | `observe_only` |
| `liminal` | `assistive` |
| `manifest` | `bounded_execute` |
| absent/unknown | `observe_only` (conservative default) |

### 3. Domain upgrade

`RuntimeDomain.CROSS_DEVICE` + `manifest` phase → `full_execute` with
`cross_device_allowed=True`.

### 4. Authority downgrade

Legacy or deprecated `AuthorityRole` values downgrade the band by one level
and disable cross-device expansion.

### 5. Moderate return-pressure restriction

Return pressure `>= 0.40` restricts action budget (halved), forces
`requires_confirmation=True`, disables `cross_device_allowed`, and clamps
`full_execute` down to `bounded_execute`.

### 6. Budget computation

| Band | `risk_budget` | `action_budget` | `fallback_budget` |
|------|--------------|-----------------|-------------------|
| `observe_only` | 0.0 | 0 | 0 |
| `assistive` | 0.1 | 0 | 1 |
| `bounded_execute` | 0.5 | 5 | 2 |
| `full_execute` | 1.0 | -1 (unbounded) | 3 |

### 7. Executor levels by band

| Band | Permitted executor levels |
|------|--------------------------|
| `observe_only` | `[]` (none) |
| `assistive` | `["orchestrator"]` |
| `bounded_execute` | `["system_api", "uia", "orchestrator"]` |
| `full_execute` | `["system_api", "uia", "gui", "vlm", "remote_executor", "orchestrator"]` |

---

## What This PR Does NOT Enforce

This PR introduces the schema, resolver, and summary helpers only. It does
**not**:

- Gate or block execution in `WindowsExecutionArbiter`
- Block task submissions in `TaskGraph`
- Modify `ConstellationRuntime` or `DesktopPresenceRuntime`
- Replace any existing executor, orchestrator, or routing module
- Introduce a competing top-level runtime

Enforcement belongs in the next PR.

---

## How Future PRs Should Use This Schema

### For enforcement in `WindowsExecutionArbiter`

```python
from core.execution_policy import resolve_policy
from core.continuum.types import TriStatePhase, RuntimeDomain

policy = resolve_policy(
    phase=TriStatePhase.MANIFEST,
    domain=RuntimeDomain.LOCAL,
)

if not policy.can_execute:
    raise PolicyBlockError(f"Execution blocked: {policy.reason}")

if policy.requires_confirmation:
    await hitl_confirm(task)
```

### For enforcement in `TaskGraph`

```python
from core.execution_policy import resolve_policy, PolicyBand

policy = resolve_policy(phase=current_phase, domain=current_domain)

if policy.policy_band is PolicyBand.OBSERVE_ONLY:
    # Drop to read-only path
    return await observe_only_path(task)

if policy.action_budget != -1:
    # Apply action count limit
    task.set_max_actions(policy.action_budget)
```

### For projection consumers

```python
from core.execution_policy import build_policy_for_projection, get_policy_hints

hints = build_policy_for_projection(projection.to_dict())
if hints["can_expand_cross_device"]:
    ...
```

---

## Relationship to Other Layers

| Layer | PR | Role |
|-------|----|------|
| Execution Observability | PR #262 | `ExecutorLevel` enum consumed by policy budget tables |
| Envelope Consolidation | PR #263 | `EnvelopeSummary` can be annotated with policy context |
| Orchestration Authority | PR #264 | `AuthorityRole` used for authority-based band downgrades |
| Return Intelligence | PR #265 | `ReturnSummary` drives return-pressure computation |
| **Execution Policy** | **PR #266 (this PR)** | **Derives constraints from all of the above** |
| Policy Enforcement | Next PR | Will gate execution using this schema |

---

## API Endpoint

A new read-only endpoint is available:

```
GET /api/v1/projection/execution_policy
```

Returns the standard `RuntimeProjection` fields plus `"return_intelligence"`
(from PR-10) and `"execution_policy"` (from this PR).

The `"execution_policy"` block includes all policy fields and the derived
hints (`can_execute`, `can_expand_cross_device`, etc.).

This endpoint is **read-only** and does not enforce the policy.

---

## Package Structure

```
core/execution_policy/
├── __init__.py            — Public API surface
├── policy_band.py         — PolicyBand enum and band helpers
├── execution_policy.py    — ExecutionPolicy dataclass
├── policy_resolver.py     — Resolver: signals → ExecutionPolicy
└── policy_summary.py      — Public-safe summary/hint helpers
```

---

## Graceful Degradation

All resolver and summary functions degrade gracefully:

- Missing signals → conservative defaults applied
- Import errors → `DEFAULT_CONSERVATIVE_POLICY` returned
- Unexpected exceptions → logged, conservative policy returned
- `None` inputs accepted at every function boundary

The package is designed to be safe to import and call even when the
continuum, topology, or authority layers are partially unavailable.

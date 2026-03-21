# Projection Assembly Governance

**PR-26 — Canonical projection assembly governance layer for Galaxy.**

---

## Overview

Projection Assembly Governance is the canonical layer that determines:

- Which execution-governance signals are **promoted into the outward projection**
- Which fields are **safe and useful for read-only status surfaces**
- How readiness, fallback, and execution-trace information is **summarised for projection consumption**
- How projection **stays stable when some internal governance objects are missing**

It lives at `core/projection/assembly_governance.py` and extends the existing projection stack without rewriting any existing module.

---

## What Projection Assembly Governance Is

The projection layer (`core/projection/`) provides a read-only, wire-safe snapshot of the runtime state to the Status Board V2 and any other downstream read-only consumer.

Before PR-26, the base `RuntimeProjection` could surface continuum state, topology routing, device formation, agent-dispatch, routing explanation, and a compact execution intent summary.  However, it did not have a **canonical governance-aware assembly layer** that integrates:

- Readiness gate decisions (PR-23)
- Fallback decision traces (PR-24)
- Execution lifecycle traces (PR-25)

…into a stable, serialisable, projection-safe representation.

PR-26 fills that gap by introducing:

1. **Projection-safe governance summary contracts** (`ProjectionGovernanceSummary` and its sub-types)
2. **Assembly helpers** that build those summaries from existing governance objects
3. **Minimal backward-compatible integration** into the projection path

---

## How Projection Differs from Execution Trace and Readiness/Fallback Internals

| Layer | Purpose | Audience |
|---|---|---|
| `ExecutionIntentProfile` (PR-22) | Full internal intent record | Executor, policy gate, governance |
| `ReadinessResult` (PR-23) | Full readiness decision record | Executor, policy gate |
| `FallbackDecisionTrace` (PR-24) | Full fallback event record | Executor, audit, governance |
| `ExecutionTraceEnvelope` (PR-25) | Full execution lifecycle | Audit, observability |
| **`ProjectionGovernanceSummary` (PR-26)** | **Compact, projection-safe governance view** | **Status surfaces, read-only consumers** |

The projection layer is a **narrowing adapter**: it exposes stable, safe field names without leaking raw internal objects.  Downstream status surfaces and governance tools should consume the projection, not the raw governance objects.

---

## Governance Signals Promoted into Outward Projection

### From Execution Intent (PR-22)

| Signal | Projection field | Notes |
|---|---|---|
| `intent_id` | `governance.execution.intent_id` | Stable ID |
| `source` | `governance.execution.source` | Origin of intent |
| `action_level` | `governance.execution.action_level` | observe / hint / assist / execute |
| `intent_mode` | `governance.execution.intent_mode` | advisory / assistive / direct / autonomous |
| `target_type` | `governance.execution.target_type` | app / window / url / device / command |
| `target_ref` | `governance.execution.target_ref` | Specific target |
| `device_scope` | `governance.execution.device_scope` | local / remote / multi-device |
| `runtime_domain` | `governance.execution.runtime_domain` | local / cross_device / transition |
| `confidence` | `governance.execution.confidence` | [0, 1] |
| `degrade_reason` | `governance.execution.degrade_reason` | Non-null when downgraded |

### From Readiness/Policy (PR-23)

| Signal | Projection field | Notes |
|---|---|---|
| `ready` | `governance.policy.ready` | Execution permitted? |
| `status` | `governance.policy.status` | ready / confirm_required / blocked / observe_only |
| `reason` | `governance.policy.reason` | Human-readable explanation |
| `requires_confirmation` | `governance.policy.requires_confirmation` | HITL required? |
| `action_level` | `governance.policy.action_level` | Action level at evaluation |
| `policy_band` | `governance.policy.policy_band` | observe_only / assistive / bounded_execute / full_execute |
| `blocked_by` | `governance.policy.blocked_by` | Block cause code |
| `runtime_domain` | `governance.policy.runtime_domain` | Domain at evaluation time |
| `blocked` | `governance.policy.blocked` | Convenience flag |
| `degraded` | `governance.policy.degraded` | Reduced capability mode? |

### From Fallback Decision (PR-24)

| Signal | Projection field | Notes |
|---|---|---|
| `outcome` | `governance.fallback.outcome` | selected / blocked / noop / degraded / failed |
| `decision_source` | `governance.fallback.decision_source` | policy / readiness_gate / runtime / bridge / executor |
| `fallback_path` | `governance.fallback.fallback_path` | Selected fallback path |
| `reason` | `governance.fallback.reason` | Fallback selection reason |
| `primary_path` | `governance.fallback.primary_path` | Originally attempted path |
| `primary_block_reason` | `governance.fallback.primary_block_reason` | Why primary was not taken |
| `action_level` | `governance.fallback.action_level` | Action level at decision |

### From Execution Trace (PR-25)

| Signal | Projection field | Notes |
|---|---|---|
| `trace_id` | `governance.execution_trace.trace_id` | Shared trace ID |
| `intent_id` | `governance.execution_trace.intent_id` | Originating intent ID |
| `final_status` | `governance.execution_trace.final_status` | pending / success / failed / blocked / degraded / skipped |
| `stage_count` | `governance.execution_trace.stage_count` | Number of lifecycle stages |
| `stages` | `governance.execution_trace.stages` | Ordered list of stage names |

---

## Contracts

### `ProjectionGovernanceSummary`

Top-level governance-enriched projection summary.  Contains:

```python
class ProjectionGovernanceSummary:
    execution: ProjectionExecutionSummary    # intent (PR-22)
    policy: ProjectionPolicySummary          # readiness/policy (PR-23)
    fallback: ProjectionTraceSummary         # fallback trace (PR-24)
    execution_trace: ProjectionExecutionTraceSummary  # trace envelope (PR-25)
    tri_state_phase: Optional[str]           # phase at assembly time
    runtime_domain: Optional[str]            # domain at assembly time
    assembled_at: float                      # Unix epoch timestamp
    governance_available: bool               # True when at least one real input present
```

### `ProjectionExecutionSummary`

Compact summary of execution intent (PR-22).  Stable field names; no raw intent internals.

### `ProjectionPolicySummary`

Compact summary of readiness/policy posture (PR-23).  Includes convenience booleans `blocked` and `degraded`.

### `ProjectionTraceSummary`

Compact summary of fallback decision trace (PR-24).

### `ProjectionExecutionTraceSummary`

Compact summary of execution lifecycle trace envelope (PR-25).

---

## Assembly Helpers

All helpers are in `core/projection/assembly_governance.py` and are exported from `core/projection/__init__.py`.

### `summarize_intent_for_projection(intent_profile)`

Builds a `ProjectionExecutionSummary` from an `ExecutionIntentProfile` (PR-22).

### `summarize_readiness_for_projection(readiness_result)`

Builds a `ProjectionPolicySummary` from a `ReadinessResult` (PR-23).

### `summarize_fallback_for_projection(fallback_trace)`

Builds a `ProjectionTraceSummary` from a `FallbackDecisionTrace` (PR-24).

### `summarize_execution_trace_for_projection(execution_trace_envelope)`

Builds a `ProjectionExecutionTraceSummary` from an `ExecutionTraceEnvelope` (PR-25).

### `assemble_projection_governance(...)`

The **single narrow entry-point** for building governance-aware projection data.  Accepts all governance inputs and returns a `ProjectionGovernanceSummary`.

```python
from core.projection import assemble_projection_governance

governance = assemble_projection_governance(
    intent_profile=profile,        # Optional[ExecutionIntentProfile]
    readiness_result=readiness,    # Optional[ReadinessResult]
    fallback_trace=trace,          # Optional[FallbackDecisionTrace]
    execution_trace_envelope=env,  # Optional[ExecutionTraceEnvelope]
    state_continuum=state,         # Optional[ContinuumState or dict]
)
payload = governance.to_dict()
```

---

## Graceful Degradation

Every helper and the main assembler tolerate missing / `None` inputs:

- When `intent_profile=None` → `ProjectionExecutionSummary(available=False)`
- When `readiness_result=None` → `ProjectionPolicySummary(available=False)` with conservatively blocked defaults
- When `fallback_trace=None` → `ProjectionTraceSummary(available=False)` with `outcome="noop"`
- When `execution_trace_envelope=None` → `ProjectionExecutionTraceSummary(available=False)` with `final_status="pending"`
- When all inputs are `None` → `ProjectionGovernanceSummary(governance_available=False)` — a fully safe minimal summary
- Exception in any helper → warning logged; safe default returned; never re-raised

The `available` field on each sub-summary lets consumers distinguish "real data" from "safe default".

---

## Integration into the Projection Path

### `build_runtime_projection` (additive)

`core/projection/projection_compiler.py` now accepts three new optional parameters:

```python
build_runtime_projection(
    continuum_state,
    ...,
    readiness_result=None,        # PR-26
    fallback_trace=None,          # PR-26
    execution_trace_envelope=None, # PR-26
)
```

When any governance input is provided, the `governance` field of the returned `RuntimeProjection` is populated via `assemble_projection_governance`.

Existing callers with no governance inputs see `governance=None` — **fully backward-compatible**.

### `RuntimeProjection` (additive field)

`core/projection/runtime_projection.py` gains one new optional field:

```python
governance: Optional[Dict[str, Any]] = None
```

Serialised via `to_dict()` as `"governance": <dict or null>`.

Existing consumers that only inspect the previous fields are unaffected.

### `GET /api/v1/projection/governance` (new read-only endpoint)

```
GET /api/v1/projection/governance
```

Returns the standard `RuntimeProjection` fields plus:
- `"governance"`: a `ProjectionGovernanceSummary` dict
- `"governance_hints"`: a flat quick-check dict for the most important governance signals

---

## Example Projection Payloads

### Without governance data

```json
{
  "tri_state_phase": "liminal",
  "runtime_domain": "local",
  "presence_intensity": 0.45,
  "coherence": 0.62,
  "collapse_tendency": 0.30,
  "retreat_tendency": 0.15,
  "primary_model_id": "gpt-4o",
  "support_model_ids": [],
  "active_weights": {"gpt-4o": 0.85},
  "route_reason": "primary model selected",
  "active_device_ids": [],
  "execution_stage": null,
  "current_task_summary": null,
  "execution_intent_summary": null,
  "governance": null,
  "timestamp": 1710000000.0
}
```

### With governance data

```json
{
  "tri_state_phase": "manifest",
  "runtime_domain": "local",
  "presence_intensity": 0.82,
  "coherence": 0.91,
  "collapse_tendency": 0.70,
  "retreat_tendency": 0.05,
  "primary_model_id": "gpt-4o",
  "support_model_ids": [],
  "active_weights": {"gpt-4o": 0.90},
  "route_reason": "primary model selected",
  "active_device_ids": ["device-001"],
  "execution_stage": "executing",
  "current_task_summary": "Open browser to example.com",
  "execution_intent_summary": {
    "intent_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
    "source": "openclawd",
    "action_level": "execute",
    "intent_mode": "direct",
    "target_type": "url",
    "target_ref": "https://example.com",
    "device_scope": "local",
    "runtime_domain": "local",
    "confidence": 0.92,
    "degrade_reason": null
  },
  "governance": {
    "execution": {
      "intent_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "source": "openclawd",
      "action_level": "execute",
      "intent_mode": "direct",
      "target_type": "url",
      "target_ref": "https://example.com",
      "device_scope": "local",
      "runtime_domain": "local",
      "confidence": 0.92,
      "degrade_reason": null,
      "available": true
    },
    "policy": {
      "ready": true,
      "status": "ready",
      "reason": "full_execute band; action level execute; domain local",
      "requires_confirmation": false,
      "action_level": "execute",
      "policy_band": "full_execute",
      "blocked_by": "none",
      "runtime_domain": "local",
      "blocked": false,
      "degraded": false,
      "available": true
    },
    "fallback": {
      "outcome": "noop",
      "decision_source": "policy",
      "fallback_path": null,
      "reason": null,
      "primary_path": "local_executor",
      "primary_block_reason": null,
      "action_level": "execute",
      "available": true
    },
    "execution_trace": {
      "trace_id": "a1b2c3d4-...",
      "intent_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
      "final_status": "success",
      "stage_count": 4,
      "stages": [
        "intent_created",
        "readiness_evaluated",
        "fallback_selected",
        "execution_finished"
      ],
      "available": true
    },
    "tri_state_phase": "manifest",
    "runtime_domain": "local",
    "assembled_at": 1710000001.0,
    "governance_available": true
  },
  "timestamp": 1710000001.0
}
```

---

## What This PR Does NOT Do Yet

The following items are **explicitly out of scope** for PR-26 and will be addressed in later PRs:

| Item | Planned PR |
|---|---|
| Runtime Governance Snapshot | PR-27 |
| Execution Policy Alignment Surface | PR-28 |
| Visual/status-board redesign | Future UI PRs |
| Desktop-wide tri-state manifestation work | Future |
| Dashboard removal/migration | Future |
| New command routes or write-capable endpoints | Out of scope |
| Policy alignment diff surface | PR-28 |

---

## File Locations

| File | Role |
|---|---|
| `core/projection/assembly_governance.py` | Main governance assembly module (PR-26) |
| `core/projection/__init__.py` | Public exports (updated) |
| `core/projection/runtime_projection.py` | `RuntimeProjection` with new `governance` field |
| `core/projection/projection_compiler.py` | `build_runtime_projection` with governance params |
| `core/routes/projection.py` | `/api/v1/projection/governance` endpoint |
| `docs/PROJECTION_ASSEMBLY_GOVERNANCE.md` | This document |
| `tests/test_pr26_projection_assembly_governance.py` | Focused tests |

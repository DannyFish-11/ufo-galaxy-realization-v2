# Orchestration Observability Review — Operator Guide (PR-10)

> **Module**: `core/orchestration_review_surface.py`
> **Routes**: `GET /api/v1/observability/orchestration-review`
>             `GET /api/v1/observability/execution-legibility`
> **Tests**: `tests/test_pr10_orchestration_observability_review.py`
> **Authority sentinel**: `ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY`

---

## 1. Purpose

PR-10 closes the remaining observability and operator-review gaps in the V2
orchestration runtime.  Prior PRs established strong canonical structures for
execution path selection (PR-20), multimodal routing (PR-41), fallback tracing
(PR-24), execution trace contracts (PR-25), runtime observability sink (PR-G),
replay/audit persistence (PR-B2), and hybrid continuity (PR-59).

Despite this, reviewers still had to consult several independent modules to
answer common operational questions:

| Operational question | Prior state | PR-10 solution |
|---|---|---|
| *Why was this execution path chosen?* | Consult `runtime_decision_observability` manually | `execution_path_summary` in snapshot |
| *Did a fallback occur and what steps were taken?* | Reconstruct from arbiter logs | `fallback_cascade` in snapshot |
| *Can the last interrupted execution be resumed?* | Read `runtime_observability_sink` ring buffer | `recovery_review` in snapshot |
| *Was the last Android truth update accepted by V2?* | Check `android_participant_truth_ingress` logs | `reconciliation_review` in snapshot |
| *Are any legacy dispatch surfaces being invoked?* | Silent log warnings only (COMPAT-007) | `legacy_dispatch` counters in snapshot |

---

## 2. Gaps closed (PR-10)

### 2.1 Execution path legibility

**Gap**: Reviewers had to combine `RuntimeDecisionExplanation` fields from
`core.runtime_decision_observability` with routing analytics from
`core.routing_observability` to understand whether an execution path was
chosen, rejected (hard gate), or degraded.

**Solution**: `ExecutionPathDecisionSummary` consolidates this into a single
object with `outcome` (`chosen` / `rejected` / `degraded` / `unknown`),
`primary_reason`, `hard_gate_active`, and `hard_gate_reasons`.

### 2.2 Fallback cascade traceability

**Gap**: Fallback events were logged per-level by `WindowsExecutionArbiter`
but there was no structured representation of the full cascade sequence.

**Solution**: `FallbackCascadeReview` chains `FallbackCascadeStep` entries in
emission order, exposing `from_tier`, `to_tier`, `reason`, and `raw_reason` for
each degradation step.  `had_fallback` and `degraded_from_preferred` provide
at-a-glance status.

### 2.3 Recovery decision visibility

**Gap**: Recovery decisions from `core.runtime.runtime_observability_sink`
required reading the raw ring-buffer snapshot and finding the most recent
`recovery_decision_events` entry.

**Solution**: `RecoveryDecisionReview` surfaces the most recent recovery event
as a flat, legible struct: `decision_kind`, `is_resumable`,
`interruption_class`, `interruption_reason`, and `resume_attempt_count`.

### 2.4 Reconciliation audit surface

**Gap**: The outcome of Android/V2 truth reconciliation (whether advisory truth
was accepted, rejected because V2 is terminal, or advisory-only) was only
available by reading raw `AndroidParticipantReconcileOutcome` objects.

**Solution**:
- `android_participant_truth_ingress.py` now stores the last reconciliation
  outcome via `_record_last_reconciliation_outcome()` after every call to
  `reconcile_android_participant_truth()`.
- `get_last_reconciliation_outcome()` exposes it as a plain dict.
- `ReconciliationOutcomeReview` wraps it with classification:
  `accepted`, `rejected_v2_terminal`, `rejected_no_record`, or
  `partially_applied`.

### 2.5 Legacy dispatch counter (COMPAT-007)

**Gap** (COMPAT-007): `LEGACY_DISPATCH` warnings from sentinel-gated compat
surfaces were emitted to logs only.  No counter or monitoring surface existed.

**Solution**: `LegacyDispatchCounters` accumulates per-surface invocation
counts.  Call `increment_legacy_dispatch_counter(surface_name)` from any
`LEGACY_DISPATCH`-emitting code path.  Operators can read the current counters
via the `legacy_dispatch` field in the review snapshot or directly via
`get_legacy_dispatch_counters()`.

---

## 3. Authority boundaries

This module is **strictly read-only and observational**:

- It assembles diagnostics from canonical authority modules; it does not
  re-compute or replace any decision logic.
- Every field in `OrchestrationReviewSnapshot` carries a `source_authority`
  label identifying the originating canonical module.
- Routing, execution, and dispatch logic MUST NOT read from this module to
  influence their decisions.

The three authority-boundary policy sentinels:
- `REVIEW_SURFACE_IS_OBSERVATIONAL_ONLY_POLICY`
- `REVIEW_SURFACE_RESPECTS_AUTHORITY_BOUNDARIES_POLICY`
- `REVIEW_SURFACE_NEVER_DUPLICATES_CANONICAL_LOGIC_POLICY`

---

## 4. API endpoints

### `GET /api/v1/observability/orchestration-review`

Returns the full `OrchestrationReviewSnapshot` as a JSON object.

```json
{
  "snapshot_id": "a3b2c1…",
  "assembled_at": 1700000000.0,
  "execution_path_summary": {
    "execution_path": "agent_execute",
    "outcome": "chosen",
    "primary_reason": "canonical_path_selected",
    "hard_gate_active": false,
    "hard_gate_reasons": [],
    "active_soft_influences": 2,
    "model_selected": "gpt-4o",
    "provider_selected": "openai",
    "task_hint": "code_generation",
    "source_authority": "core.runtime_decision_observability",
    "assembled_at": 1700000000.0
  },
  "fallback_cascade": {
    "cascade_steps": [
      {
        "step_index": 0,
        "from_tier": "system_api",
        "to_tier": "gui",
        "reason": "executor_unavailable",
        "raw_reason": "SystemAPI not initialised",
        "authority": "core.windows_execution_arbiter"
      }
    ],
    "final_tier": "gui",
    "total_steps": 1,
    "had_fallback": true,
    "degraded_from_preferred": true,
    "source_authority": "core.execution_observability.fallback_schema",
    "assembled_at": 1700000000.0
  },
  "recovery_review": {
    "decision_kind": "resumable_reassociation",
    "is_resumable": true,
    "interruption_class": "process_restart",
    "interruption_reason": "host_crash",
    "recovery_reason": "session_context_available",
    "continuity_id": "cont_abc",
    "trace_id": "trace_xyz",
    "resume_attempt_count": 1,
    "source_authority": "core.runtime.runtime_observability_sink",
    "assembled_at": 1700000000.0
  },
  "reconciliation_review": {
    "outcome": "accepted",
    "was_reconciled": true,
    "v2_terminal_state_blocked": false,
    "advisory_only_fields_skipped": ["readiness_assessment"],
    "applied_signal_types": ["task_phase"],
    "device_id": "android_01",
    "task_id": "task_123",
    "source_authority": "core.android_participant_truth_ingress",
    "assembled_at": 1700000000.0
  },
  "legacy_dispatch": {
    "total_legacy_dispatch_count": 0,
    "per_surface_counts": {},
    "monitoring_authority": "COMPAT-007::…",
    "reset_at": 1700000000.0
  },
  "observability_authority": "ORCHESTRATION_REVIEW_SURFACE_IS_AUTHORITY: …",
  "_partial": false,
  "_partial_reasons": []
}
```

When one or more upstream modules are unavailable, `_partial` is `true` and
`_partial_reasons` lists the causes.  The surface never raises — it returns a
partial snapshot instead.

---

### `GET /api/v1/observability/execution-legibility`

Returns a compact, at-a-glance legibility view.

```json
{
  "schema_version": "pr10-v1",
  "assembled_at": 1700000000.0,
  "path": {
    "execution_path": "agent_execute",
    "outcome": "chosen",
    "primary_reason": "canonical_path_selected",
    "hard_gate_active": false
  },
  "fallback": {
    "had_fallback": false,
    "total_steps": 0,
    "final_tier": "",
    "degraded_from_preferred": false
  },
  "recovery": {
    "decision_kind": "unknown",
    "is_resumable": false,
    "interruption_class": "",
    "resume_attempt_count": 0
  },
  "legacy_usage": {
    "total_legacy_dispatch_count": 0,
    "per_surface_counts": {}
  },
  "_partial": false
}
```

---

## 5. Key data structures

| Structure | Purpose |
|---|---|
| `ExecutionPathDecisionSummary` | Why the execution path was chosen/rejected |
| `FallbackCascadeReview` | Ordered fallback degradation trace |
| `FallbackCascadeStep` | One step in the fallback cascade |
| `RecoveryDecisionReview` | Most recent interruption/recovery decision |
| `ReconciliationOutcomeReview` | Android/V2 reconciliation classification |
| `LegacyDispatchCounters` | COMPAT-007 legacy dispatch usage counters |
| `OrchestrationReviewSnapshot` | Full assembled operator review snapshot |

---

## 6. ExecutionPathOutcome values

| Value | Meaning |
|---|---|
| `chosen` | Path selected as the active execution route |
| `rejected` | Path explicitly rejected (hard gate / governance denial) |
| `degraded` | Path selected but at a lower tier than preferred |
| `unknown` | Outcome cannot be determined from available diagnostics |

---

## 7. ReconciliationOutcome values

| Value | Meaning |
|---|---|
| `accepted` | Android truth applied to V2 canonical state |
| `rejected_v2_terminal` | V2 already terminal; Android update rejected |
| `rejected_no_record` | No matching V2 tracking record found |
| `partially_applied` | Some signals applied; advisory fields (readiness_assessment, runtime_state) skipped |
| `unknown` | Outcome cannot be determined |

---

## 8. Legacy dispatch monitoring (COMPAT-007)

```python
from core.orchestration_review_surface import (
    increment_legacy_dispatch_counter,
    get_legacy_dispatch_counters,
)

# In any LEGACY_DISPATCH-emitting code path:
increment_legacy_dispatch_counter("cross_device_coordinator")

# In an operator monitoring script / alert rule:
counters = get_legacy_dispatch_counters()
if counters.total_legacy_dispatch_count > 0:
    alert("Unexpected legacy dispatch activity detected")
```

Counters are accumulated since process start (or the last
`reset_legacy_dispatch_counters()` call).  They are also visible in the
`legacy_dispatch` field of `GET /api/v1/observability/orchestration-review`.

---

## 9. How to use for operator review

### "Why did execution choose this path?"

```
GET /api/v1/observability/orchestration-review
→ execution_path_summary.outcome
→ execution_path_summary.primary_reason
→ execution_path_summary.hard_gate_active (and hard_gate_reasons)
```

### "Was there a fallback and how many steps?"

```
GET /api/v1/observability/execution-legibility
→ fallback.had_fallback
→ fallback.total_steps
→ fallback.final_tier
```

### "Can the last interrupted execution be resumed?"

```
GET /api/v1/observability/orchestration-review
→ recovery_review.decision_kind (resumable_reassociation / terminal_loss)
→ recovery_review.is_resumable
→ recovery_review.interruption_class
```

### "Was the last Android update accepted by V2?"

```
GET /api/v1/observability/orchestration-review
→ reconciliation_review.outcome
→ reconciliation_review.was_reconciled
→ reconciliation_review.v2_terminal_state_blocked
→ reconciliation_review.advisory_only_fields_skipped
```

### "Are legacy dispatch surfaces being called?"

```
GET /api/v1/observability/execution-legibility
→ legacy_usage.total_legacy_dispatch_count
→ legacy_usage.per_surface_counts
```

---

## 10. Acceptance criteria (PR-10)

A reviewer should be able to determine:

1. **Which observability/reviewability gaps were closed** — sections 2.1–2.5
   above.
2. **How to inspect execution decisions and lifecycle transitions** — sections
   4 and 9.
3. **Whether recovery, fallback, and reconciliation are auditable** — yes:
   `RecoveryDecisionReview`, `FallbackCascadeReview`, and
   `ReconciliationOutcomeReview` provide structured, labelled audit surfaces.
4. **Whether V2 is operationally legible without weakening authority
   boundaries** — yes: the review surface is purely observational; authority
   boundaries are documented via policy sentinels and `source_authority` fields;
   canonical truth modules are unchanged.

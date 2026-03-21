# Execution Policy Alignment Surface (PR-28)

## Overview

The **Execution Policy Alignment Surface** is a read-only, serialisable contract that answers, in one narrow structure, whether the current execution-policy signals are aligned or contradictory across runtime, projection, governance, and cross-device/device-formation surfaces.

It is the "policy explanation" layer that sits **above** the existing governance summaries and answers *why* the system chose a particular route or posture.

---

## What it is

The alignment surface is embodied by the `ExecutionPolicyAlignmentSummary` contract in `core/policy/alignment_surface.py`.

It assembles five **policy dimensions** into one stable object:

| Dimension | Source |
|---|---|
| `runtime_policy` | `RuntimeGovernanceSnapshot` (PR-27) |
| `readiness_policy` | `ReadinessResult` (PR-23) |
| `fallback_policy` | `FallbackDecisionTrace` (PR-24) |
| `dispatch_policy` | `DispatchSummary` / `HandoffPolicy` (PR-18) |
| `projection_policy` | `ProjectionGovernanceSummary` (PR-26) |

---

## How it differs from related surfaces

| Surface | What it answers |
|---|---|
| **Execution Trace** (PR-25) | *What happened?* — execution lifecycle lifecycle events |
| **Projection Assembly Governance** (PR-26) | *What governance state is visible in the projection?* |
| **Runtime Governance Snapshot** (PR-27) | *What is the current runtime posture?* — unified snapshot |
| **Execution Policy Alignment Surface** (PR-28) | *Are the policies aligned? If not, where and why?* |

The alignment surface does **not** replace any of the above; it consumes them.

---

## Policy signals considered

For each dimension, the following signals are extracted and compared:

- `blocked` — hard block on execution
- `degraded` — operating in reduced capacity
- `confirmation_required` — explicit human confirmation needed
- `cross_device_allowed` — whether cross-device expansion is permitted
- `runtime_domain` — resolved runtime domain
- `action_level` — graduated action permission level

---

## Policy posture values

The `policy_posture` field resolves to one of:

| Posture | Meaning |
|---|---|
| `local_preferred` | Local execution is preferred; cross-device not required |
| `local_then_expand` | Start local, may expand to cross-device |
| `remote_required` | Cross-device or remote execution is required |
| `blocked` | Hard block — no execution permitted |
| `degraded` | Operating in degraded mode — partial inputs or dimension conflicts |
| `confirmation_gated` | Execution requires explicit confirmation before proceeding |
| `unknown` | Insufficient data to determine posture |

---

## Aligned vs misaligned states

### Aligned state

All available policy dimensions agree on:
- No dimension signals `blocked=True`
- No dimension signals `degraded=True`
- All available `cross_device_allowed` signals agree
- No critical mismatches detected

Example aligned state:
```json
{
  "aligned": true,
  "blocked": false,
  "degraded": false,
  "confirmation_required": false,
  "policy_posture": "local_preferred",
  "mismatches": [],
  "alignment_hints": {
    "can_execute_locally": true,
    "can_expand_cross_device": false,
    "is_blocked": false,
    "effective_action_level": "execute",
    "alignment_confidence": 1.0,
    "hint_source": "full"
  }
}
```

### Misaligned state

At least two dimensions disagree on a policy signal. Example:

```json
{
  "aligned": false,
  "blocked": true,
  "policy_posture": "blocked",
  "mismatches": [
    {
      "dimension_a": "runtime_policy",
      "dimension_b": "readiness_policy",
      "field_a": "blocked",
      "field_b": "blocked",
      "value_a": false,
      "value_b": true,
      "severity": "critical",
      "description": "runtime_policy blocked=False conflicts with readiness_policy blocked=True"
    }
  ],
  "alignment_hints": {
    "is_blocked": true,
    "alignment_confidence": 0.6,
    "hint_source": "partial"
  }
}
```

---

## Blocked / degraded / confirmation-gated posture

### Blocked
`blocked=True` is set when **any** available dimension signals `blocked=True`. The `policy_posture` resolves to `"blocked"`. Downstream consumers should not proceed with execution.

### Degraded
`degraded=True` is set when:
- Two or more dimensions are individually in degraded state, **or**
- A critical mismatch is detected between dimensions, **or**
- The single available dimension signals `degraded=True`

The `policy_posture` resolves to `"degraded"`. Downstream consumers may proceed with caution.

### Confirmation-gated
`confirmation_required=True` is set when **any** available dimension signals `confirmation_required=True`. The `policy_posture` resolves to `"confirmation_gated"`. Downstream consumers must obtain explicit confirmation before proceeding.

---

## Alignment hints

The `alignment_hints` block (`ExecutionPolicyHints`) provides quick-access signals for downstream consumers:

| Hint | Type | Meaning |
|---|---|---|
| `can_execute_locally` | bool | Local execution currently permitted |
| `can_expand_cross_device` | bool | Cross-device expansion permitted by all dimensions |
| `is_confirmation_gated` | bool | Confirmation required |
| `is_blocked` | bool | Hard block active |
| `is_degraded` | bool | Degraded mode |
| `preferred_domain` | str\|null | Best-guess preferred runtime domain |
| `effective_action_level` | str | Most conservative action level across dimensions |
| `alignment_confidence` | float | Assessment confidence [0.0, 1.0] |
| `policy_posture` | str | Resolved posture (mirrors top-level) |
| `hint_source` | str | `"full"` / `"partial"` / `"empty"` |

---

## API surface

### `GET /api/v1/projection/policy-alignment`

Returns the `ExecutionPolicyAlignmentSummary` as a JSON payload. Read-only.

### Optional field on `RuntimeProjection`

The `policy_alignment` field on `RuntimeProjection` may carry the alignment summary when populated by callers.

---

## Module location

```
core/policy/alignment_surface.py
```

### Public contracts

- `ExecutionPolicyAlignmentSummary` — top-level alignment surface
- `AlignmentDimensionSummary` — per-dimension policy summary
- `AlignmentMismatch` — single detected mismatch
- `ExecutionPolicyHints` — quick-access hints

### Assembly helpers

- `build_execution_policy_alignment_surface(...)` — canonical entry point
- `summarize_runtime_policy_alignment(...)` — runtime dimension adapter
- `summarize_dispatch_policy_alignment(...)` — dispatch/handoff dimension adapter
- `summarize_projection_policy_alignment(...)` — projection dimension adapter

---

## What this PR explicitly does not do

- No Registered Runtime Device contract
- No Local Runtime Host contract
- No Handoff Envelope v2 redesign
- No Mesh Membership contract
- No Mesh Session contract
- No target runtime local takeover flow
- No device registration unification rewrite
- No UI redesign or dashboard rewrite
- No persistence or streaming system
- No command/write endpoints — read-only only
- Does not enforce policy — only describes the current posture

---

## Relationship to the governance chain

```
PR-22  ExecutionIntentProfile          → intent
PR-23  ReadinessResult                 → readiness gate
PR-24  FallbackDecisionTrace           → fallback posture
PR-25  ExecutionTraceEnvelope          → execution lifecycle trace
PR-26  ProjectionGovernanceSummary     → projection-safe governance assembly
PR-27  RuntimeGovernanceSnapshot       → unified runtime posture snapshot
PR-28  ExecutionPolicyAlignmentSummary → are all the above aligned?
```

PR-28 consumes all prior layers and answers whether they are currently consistent with each other.

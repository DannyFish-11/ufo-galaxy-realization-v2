# Routing Explanation & Decision Surface

**PR-21 (V4) — Additive read-only layer for routing decision explainability**

---

## Overview

The routing explanation layer unifies the routing decision signals that are
already present in the system — cross-device routing posture, execution-policy
band, device health, capability state, device formation, agent dispatch
governance — into a **stable, serialisable, read-only surface** that downstream
code can inspect to understand *why* a route was chosen.

This layer does not replace any router, does not add routing strategies, and
does not alter routing outcomes.  It is purely additive: it reads from existing
signals and exposes them in a normalised explanation format.

---

## Package: `core/routing_explanation/`

```
core/routing_explanation/
├── __init__.py             # Public API
├── decision_basis.py       # DecisionFactor enum + DecisionBasis dataclass
├── route_confidence.py     # ConfidenceBand enum + RouteConfidence dataclass
├── route_explanation.py    # RouteExplanation + RejectedCandidate dataclasses
└── explanation_summary.py  # RoutingExplanationSummary + projection helpers
```

---

## Decision Factors Captured

| Factor | Signal Source | Description |
|---|---|---|
| `policy` | `cross_device_policy.RoutingPolicy.posture` | Routing posture derived by the cross-device resolver |
| `health` | `unified.device_health.DeviceHealthScorer` | Composite health score (latency, error rate, jitter, heartbeat) |
| `capability` | `capability_runtime.CapabilityRuntimeState` | Capability availability / constraint flags |
| `latency` | `device_pool_manager` scoring | Observed or estimated round-trip latency |
| `availability` | UDM online devices list | Device online / offline / degraded status |
| `authority_role` | `orchestration_authority.AuthorityRole` | Orchestration authority that gates cross-device permission |
| `fallback` | `device_formation.fallback_device_ids` | Fallback path available or engaged |
| `execution_budget` | `execution_policy.policy_band` | Execution-policy band and budget constraints |
| `formation` | `device_formation.FormationSummary` | Device formation membership and barrier posture |
| `agent_handoff` | `agent_governance.DispatchSummary` | Agent dispatch role and handoff validity |

Each factor is represented as a `DecisionBasis` entry with:
- `factor` — the factor category (from `DecisionFactor` enum)
- `signal_value` — the raw value captured at explanation time
- `description` — human-readable explanation of how the factor influenced the decision
- `accepted` — `True` if the factor favoured the selected route; `False` if it
  was a constraint or rejection signal
- `weight` — relative weight used in confidence computation

---

## Confidence Score

The `RouteConfidence` model aggregates all `DecisionBasis` entries into a
single confidence score:

- **Score**: `0.0–1.0` (higher = more confident)
- **Band**:
  - `high` — score ≥ 0.75
  - `medium` — score in [0.45, 0.75)
  - `low` — score in [0.15, 0.45)
  - `undetermined` — score < 0.15 or no basis entries

Confidence is a **post-hoc read-only summary** derived from the collected
decision bases.  It is not a routing signal — it does not influence routing
outcomes.

---

## Explanation vs. Routing Policy Logic

| Dimension | Routing Policy Logic | Routing Explanation Layer |
|---|---|---|
| **Purpose** | Determines *which* route to take | Explains *why* that route was taken |
| **Timing** | Active during routing decision | Assembled after routing decision |
| **Mutability** | May update routing state | Read-only; never writes state |
| **Components** | `RoutingPolicy`, `RoutingPosture`, `RoutingResolver` | `DecisionBasis`, `RouteConfidence`, `RoutingExplanationSummary` |
| **Consumer** | Router, executor, transport | Status board, governance, debugging tools |
| **Effect on routing** | Drives dispatch decisions | Zero — purely observational |

The explanation layer reads from the same signals that routing policy already
uses (posture, policy reason, expansion flag) but packages them into an
inspectable, versioned surface without ever feeding back into routing logic.

---

## Integration Points

### 1. Read-Only Projection Endpoint

```
GET /api/v1/projection/routing-explanation
```

Returns the full projection payload (all prior layers: runtime, return
intelligence, execution policy, cross-device routing, merge summary, task
semantics, device formation, agent dispatch) plus two new keys:

- **`routing_explanation`** — full `RoutingExplanationSummary` dict
- **`explanation_hints`** — compact quick-check dict

Example response (routing_explanation block):

```json
{
  "schema_version": 1,
  "route_target": "android_01",
  "decision_basis_list": [
    {
      "factor": "policy",
      "signal_value": "local_preferred",
      "description": "Routing posture 'local_preferred': ...",
      "accepted": true,
      "weight": 0.3
    },
    {
      "factor": "execution_budget",
      "signal_value": "bounded_execute",
      "description": "Execution policy band: 'bounded_execute'",
      "accepted": true,
      "weight": 0.2
    }
  ],
  "confidence": {
    "score": 0.75,
    "band": "high",
    "basis_count": 2,
    "accepted_factor_count": 2,
    "rejected_factor_count": 0,
    "contributing_factors": ["policy", "execution_budget"],
    "reason": "2 accepted factor(s) / 0 constraint(s) across 2 distinct factor type(s) → confidence 0.750 (high)"
  },
  "rejected_alternatives": [],
  "fallback_plan": null,
  "owner_agent": "planner",
  "owner_component": "routing_explanation",
  "policy_posture": "local_preferred",
  "policy_band": "bounded_execute",
  "policy_reason": "runtime domain is not cross_device; local execution preferred",
  "is_cross_device": false,
  "has_fallback": false,
  "task_id": null,
  "trace_id": null
}
```

Example `explanation_hints` block:

```json
{
  "route_target": "android_01",
  "policy_posture": "local_preferred",
  "policy_band": "bounded_execute",
  "confidence_score": 0.75,
  "confidence_band": "high",
  "is_cross_device": false,
  "has_fallback": false,
  "has_rejected_alternatives": false,
  "rejected_count": 0,
  "basis_count": 2,
  "owner_agent": "planner"
}
```

### 2. Programmatic API

Downstream code can use the public Python API directly:

```python
from core.routing_explanation import (
    resolve_explanation_from_projection,
    get_explanation_hints,
    build_route_explanation,
    build_explanation_summary,
    make_decision_basis,
    DecisionFactor,
)

# Derive explanation from an assembled projection dict
summary = resolve_explanation_from_projection(projection_dict)

# Get quick-check hints
hints = get_explanation_hints(summary)
print(hints["confidence_band"])  # "high"
print(hints["is_cross_device"])  # True/False

# Build a custom explanation (e.g., from a live routing result)
from core.routing_explanation import (
    basis_from_health_score,
    basis_from_policy_posture,
    RejectedCandidate,
)

explanation = build_route_explanation(
    selected_target="android_01",
    decision_bases=[
        basis_from_policy_posture("local_preferred", "default local policy"),
        basis_from_health_score("android_01", health_score=0.91),
    ],
    rejected_candidates=[
        RejectedCandidate(
            candidate_id="tablet_01",
            rejection_reason="health score below threshold",
            health_score=0.30,
        )
    ],
    policy_posture="local_preferred",
    policy_reason="default local routing policy",
    owner_agent="planner",
)

summary = build_explanation_summary(explanation)
print(summary.confidence["band"])  # "high"
print(len(summary.rejected_alternatives))  # 1
```

### 3. Projection Enrichment

The `attach_explanation_to_projection` helper integrates with the existing
`core/routes/projection.py` chain:

```python
from core.routing_explanation import (
    attach_explanation_to_projection,
    resolve_explanation_from_projection,
    get_explanation_hints,
)

# In a custom projection assembler
base_projection = _assemble_projection_with_agent_dispatch()
summary = resolve_explanation_from_projection(base_projection)
enriched = attach_explanation_to_projection(base_projection, summary)
enriched["explanation_hints"] = get_explanation_hints(summary)
```

---

## How Downstream Code Should Consume Explanation Surfaces

### For Status Boards and Dashboards

Poll `GET /api/v1/projection/routing-explanation` and render:
- `explanation_hints.confidence_band` as a traffic-light indicator
- `routing_explanation.policy_posture` as the active routing mode
- `routing_explanation.decision_basis_list` as an expandable detail panel
- `routing_explanation.rejected_alternatives` to show what was considered

### For Governance and Audit

- Store `routing_explanation` dicts alongside task results for post-hoc audit
- Use `routing_explanation.trace_id` and `task_id` to correlate with
  distributed traces
- Check `routing_explanation.policy_band` against expected policy constraints
- Flag decisions where `confidence.band == "undetermined"` for review

### For Debugging

- Inspect `routing_explanation.decision_basis_list` to see which factors
  contributed and whether they were accepted or constrained
- Check `routing_explanation.rejected_alternatives` to understand which
  candidates were considered
- Use `explanation_hints.basis_count == 0` as a signal that the system was
  in an idle or uninitialised state

---

## Idle and Fallback Behaviour

When routing context is unavailable (system idle, uninitialised, or error
during assembly), the explanation layer returns safe pre-built sentinels:

| Sentinel | Module | Value |
|---|---|---|
| `IDLE_EXPLANATION_SUMMARY` | `explanation_summary` | `policy_posture="undecided"`, `confidence.band="undetermined"` |
| `EMPTY_ROUTE_EXPLANATION` | `route_explanation` | All empty; `policy_posture="undecided"` |
| `UNDETERMINED_CONFIDENCE` | `route_confidence` | `score=0.0`, `band="undetermined"` |

All public functions (`resolve_explanation_from_projection`,
`build_explanation_summary`, `compute_confidence`, etc.) catch exceptions
internally and return the appropriate sentinel rather than raising.

---

## What This PR Does Not Yet Solve

The following capabilities are explicitly **out of scope** for PR-21 and
represent future work:

1. **Automatic counterfactual simulation** — "What route would have been
   chosen if health score X were 0.5 instead of 0.9?" This requires running
   the resolver with modified inputs and comparing outcomes.

2. **Historical explanation store** — Persisting past routing explanations
   to a database or time-series store for trend analysis and drift detection.

3. **Live route monitoring** — Active observation of in-flight routing changes
   and generation of explanation deltas when routes shift.

4. **Explanation-driven re-routing** — Using confidence scores or rejected
   candidate data to proactively trigger re-routing before failures occur.
   The current layer is observational only.

5. **Per-request granularity** — The current implementation derives
   explanation from projection-level (system-level) signals rather than from
   a specific in-flight routing request.  Per-request explanation would require
   the router to emit structured explanation data on each decision.

6. **Explanation caching / registry** — A registry of the most recent routing
   explanation per task or device, queryable by task ID or trace ID.

---

## Schema Stability Contract

All `to_dict()` outputs are considered **stable** once merged:

- Existing keys will not be removed or renamed without a schema version bump.
- New fields may be added as optional keys with safe defaults in future PRs.
- `schema_version` is currently `1` on `RoutingExplanationSummary`.

---

## File Map

| File | Purpose |
|---|---|
| `core/routing_explanation/__init__.py` | Public API, all exports |
| `core/routing_explanation/decision_basis.py` | `DecisionFactor` enum, `DecisionBasis` dataclass, convenience builders |
| `core/routing_explanation/route_confidence.py` | `ConfidenceBand` enum, `RouteConfidence` dataclass, `compute_confidence()` |
| `core/routing_explanation/route_explanation.py` | `RejectedCandidate`, `RouteExplanation`, `build_route_explanation()` |
| `core/routing_explanation/explanation_summary.py` | `RoutingExplanationSummary`, `build_explanation_summary()`, `attach_*`, `resolve_*`, `get_hints()` |
| `core/routes/projection.py` | Added `GET /api/v1/projection/routing-explanation` endpoint and `_assemble_projection_with_routing_explanation()` |
| `tests/test_pr21_routing_explanation.py` | 67 focused tests (serialisation, confidence, integration endpoint) |
| `docs/ROUTING_EXPLANATION_AND_DECISION_SURFACE.md` | This document |

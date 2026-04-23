# Compat/Fallback Authority Boundary — Reviewer Guide

> **PR-9: Harden canonical truth authority boundaries and restrict compat
> fallback influence**
>
> Primary repo: `DannyFish-11/ufo-galaxy-realization-v2`.
> Companion context: `DannyFish-11/ufo-galaxy-android`.

---

## Purpose

This document enables a reviewer to answer the following questions for the
post-PR-9 runtime:

1. Which compat/fallback paths were previously too influential?
2. How is canonical authority now more strongly enforced in live runtime
   decisions?
3. Is compat behavior available but explicitly bounded?
4. Is the runtime now more reviewably governed by V2 canonical truth?

---

## Canonical authority chain

The canonical authority chain for live runtime decisions is:

```
DesktopPresenceRuntime   (runtime_shell_authority)
      │
      ▼
OpenClawd                (subject_decision_authority)
      │
      ▼
AgentKernel              (cognition_planning_layer)
      │
      ▼
CommandRouter            (execution_substrate)
```

Every live routing, state-transition, truth-compilation, and dispatch decision
must be driven primarily by this chain.  Compat and fallback paths are
explicitly **secondary**: they may only observe or assist within bounded scopes.

---

## Governance modules — where to look

| Concern | Module |
|---|---|
| Compat/fallback influence points registry | `core/compat_fallback_authority_guard.py` (PR-9) |
| Compat gap catalog (center-side) | `core/center_side_compat_closure.py` (PR-5) |
| Authority surface classification | `core/authority_boundary_classification.py` (PR-6) |
| Compat surface retirement inventory | `core/compat_surface_retirement.py` (PR-10) |
| Outward truth governance | `core/outward_runtime_truth.py` (PR-531) |
| Orchestration authority roles | `core/orchestration_authority/` (PR-9) |
| Legacy path registry | `core/orchestration_authority/legacy_paths.py` |
| Runtime closure audit | `core/runtime_closure_audit.py` |
| Fallback decision tracing | `core/execution/fallback_trace.py` (PR-24) |

---

## Influence point catalog summary

The table below lists every catalogued place where a compat or fallback path
could influence a canonical runtime decision, together with:

- The **canonical path** that should be the primary decision maker.
- The **compat/fallback path** whose influence is bounded.
- The **influence role** (observer / bounded_assist / degraded_fallback).
- The **bounding status** (how the influence is constrained).
- The **reviewer signal** — what to check to confirm canonical authority.

| ID | Decision site | Canonical path | Compat/fallback path | Role | Bounding | Reviewer signal |
|---|---|---|---|---|---|---|
| INFL-001 | Model/provider routing | `TopologyRouter.route()` | `MultiLLMRouter` | degraded_fallback | EXPLICITLY_BOUNDED | `routing_authority_source == 'topology_router'` in projection |
| INFL-002 | Provider list endpoint | `GET /api/v1/projection/runtime` | `dashboard.backend.main llm_providers` | bounded_assist | EXPLICITLY_BOUNDED | No routing code imports from `dashboard.backend.main` for routing |
| INFL-003 | Capability-based routing | `CapabilityAssimilationLayer` | `CapabilityRegistry` | bounded_assist | EXPLICITLY_BOUNDED | No routing context imports `CapabilityRegistry` for routing |
| INFL-004 | Cross-device dispatch | `CrossDeviceExecutionChain` via `CommandRouter` | `CrossDeviceCoordinator` | degraded_fallback | EXPLICITLY_BOUNDED | No `LEGACY_DISPATCH` warnings in logs |
| INFL-005 | Projection assembly | `ProjectionSurfaceBridge.enrich_runtime_projection()` | `ProjectionEngine` | bounded_assist | EXPLICITLY_BOUNDED | `ProjectionEngine` delegates to bridge; no raw subsystem imports |
| INFL-006 | Task status truth | `CanonicalTask` / `CanonicalTaskRuntime` | legacy `task_queue` | bounded_assist | EXPLICITLY_BOUNDED | Task status read from `CanonicalTaskRuntime` only |
| INFL-007 | Takeover/fallback routing | `resolve_takeover_or_fallback_route()` | stale session context | degraded_fallback | EXPLICITLY_BOUNDED | `REGISTRY_DISPATCH_MUST_CONSULT_REGISTRY_POLICY` enforced |
| INFL-008 | Node tool exposure | `NodeFabricRegistry → CapabilityResolver` | legacy Layer 3 node scan | degraded_fallback | EXPLICITLY_BOUNDED | `OPENCLAWD_LEGACY_NODE_SCAN_COMPAT` env var absent or false |

All eight influence points have bounding status **EXPLICITLY_BOUNDED** in the
post-PR-9 runtime.  There are **no UNBOUNDED** influence points.

---

## How to read the authority hardening snapshot

The `build_authority_hardening_snapshot()` function in
`core/compat_fallback_authority_guard.py` returns an
`AuthorityHardeningSnapshot` with:

```json
{
  "total_influence_points": 8,
  "by_bounding_status": {
    "explicitly_bounded": 8,
    "scope_limited": 0,
    "unbounded": 0,
    "retired": 0
  },
  "unbound_violation_count": 0,
  "hardening_complete": true,
  ...
}
```

A reviewer should confirm:
- `unbound_violation_count == 0` — no unbounded compat influence.
- `hardening_complete == true` — all influence points are explicitly bounded
  or retired; none are scope-limited or unbounded.

---

## Compat role taxonomy

The `CompatInfluenceRole` enum in `core/compat_fallback_authority_guard.py`
defines four roles:

| Role | Meaning | Can alter canonical decision? |
|---|---|---|
| `observer` | Reads runtime state, contributes nothing to the decision | No |
| `bounded_assist` | Contributes supplemental/enrichment data within an explicit scope | No (enrichment only) |
| `degraded_fallback` | Activated only when canonical path unavailable; temporary | Only when canonical unavailable |
| `unbound_influence` | Influences decisions without explicit scope — **policy violation** | Yes (violation) |

---

## Policy sentinels for CI / test assertions

The following sentinels are importable strings that CI gates and tests can
assert to confirm the hardening invariants are in place:

```python
from core.compat_fallback_authority_guard import (
    CANONICAL_AUTHORITY_MUST_BE_PRIMARY_DECISION_MAKER_POLICY,
    COMPAT_FALLBACK_MAY_ONLY_OBSERVE_OR_ASSIST_WITHIN_EXPLICIT_SCOPE_POLICY,
    UNBOUND_COMPAT_INFLUENCE_IS_POLICY_VIOLATION_POLICY,
    FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY,
)
```

---

## What changed in PR-9 vs prior state

| Area | Before PR-9 | After PR-9 |
|---|---|---|
| Influence point visibility | No single catalog; influence points were documented ad-hoc across multiple PRs | All 8 influence points catalogued in `core/compat_fallback_authority_guard.py` with explicit bounding status |
| Authority boundary reviewability | Reviewer had to trace through multiple modules to determine which path governed a decision | `CompatInfluenceRecord.reviewer_note` for each point explains exactly what a reviewer should check |
| Fallback role classification | Fallback paths documented as "legacy" but role in decision-making not explicitly classified | `CompatInfluenceRole` enum distinguishes observer / bounded_assist / degraded_fallback / unbound_influence |
| Hardening posture | No single surface summarised overall authority hardening status | `build_authority_hardening_snapshot()` provides a JSON-serialisable aggregate status |
| Decision-site guard helpers | No standard helper to check canonical authority at a decision site | `check_canonical_authority_at_decision_site()` and `assert_canonical_is_decision_authority()` for call-site use |
| Policy sentinels | Policies scattered across PR-5/6/10 modules | Four canonical PR-9 sentinels in `core/compat_fallback_authority_guard.py` |

---

## How compat paths can legitimately assist without becoming decision authorities

A compat or fallback path operates within its bounded role when:

1. **It is catalogued** in `core/compat_fallback_authority_guard.py` with an
   explicit `CompatInfluenceRecord`.
2. **Its `bounding_status` is `EXPLICITLY_BOUNDED`** — a concrete mechanism
   (sentinel, env-var gate, log warning, redirect) is cited in
   `bounding_evidence`.
3. **Its `influence_role` is `observer` or `bounded_assist`** for enrichment
   use, or `degraded_fallback` for resilience use.  Role `unbound_influence`
   is never permitted.
4. **Degraded fallback paths re-defer to the canonical path** as soon as it
   becomes available again (policy:
   `FALLBACK_MUST_NOT_SILENTLY_BECOME_CANONICAL_POLICY`).
5. **The decision-site guard** (`check_canonical_authority_at_decision_site`)
   is invoked when both paths are active, so any compat invocation is
   explicitly logged.

---

## Companion modules

- `core/center_side_compat_closure.py` — PR-5 compat gap closure (7 gaps,
  all FENCED).  Provides `check_compat_fence()` for gap-level fence checks.
- `core/authority_boundary_classification.py` — PR-6 authority surface
  taxonomy across SSOT, registries, caches, facades, adapters.
- `docs/MODEL_ROUTING_AUTHORITY.md` — routing authority policy for
  model/provider selection.
- `docs/COMPATIBILITY_RETIREMENT_IMPACT_MAP.md` — impact assessment for
  compatibility surface retirement.
- `docs/FALLBACK_DECISION_TRACE.md` — PR-24 canonical fallback decision
  trace object.
